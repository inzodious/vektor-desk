import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api.js';
import { cronWords, jobState, jobWord, refreshPlan, refusalText, runAndWait, scheduleWords, splitJobs } from './jobs.js';

describe('job words', () => {
  it('names jobs plainly', () => {
    expect(jobWord({ name: 'engine-quotes' }).title).toBe('Prices');
    expect(jobWord({ name: 'engine-lookthrough' }).title).toBe('Fund breakdowns');
    expect(jobWord({ name: 'agents-run-plan_keeper' }).title).toBe('Plan keeper desk');
    expect(jobWord({ name: 'brand-new', title: 'Brand new' }).title).toBe('Brand new');
  });

  it('reads cron lines in plain words', () => {
    expect(cronWords('20 8,17 * * *')).toBe('8:20 AM and 5:20 PM');
    expect(cronWords('40 0 * * *')).toBe('Daily at 12:40 AM');
    expect(cronWords('*/15 * * * *')).toBe('Every 15 min');
    expect(cronWords('*/5 4-20 * * 1-5')).toBe('Every 5 min, 4 AM to 8 PM on weekdays');
    expect(cronWords('10 1-6 * * *')).toBe('Hourly at :10, 1 AM to 6 AM');
    expect(cronWords('10 2 * * 0')).toBe('2:10 AM on Sundays');
    expect(cronWords('30 3 2 * *')).toBe('Monthly on day 2 at 3:30 AM');
    expect(cronWords('0 2 * 1-11 0')).toBe('2 AM on Sundays, Jan to Nov');
    expect(cronWords('0 2 * 12 *')).toBe('2 AM in Dec');
    expect(cronWords('* * * * *')).toBe('Every minute');
    expect(cronWords('0 9 1,15 * *')).toBe('0 9 1,15 * *');
    expect(scheduleWords({ schedules: [] })).toBe('Only when asked');
  });
});

describe('job state', () => {
  it('says how the last run went', () => {
    expect(jobState({ running: true, running_since: null }).state).toBe('running');
    expect(jobState({ queued: true }).line).toBe('Starting in a few seconds');
    expect(jobState({ last_run: null }).state).toBe('never');
    const failed = jobState({ last_run: { result: 'failed', finished: '2026-11-09T05:43:00Z', detail: 'SEC answered 503' } });
    expect(failed.state).toBe('failed');
    expect(failed.line).toMatch(/^Didn’t finish .*: SEC answered 503$/);
    expect(jobState({ last_run: { result: 'ok', finished: '2026-11-09T13:01:00Z', trigger: 'request' } }).line).toMatch(/on request$/);
  });

  it('splits data jobs from the rest', () => {
    const { main, rest } = splitJobs([{ name: 'agents-queue' }, { name: 'engine-daily' }, { name: 'mirror' }]);
    expect(main.map((j) => j.name)).toEqual(['mirror', 'engine-daily']);
    expect(rest.map((j) => j.name)).toEqual(['agents-queue']);
  });

  it('picks refresh jobs from the failing checks, mirror first', () => {
    const jobs = [
      { name: 'engine-daily', refreshes: ['holdings', 'value', 'closes'] },
      { name: 'mirror', refreshes: ['freshness', 'holdings', 'value'] },
      { name: 'engine-lots', refreshes: ['shares'] },
    ];
    expect(refreshPlan({ checks: [{ check_name: 'value', status: 'fail' }] }, jobs)).toEqual(['mirror', 'engine-daily']);
    expect(refreshPlan({ checks: [{ check_name: 'marginal_rate', status: 'warn' }] }, jobs)).toEqual([]);
    expect(refreshPlan({ checks: [{ check_name: 'value', status: 'ok' }, { check_name: 'shares', status: 'warn' }] }, jobs)).toEqual(['engine-lots']);
    expect(refreshPlan({ checks: [{ check_name: 'value', status: 'fail' }, { check_name: 'shares', status: 'warn' }] }, jobs)).toEqual(['mirror', 'engine-daily']);
  });

  it('turns refusals into friendly words', () => {
    expect(refusalText(new ApiError(503, 'x', { error: 'scheduler_down' }))).toMatch(/taking a break/);
    expect(refusalText(new ApiError(429, 'x', { error: 'cooldown', cooldown_until: '2026-11-09T16:45:00Z' }))).toMatch(/^Asked for a moment ago\. Try again at/);
    expect(refusalText(new ApiError(0, 'offline'))).toBe('offline');
  });
});

describe('runAndWait', () => {
  afterEach(() => vi.unstubAllGlobals());

  const respond = (status, body) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(body) });

  it('waits until the run it asked for has finished', async () => {
    const lists = [
      { jobs: [{ name: 'mirror', queued: true, last_run: null }] },
      { jobs: [{ name: 'mirror', running: true, last_run: { request_id: 'r1', finished: null, result: null } }] },
      { jobs: [{ name: 'mirror', last_run: { request_id: 'r1', finished: '2026-11-09T16:43:00Z', result: 'ok' } }] },
    ];
    const fetch = vi.fn((url, opts) => (opts?.method === 'POST' ? respond(202, { ok: true, request_id: 'r1' }) : respond(200, lists.shift())));
    vi.stubGlobal('fetch', fetch);
    const seen = [];
    const last = await runAndWait('mirror', { poll: 1, onState: (j) => seen.push(j.running ? 'running' : j.queued ? 'queued' : 'done') });
    expect(last.result).toBe('ok');
    expect(seen).toEqual(['queued', 'running', 'done']);
    expect(fetch.mock.calls[0][0]).toBe('/api/jobs/mirror/run');
  });

  it('follows a run already going instead of failing', async () => {
    const lists = [{ jobs: [{ name: 'engine-daily', running: true }] }, { jobs: [{ name: 'engine-daily', running: false, last_run: { request_id: null, result: 'ok', finished: 'x' } }] }];
    vi.stubGlobal('fetch', vi.fn((url, opts) => (opts?.method === 'POST' ? respond(409, { ok: false, error: 'running' }) : respond(200, lists.shift()))));
    expect((await runAndWait('engine-daily', { poll: 1 })).result).toBe('ok');
  });

  it('passes refusals on with their body', async () => {
    vi.stubGlobal('fetch', vi.fn(() => respond(429, { ok: false, error: 'cooldown', message: 'Mirror was asked for less than 5 minutes ago.' })));
    await expect(runAndWait('mirror', { poll: 1 })).rejects.toMatchObject({ status: 429, message: 'Mirror was asked for less than 5 minutes ago.', body: { error: 'cooldown' } });
  });
});

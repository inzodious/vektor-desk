import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api.js';
import { AUTO_EVERY_MS, autoPlan, cronWords, jobState, jobWord, plainLine, refreshPlan, refusalText, runAndWait, scheduleWords, splitJobs, stepTitle } from './jobs.js';

describe('job words', () => {
  it('names jobs plainly', () => {
    expect(jobWord({ name: 'engine-quotes' }).title).toBe('Prices');
    expect(jobWord({ name: 'engine-lookthrough' }).title).toBe('Fund breakdowns');
    expect(jobWord({ name: 'engine-lab-offer', title: 'Engine lab offer' }).title).toBe('Lab work to the worker');
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
    expect(cronWords('* 1-5 * * *')).toBe('Every minute, 1 AM to 6 AM');
    expect(cronWords('* 9-15 * * 1-5')).toBe('Every minute, 9 AM to 4 PM on weekdays');
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
    expect(jobState({ last_run: { result: 'ok', finished: '2026-11-09T13:01:00Z', trigger: 'start' } }).line).toMatch(/from Start the desk$/);
    const skipped = jobState({ last_run: { result: 'ok', finished: '2026-11-09T13:01:00Z', trigger: 'start', note: 'Price history is already complete.' } });
    expect(skipped.state).toBe('skipped');
    expect(skipped.line).toMatch(/from Start the desk: Price history is already complete\.$/);
    expect(jobState({ last_run: { result: 'failed', finished: '2026-11-09T05:43:00Z', error: 'the price feed timed out' } }).line).toMatch(/: the price feed timed out$/);
  });

  it('says when a job is waiting for its turn', () => {
    const turn = jobState({ waiting: true, waiting_since: '2026-11-09T22:35:02Z', last_run: { result: 'ok', finished: '2026-11-06T22:36:00Z' } });
    expect(turn.state).toBe('waiting');
    expect(turn.line).toMatch(/^Waiting for its turn since .*: low-memory mode runs heavy jobs one at a time$/);
    expect(jobState({ waiting: true, waiting_since: null }).line).toBe('Waiting for its turn: low-memory mode runs heavy jobs one at a time');
    expect(jobState({ running: true, waiting: true }).state).toBe('running');
    expect(refusalText({ body: { error: 'waiting' } })).toMatch(/already waiting for its turn/);
  });

  it('gives the real reason a job is waiting, and none when the desk names none', () => {
    expect(jobState({ waiting: true, waiting_since: null, waiting_for: 'memory' }).line).toBe('Waiting for its turn: low-memory mode runs heavy jobs one at a time');
    expect(jobState({ waiting: true, waiting_since: null, waiting_for: 'night' }).line).toBe('Waiting for its turn: the overnight run goes one step at a time');
    expect(jobState({ waiting: true, waiting_since: null, waiting_for: null }).line).toBe('Waiting for its turn');
    expect(jobState({ waiting: true, waiting_since: null, waiting_for: 'something new' }).line).toBe('Waiting for its turn');
    expect(refusalText({ body: { error: 'waiting', waiting_for: 'night' } })).toBe('It’s already waiting for its turn. The overnight run goes one step at a time.');
    expect(refusalText({ body: { error: 'waiting', waiting_for: null } })).toBe('It’s already waiting for its turn.');
    expect(refusalText({ body: { error: 'waiting' } })).toBe('It’s already waiting for its turn. Low-memory mode runs heavy jobs one at a time.');
  });

  it('shows what a finished run did, and never raw output', () => {
    const run = { result: 'ok', finished: '2026-11-09T13:01:00Z' };
    expect(jobState({ last_run: { ...run, did: ' Asked for 2 names. Nothing new. ', said: 'x' } }).did).toBe('Asked for 2 names. Nothing new.');
    expect(jobState({ last_run: { ...run, did: null, said: '{"filled": 0}' } }).did).toBeNull();
    expect(jobState({ last_run: { ...run, did: '{"filled": 0}' } }).did).toBeNull();
    expect(jobState({ last_run: run }).did).toBeNull();
    expect(plainLine('[1, 2]')).toBeNull();
    expect(plainLine('Traceback (most recent call last):')).toBeNull();
    expect(plainLine('')).toBeNull();
    expect(plainLine({ filled: 0 })).toBeNull();
    expect(plainLine('4 holdings analysed')).toBe('4 holdings analysed');
    expect(stepTitle({ job: 'mirror', title: 'Mirror' })).toBe('Accounts');
    expect(stepTitle({ job: 'night', title: 'Work up tonight’s buying opportunities' })).toBe('Work up tonight’s buying opportunities');
    expect(stepTitle({ id: 'agents-run-tax' })).toBe('Tax desk');
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

  it('refreshes by itself only what is free to run and was not asked for lately', () => {
    const jobs = [
      { name: 'engine-daily', refreshes: ['holdings', 'value', 'closes'], can_run: true },
      { name: 'mirror', refreshes: ['freshness', 'holdings', 'value'], can_run: false, cooldown_until: '2026-11-09T16:45:00Z' },
      { name: 'engine-lots', refreshes: ['shares'], can_run: true },
      { name: 'engine-backfill', refreshes: ['closes'], can_run: true, running: true },
    ];
    const now = Date.parse('2026-11-09T16:42:00Z');
    const fail = { checks: [{ check_name: 'value', status: 'fail' }, { check_name: 'closes', status: 'fail' }] };
    expect(autoPlan(fail, jobs, {}, now)).toEqual(['engine-daily']);
    expect(autoPlan(fail, jobs, { 'engine-daily': now - 60000 }, now)).toEqual([]);
    expect(autoPlan(fail, jobs, { 'engine-daily': now - AUTO_EVERY_MS }, now)).toEqual(['engine-daily']);
    expect(autoPlan({ checks: [{ check_name: 'shares', status: 'warn' }] }, jobs, { 'engine-lots': 'junk' }, now)).toEqual(['engine-lots']);
    expect(autoPlan({ checks: [{ check_name: 'marginal_rate', status: 'warn' }] }, jobs, {}, now)).toEqual([]);
    expect(autoPlan(null, jobs, {}, now)).toEqual([]);
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

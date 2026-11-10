import { describe, expect, it } from 'vitest';
import midday from '../fixtures/jobs.json';
import evening from '../fixtures/jobs.evening.json';
import fresh from '../fixtures/jobs.fresh.json';
import down from '../fixtures/jobs.down.json';
import { clockText, etParts, jobToday, runsToday, stageToday, todayRun, STAGES } from './todayRun.js';

const NOW = new Date('2026-11-09T16:42:00Z');
const stage = (run, id) => run.stages.find((s) => s.id === id);

describe('today’s run', () => {
  it('reads the Eastern clock', () => {
    expect(etParts(NOW)).toMatchObject({ dow: 1, month: 11, day: 9, minutes: 11 * 60 + 42 });
    expect(clockText(17 * 60 + 20)).toBe('5:20 PM');
    expect(clockText(8 * 60)).toBe('8:00 AM');
  });

  it('lists a cron line’s runs for today', () => {
    expect(runsToday('20 8,17 * * *', NOW)).toEqual([500, 1040]);
    expect(runsToday('45 16 * * 1-5', NOW)).toEqual([1005]);
    expect(runsToday('0 2 * * 6', NOW)).toEqual([]);
    expect(runsToday('30 3 2 * *', NOW)).toEqual([]);
    expect(runsToday('*/5 4-20 * * 1-5', NOW)).toEqual([]);
    expect(runsToday('0 3 * * 7', new Date('2026-11-08T16:00:00Z'))).toEqual([180]);
    expect(runsToday('nonsense', NOW)).toEqual([]);
  });

  it('places one job in the day', () => {
    const daily = midday.jobs.find((j) => j.name === 'engine-daily');
    expect(jobToday(daily, NOW)).toMatchObject({ state: 'waiting', ranToday: true, next: 1040 });
    expect(jobToday({ ...daily, running: true }, NOW).state).toBe('running');
    expect(jobToday({ ...daily, last_run: { ...daily.last_run, result: 'failed' } }, NOW).state).toBe('failed');
    expect(jobToday(daily, new Date('2026-11-09T23:30:00Z')).state).toBe('ok');
    expect(jobToday({ ...daily, last_run: null }, new Date('2026-11-09T23:30:00Z')).state).toBe('idle');
  });

  it('reads midday: morning runs done, evening runs still to come', () => {
    const run = todayRun(midday);
    expect(run.stages.map((s) => s.id)).toEqual(['mirror', 'engine', 'review', 'desks', 'paper']);
    expect(run.stages.map((s) => s.title)).toEqual(['Accounts', 'Numbers', 'Review', 'Desks', 'Paper']);
    expect(stage(run, 'mirror')).toMatchObject({ state: 'waiting', line: 'Ran 8:01 AM · Next 5:00 PM' });
    expect(stage(run, 'engine').line).toBe('Ran 8:24 AM · Next 5:20 PM');
    expect(stage(run, 'review')).toMatchObject({ state: 'soon', line: 'Arrives with the next desk update' });
    expect(stage(run, 'desks')).toMatchObject({ state: 'waiting', line: 'Next 5:30 PM', jobs: ['agents-run-plan_keeper'] });
    expect(stage(run, 'paper').line).toBe('Ran 8:46 AM · Next 4:45 PM');
    expect(run).toMatchObject({ head: 'More to run today', tone: '', total: 4 });
  });

  it('reads the evening: review in, debrief running', () => {
    const run = todayRun(evening);
    expect(stage(run, 'mirror')).toMatchObject({ state: 'ok', line: 'Ran 5:01 PM' });
    expect(stage(run, 'review')).toMatchObject({ state: 'ok', line: 'Ran 5:36 PM' });
    expect(stage(run, 'desks')).toMatchObject({ state: 'running', line: 'Debrief desk is running' });
    expect(stage(run, 'paper')).toMatchObject({ state: 'ok', line: 'Ran 4:46 PM' });
    expect(run).toMatchObject({ head: 'Running now', tone: 'info', done: 4, total: 5 });
  });

  it('calls out a stage that didn’t finish', () => {
    const jobs = evening.jobs.map((j) => (j.name === 'engine-review' ? { ...j, last_run: { ...j.last_run, result: 'failed' } } : { ...j, running: false }));
    const run = todayRun({ ...evening, jobs });
    expect(stage(run, 'review')).toMatchObject({ state: 'failed', line: 'Didn’t finish 5:36 PM' });
    expect(stage(run, 'desks')).toMatchObject({ state: 'ok', line: '1 ran, last 5:33 PM' });
    expect(run).toMatchObject({ head: '1 stage needs a look', tone: 'watch' });
  });

  it('says all done when nothing is left today', () => {
    const jobs = evening.jobs.map((j) => ({ ...j, running: false })).filter((j) => j.name !== 'agents-run-debrief');
    const run = todayRun({ ...evening, now: '2026-11-10T00:30:00Z', jobs });
    expect(run).toMatchObject({ head: 'All done today', tone: 'ok', done: 5, total: 5 });
  });

  it('follows the stages the API serves and falls back to names on an older desk', () => {
    const extra = todayRun({ ...evening, stages: [...evening.stages, 'backup'], jobs: [...evening.jobs, { name: 'ops-backup', stage: 'backup', schedules: ['0 3 * * *'], last_run: { finished: '2026-11-09T08:02:00Z', result: 'ok' } }] });
    expect(stage(extra, 'backup')).toMatchObject({ title: 'Backup', state: 'ok', line: 'Ran 3:02 AM' });
    const old = { now: evening.now, scheduler_alive: true, jobs: evening.jobs.map((j) => ({ ...j, stage: undefined })) };
    const run = todayRun(old);
    expect(run.stages.map((s) => s.id)).toEqual(STAGES.map((s) => s.id));
    expect(stage(run, 'review').jobs).toEqual(['engine-review']);
    expect(stage(run, 'desks').jobs).toEqual(['agents-run-plan_keeper', 'agents-run-debrief']);
  });

  it('handles a first day and a stopped scheduler', () => {
    const first = todayRun(fresh);
    expect(stage(first, 'engine')).toMatchObject({ state: 'waiting', line: 'Next 5:20 PM' });
    expect(todayRun(down)).toMatchObject({ head: 'Scheduler isn’t answering', tone: 'watch' });
    expect(todayRun({ jobs: [] }, NOW).head).toBe('Quiet day');
    expect(stageToday(STAGES[0], [{ name: 'mirror', schedules: ['0 2 * * 6'], last_run: { finished: '2026-11-07T07:00:00Z', result: 'ok' } }], NOW)).toMatchObject({ state: 'idle', line: 'Last ran Nov 7' });
  });
});

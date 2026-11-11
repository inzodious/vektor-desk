import { describe, expect, it } from 'vitest';
import none from '../fixtures/workers.json';
import online from '../fixtures/workers.horizon.json';
import asleep from '../fixtures/workers.asleep.json';
import joined from '../fixtures/workers.joined.json';
import { jobChip, nameProblem, startCommand, took, workerChip, workerRefusal, workerStrip, workersBusy, workersView } from './workers.js';

const NOW = new Date('2026-11-09T16:42:00Z');

describe('workers', () => {
  it('shows nothing when the desk does not serve workers', () => {
    expect(workersView(null)).toBeNull();
    expect(workersView({ detail: 'Not Found' })).toBeNull();
    expect(workerChip(null)).toBeNull();
    expect(workerStrip(null)).toBeNull();
  });

  it('reads a desk with no worker', () => {
    const v = workersView(none, NOW);
    expect(v).toMatchObject({ state: 'none', lead: 'No worker has joined. Everything runs on this box.', workers: [], jobs: [], waiting: 0, canAdd: true, canTest: false });
    expect(v.chip.t).toBe('No worker yet');
    expect(workerChip(none)).toBeNull();
    expect(workersBusy(none)).toBe(false);
  });

  it('reads a worker that is online and busy', () => {
    const v = workersView(online, NOW);
    expect(v).toMatchObject({ state: 'online', waiting: 1, open: 3, canTest: true });
    expect(v.workers[0]).toMatchObject({ name: 'Horizon', state: 'online', words: null, meta: 'Added 8:10 AM · on horizon · build a02ded6' });
    expect(v.jobs.map((j) => j.chip.t)).toEqual(['On the worker', 'Waiting', 'Being checked', 'Done', 'Done', 'Didn’t finish']);
    expect(v.jobs[0]).toMatchObject({ title: 'Lab simulations', why: 'Running on Horizon, started 3 minutes ago.', open: true, meta: 'Asked 11:38 AM' });
    expect(v.jobs[3].meta).toBe('9:09 AM · 3 min 42 s · 2.1 GB at peak');
    expect(v.jobs[5]).toMatchObject({ why: 'the worker ran out of memory and stopped it', meta: 'Nov 8, 5:41 PM · try 3' });
    expect(workersBusy(online)).toBe(true);
    expect(workerChip(online)).toMatchObject({ state: 'online', tone: 'ok', text: 'Horizon online', count: 0, to: '/settings/box#workers' });
    expect(workerStrip(online)).toBeNull();
  });

  it('says what waits for a sleeping worker', () => {
    const v = workersView(asleep, NOW);
    expect(v).toMatchObject({ state: 'asleep', waiting: 2, lead: 'Horizon is asleep or off: last heard 3 hours ago. 2 jobs waiting.' });
    expect(v.jobs[0].chip.t).toBe('Back in line');
    expect(v.jobs[1].why).toBe('Waiting for Horizon, which is asleep or off (last heard 3 hours ago).');
    expect(workerChip(asleep)).toMatchObject({ state: 'asleep', tone: 'watch', text: 'Horizon asleep · 2 waiting', count: 2 });
    expect(workerStrip(asleep)).toMatchObject({ key: 'asleep:2026-11-09T13:40:00Z', head: 'Work is waiting for Horizon', line: asleep.summary.words, to: '/settings/box#workers' });
    expect(workerStrip({ ...asleep, summary: { ...asleep.summary, waiting: 0 } })).toBeNull();
  });

  it('reads a worker that has a key but has not checked in', () => {
    const v = workersView(joined, NOW);
    expect(v).toMatchObject({ state: 'never', open: 0 });
    expect(v.workers[0]).toMatchObject({ state: 'never', meta: 'Added 11:40 AM' });
    expect(v.workers[0].chip.t).toBe('Not seen yet');
    expect(workerChip(joined)).toMatchObject({ tone: '', text: 'Horizon not seen yet' });
  });

  it('words a job and how long it took', () => {
    expect(jobChip({ state: 'leased', where: 'queue' }).t).toBe('Back in line');
    expect(jobChip({ state: 'returned' })).toMatchObject({ t: 'Being checked', live: true });
    expect(took(0.4)).toBe('0.4 s');
    expect(took(42.2)).toBe('42 s');
    expect(took(221.6)).toBe('3 min 42 s');
    expect(took(null)).toBeNull();
  });

  it('checks a name before asking the desk', () => {
    expect(nameProblem('')).toMatch(/Give it a name/);
    expect(nameProblem('Horizon!')).toMatch(/Up to 40 letters/);
    expect(nameProblem('horizon', ['Horizon'])).toBe('A worker already has that name.');
    expect(nameProblem(' Garage PC ')).toBeNull();
  });

  it('writes the start commands with the key and the desk address', () => {
    expect(startCommand(null)).toBeNull();
    const text = startCommand({ key: 'dwk_example_not_a_real_key', desk_url: 'https://desk-lan.example.test' });
    expect(text.split('\n')).toEqual(['git pull --ff-only', 'DESK_BUILD=$(git rev-parse HEAD) DESK_URL=https://desk-lan.example.test DESK_WORKER_KEY=dwk_example_not_a_real_key docker compose -f deploy/worker/compose.yaml up -d --build']);
    expect(startCommand({ key: 'dwk_example_not_a_real_key' })).not.toMatch(/DESK_URL/);
  });

  it('explains a refusal', () => {
    expect(workerRefusal({ status: 409, body: { error: 'too_many', message: 'Four workers at most.' } })).toBe('Four workers at most.');
    expect(workerRefusal({ status: 409, body: { error: 'no_data', message: 'There is no database to send yet.' } })).toBe('There is no database to send yet.');
    expect(workerRefusal({ status: 404, body: null })).toBe('Workers arrive with the next desk update.');
  });
});

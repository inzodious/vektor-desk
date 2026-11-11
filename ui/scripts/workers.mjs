import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const DIR = fileURLToPath(new URL('../src/fixtures/', import.meta.url));
const at = (hms, day = '2026-11-09') => `${day}T${hms}Z`;
const NOW = at('16:42:00');

// ---------- rows ----------
const horizon = (o = {}) => ({ id: 'a1b2c3d4e5f6', name: 'Horizon', added_at: at('13:10:00'), state: 'online', last_seen: at('16:41:48'), build: 'a02ded6', host: 'horizon', job_id: null, words: 'Horizon is online.', ...o });
const job = (id, kind, title, state, where, why, o = {}) => ({ id, kind, title, state, queued_at: at('16:38:00'), leased_at: null, finished_at: null, attempts: 0, seconds: null, peak_mb: null, where, why, ...o });
const CHECK = job('0a1b2c3d4e5f', 'worker.check', 'Check a database copy on the worker', 'done', null, 'The copy opened cleanly on the worker: 12 tables.', { queued_at: at('13:12:00'), leased_at: at('13:12:10'), finished_at: at('13:12:14'), attempts: 1, seconds: 0.4, peak_mb: 38 });
const SIMS_DONE = job('1b2c3d4e5f60', 'lab.sims', 'Lab simulations', 'done', null, 'Saved 48 simulations for the lab.', { queued_at: at('14:05:00'), leased_at: at('14:05:20'), finished_at: at('14:09:02'), attempts: 1, seconds: 221.6, peak_mb: 2140 });
const SIMS_FAILED = job('2c3d4e5f6071', 'lab.sims', 'Lab simulations', 'failed', null, 'the worker ran out of memory and stopped it', { queued_at: at('22:05:00', '2026-11-08'), leased_at: at('22:05:30', '2026-11-08'), finished_at: at('22:41:00', '2026-11-08'), attempts: 3, seconds: null, peak_mb: null });
const HEARD = 'last heard 3 hours ago';

// ---------- states ----------
const none = { now: NOW, summary: { state: 'none', name: null, waiting: 0, words: 'No worker has joined. Everything runs on this box.' }, workers: [], jobs: [] };

const online = {
  now: NOW,
  summary: { state: 'online', name: 'Horizon', waiting: 1, words: 'Horizon is online, working on: Lab simulations.' },
  workers: [horizon({ job_id: '9f8e7d6c5b4a', words: 'Horizon is online, working on: Lab simulations.' })],
  jobs: [
    job('9f8e7d6c5b4a', 'lab.sims', 'Lab simulations', 'leased', 'worker', 'Running on Horizon, started 3 minutes ago.', { leased_at: at('16:38:20'), attempts: 1 }),
    job('8e7d6c5b4a39', 'worker.check', 'Check a database copy on the worker', 'queued', 'queue', 'Next in line for Horizon.', { queued_at: at('16:41:00') }),
    job('7d6c5b4a3928', 'lab.sims', 'Lab simulations', 'returned', 'here', 'Back from the worker. The desk checks it and saves it within a few seconds.', { queued_at: at('16:20:00'), leased_at: at('16:20:10'), attempts: 1, seconds: 932.4, peak_mb: 3120 }),
    SIMS_DONE,
    CHECK,
    SIMS_FAILED,
  ],
};

const asleep = {
  now: NOW,
  summary: { state: 'asleep', name: 'Horizon', waiting: 2, words: `Horizon is asleep or off: ${HEARD}. 2 jobs waiting.` },
  workers: [horizon({ state: 'asleep', last_seen: at('13:40:00'), words: `Horizon is asleep or off: ${HEARD}.` })],
  jobs: [
    job('9f8e7d6c5b4a', 'lab.sims', 'Lab simulations', 'leased', 'queue', 'Horizon went quiet while running it. It goes back in line when a worker checks in.', { queued_at: at('13:36:00'), leased_at: at('13:36:20'), attempts: 1 }),
    job('8e7d6c5b4a39', 'lab.sims', 'Lab simulations', 'queued', 'queue', `Waiting for Horizon, which is asleep or off (${HEARD}).`, { queued_at: at('15:05:00') }),
    job('6c5b4a392817', 'worker.check', 'Check a database copy on the worker', 'queued', 'queue', `Waiting for Horizon, which is asleep or off (${HEARD}).`, { queued_at: at('16:30:00') }),
    CHECK,
  ],
};

const joined = {
  now: NOW,
  summary: { state: 'never', name: 'Horizon', waiting: 0, words: "Horizon has a key but hasn't checked in yet." },
  workers: [horizon({ state: 'never', last_seen: null, build: null, host: null, added_at: at('16:40:00'), words: "Horizon has a key but hasn't checked in yet." })],
  jobs: [],
};

export function workersFixtures() {
  return { workers: none, 'workers.horizon': online, 'workers.asleep': asleep, 'workers.joined': joined };
}

// ---------- write ----------
for (const [name, body] of Object.entries(workersFixtures())) {
  writeFileSync(`${DIR}${name}.json`, `${JSON.stringify(body, null, 1)}\n`);
  console.log(`wrote ${name}.json`);
}

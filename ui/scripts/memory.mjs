import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const DIR = fileURLToPath(new URL('../src/fixtures/', import.meta.url));
const at = (hms, day = '2026-11-09') => `${day}T${hms}Z`;
const read = (name) => JSON.parse(readFileSync(`${DIR}${name}.json`, 'utf8'));
const TURN = 'Waiting for its turn: low-memory mode runs heavy jobs one at a time.';
const WHY = 'The box has 512 MB free, under the 1.5 GB floor.';
const CAP = 'It needed more memory than the scheduler is allowed (640 MB) and was stopped.';

// ---------- the block ----------
const KILLED = [
  { at: at('19:03:22'), kind: 'job', name: 'agents-run-debrief', scope: 'cap', words: 'Agents run debrief was stopped: it needed more memory than the scheduler is allowed.' },
  { at: at('18:10:00'), kind: 'service', name: 'lab', scope: 'cap', words: 'The desk’s lab needed more memory than it is allowed, and python was stopped.' },
  { at: at('17:20:00', '2026-11-08'), kind: 'outside', name: 'smbd', scope: 'box', words: 'The box ran out of memory and stopped smbd, a program outside the desk.' },
];
const WAITING = [{ job: 'engine-review', title: 'Engine review', since: at('22:35:02') }];
const LOW_NOTE =
  'The box has 512 MB of 15.0 GB free, and no swap. Its ZFS file cache holds 6.0 GB, which it hands back under pressure, but slowly. Low-memory mode is on: the lab and the eval session are paused, and heavy jobs run one at a time. Waiting for a turn: Engine review. Stopped for memory in the last two days: 3. Latest: Agents run debrief was stopped: it needed more memory than the scheduler is allowed.';

const calm = {
  state: 'ok',
  total_mb: 15360,
  available_mb: 6144,
  swap_mb: 0,
  cache_mb: 2048,
  scheduler: { limit_mb: 640, used_mb: 180 },
  low_memory: { on: false, mode: 'auto', why: null, since: null, paused: [], low_mb: 1500, roomy_mb: 4000 },
  waiting: [],
  killed: [],
  host_seen: true,
  note: 'The box has 6.0 GB of 15.0 GB free, and no swap. Its ZFS file cache holds 2.0 GB, which it hands back under pressure, but slowly.',
};

const low = {
  ...calm,
  state: 'tight',
  available_mb: 512,
  cache_mb: 6144,
  scheduler: { limit_mb: 640, used_mb: 300 },
  low_memory: { on: true, mode: 'auto', why: WHY, since: at('20:00:00'), paused: ['lab', 'eval'], low_mb: 1500, roomy_mb: 4000 },
  waiting: WAITING,
  killed: KILLED,
  note: LOW_NOTE,
};

const blind = {
  ...calm,
  state: 'unknown',
  total_mb: null,
  available_mb: null,
  swap_mb: null,
  cache_mb: null,
  scheduler: null,
  killed: KILLED.slice(0, 1),
  host_seen: false,
  note: 'The box’s memory can’t be read from here. Stopped for memory in the last two days: 1. Latest: Agents run debrief was stopped: it needed more memory than the scheduler is allowed.',
};

const brief = (m) => ({ state: m.state, low_memory: m.low_memory.on, killed: m.killed.length, note: m.note });

// ---------- jobs taking turns ----------
function lowJobs(evening) {
  const jobs = evening.jobs.map((j) => {
    const row = { ...j, running: false, running_since: null, waiting: false, waiting_since: null };
    if (j.name === 'agents-run-plan_keeper') return { ...row, running: true, running_since: at('22:30:00'), can_run: false, last_run: null };
    if (j.name === 'engine-review') return { ...row, waiting: true, waiting_since: at('22:35:02'), can_run: false, last_run: { ...j.last_run, started: at('22:35:00', '2026-11-06'), finished: at('22:36:00', '2026-11-06') } };
    if (j.name === 'agents-run-debrief') return { ...row, last_run: { trigger: 'request', request_id: 'c0ffee123456', started: at('19:01:10'), finished: at('19:03:22'), result: 'failed', exit_code: 137, detail: null, error: CAP, oom: 'cap' } };
    return row;
  });
  return { ...evening, now: at('22:41:00'), low_memory: { on: true, why: WHY }, jobs };
}

// ---------- the chain taking turns ----------
function lowStart(running) {
  let seen = false;
  const steps = running.steps.map((s) => {
    if (s.state !== 'running' || seen) return s;
    seen = true;
    return { ...s, detail: TURN };
  });
  return { ...running, memory: brief(low), steps };
}

function lowReadiness(ready) {
  const sections = ready.sections.map((s) =>
    /^results\.(day|week|month|year)$/.test(s.key) ? { ...s, state: 'stale', why: 'It’s waiting for its turn: low-memory mode runs heavy jobs one at a time.', action: { kind: 'job', job: 'engine-review', label: 'Write it now' }, next_auto: null, next_auto_text: null } : s,
  );
  return { ...ready, memory: brief(low), sections };
}

export function memoryFixtures({ evening, start, running, readiness }) {
  return {
    memory: calm,
    'memory.low': low,
    'memory.blind': blind,
    'jobs.low': lowJobs(evening),
    'start.low': { ...start, memory: brief(low) },
    'start.lowstart': lowStart(running),
    'start.blind': { ...start, memory: brief(blind) },
    'readiness.low': lowReadiness(readiness),
  };
}

// ---------- write ----------
const made = memoryFixtures({ evening: read('jobs.evening'), start: read('start'), running: read('start.starting'), readiness: read('readiness') });
for (const [name, body] of Object.entries(made)) {
  writeFileSync(`${DIR}${name}.json`, `${JSON.stringify(body, null, 1)}\n`);
  console.log(`wrote ${name}.json`);
}

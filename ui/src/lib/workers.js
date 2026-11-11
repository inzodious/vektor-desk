import { when } from './box.js';
import { size } from './memory.js';

export const WORKERS_EVENT = 'desk:workers';
const MAX_WORKERS = 4;
const NAME = /^[A-Za-z0-9 _-]{1,40}$/;
const WORKER = {
  online: { t: 'Online', tone: 'ok' },
  asleep: { t: 'Asleep', tone: '' },
  never: { t: 'Not seen yet', tone: 'info' },
};
const HEAD = {
  none: { t: 'No worker yet', tone: '' },
  ...WORKER,
};
const OPEN = ['queued', 'leased', 'returned'];

// ---------- time ----------
export function took(seconds) {
  const s = Number(seconds);
  if (seconds == null || !Number.isFinite(s) || s < 0) return null;
  if (s < 10) return `${Math.round(s * 10) / 10} s`;
  if (s < 90) return `${Math.round(s)} s`;
  return `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, '0')} s`;
}

// ---------- one job ----------
export function jobChip(job) {
  if (job?.state === 'queued') return { t: 'Waiting', tone: '' };
  if (job?.state === 'leased') return job.where === 'worker' ? { t: 'On the worker', tone: 'ok', live: true } : { t: 'Back in line', tone: '' };
  if (job?.state === 'returned') return { t: 'Being checked', tone: 'info', live: true };
  if (job?.state === 'failed') return { t: 'Didn’t finish', tone: 'watch' };
  return { t: 'Done', tone: 'ok' };
}

function jobRow(job, now) {
  const open = OPEN.includes(job.state);
  const meta = [];
  if (!open && job.finished_at) meta.push(when(job.finished_at, now));
  if (open && job.queued_at) meta.push(`Asked ${when(job.queued_at, now)}`);
  if (took(job.seconds)) meta.push(took(job.seconds));
  if (job.peak_mb != null) meta.push(`${size(job.peak_mb)} at peak`);
  if (job.attempts > 1) meta.push(`try ${job.attempts}`);
  return { id: job.id, title: job.title || 'A job', why: job.why || null, state: job.state, open, chip: jobChip(job), meta: meta.filter(Boolean).join(' · ') || null };
}

// ---------- the panel ----------
export function workersView(block, now = new Date()) {
  if (!block || typeof block !== 'object' || !block.summary) return null;
  const state = HEAD[block.summary.state] ? block.summary.state : 'none';
  const lead = block.summary.words || null;
  const workers = (block.workers || []).map((w) => {
    const meta = [w.added_at ? `Added ${when(w.added_at, now)}` : null, w.host ? `on ${w.host}` : null, w.build ? `build ${String(w.build).slice(0, 7)}` : null].filter(Boolean).join(' · ');
    return { id: w.id, name: w.name, state: WORKER[w.state] ? w.state : 'never', chip: WORKER[w.state] || WORKER.never, words: w.words && !(lead || '').startsWith(w.words) ? w.words : null, meta: meta || null };
  });
  const jobs = (block.jobs || []).map((j) => jobRow(j, now));
  const waiting = Number(block.summary.waiting) || 0;
  return {
    state,
    chip: HEAD[state],
    lead,
    waiting,
    workers,
    jobs,
    open: jobs.filter((j) => j.open).length,
    canAdd: workers.length < MAX_WORKERS,
    canTest: workers.length > 0,
  };
}

export const workersBusy = (block) => (block?.jobs || []).some((j) => OPEN.includes(j.state));

// ---------- the top bar chip ----------
export function workerChip(block) {
  const s = block?.summary;
  if (!s || !WORKER[s.state] || !s.name) return null;
  const waiting = Number(s.waiting) || 0;
  const held = s.state !== 'online' && waiting > 0;
  const word = s.state === 'online' ? 'online' : s.state === 'asleep' ? 'asleep' : 'not seen yet';
  return { state: s.state, tone: held ? 'watch' : s.state === 'online' ? 'ok' : '', text: `${s.name} ${word}${held ? ` · ${waiting} waiting` : ''}`, count: held ? waiting : 0, label: s.words || `${s.name} is ${word}.`, to: '/settings/box#workers' };
}

// ---------- the one-line strip ----------
export function workerStrip(block) {
  const s = block?.summary;
  const waiting = Number(s?.waiting) || 0;
  if (!s || !s.name || !waiting || (s.state !== 'asleep' && s.state !== 'never')) return null;
  const seen = (block.workers || []).find((w) => w.name === s.name)?.last_seen || 'never';
  return { key: `${s.state}:${seen}`, head: `Work is waiting for ${s.name}`, line: s.words || `${waiting} waiting.`, to: '/settings/box#workers', label: 'See workers' };
}

// ---------- adding one ----------
export function nameProblem(name, taken = []) {
  const n = String(name || '').trim();
  if (!n) return 'Give it a name, like Horizon.';
  if (!NAME.test(n)) return 'Up to 40 letters, digits, spaces, dashes or underscores.';
  if (taken.some((t) => String(t).toLowerCase() === n.toLowerCase())) return 'A worker already has that name.';
  return null;
}

export function startCommand(made) {
  if (!made?.key) return null;
  const url = made.desk_url ? `DESK_URL=${made.desk_url} ` : '';
  return ['git pull --ff-only', `DESK_BUILD=$(git rev-parse HEAD) ${url}DESK_WORKER_KEY=${made.key} docker compose -f deploy/worker/compose.yaml up -d --build`].join('\n');
}

export function workerRefusal(err) {
  const body = err?.body || {};
  if (typeof body.message === 'string' && body.message) return body.message;
  if (body.error === 'too_many') return 'Four workers is the most the desk takes. Remove one first.';
  if (body.error === 'unknown_worker') return 'That worker is already gone. Refresh the page.';
  if (err?.status === 404) return 'Workers arrive with the next desk update.';
  return err?.message || 'The desk didn’t take that. Try again in a moment.';
}

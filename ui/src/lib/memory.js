import { when } from './box.js';
import { jobWord } from './jobs.js';

const PAUSED = { lab: 'the strategy lab', eval: 'the eval session' };
const STATE = {
  ok: { t: 'Enough room', tone: '' },
  tight: { t: 'Tight', tone: 'watch' },
  unknown: { t: 'Can’t read it', tone: '' },
};

// ---------- sizes ----------
export function size(mb) {
  if (mb == null || !Number.isFinite(Number(mb))) return null;
  const n = Number(mb);
  return n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${Math.round(n).toLocaleString('en-US')} MB`;
}

function list(words) {
  if (words.length < 2) return words[0] || '';
  return `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`;
}

// ---------- the switch ----------
export function modeChoices(low) {
  const floor = size(low?.low_mb) || '1.5 GB';
  const roomy = size(low?.roomy_mb) || '4.0 GB';
  return [
    { mode: 'auto', title: 'Automatic', blurb: `On under ${floor} free, off again above ${roomy}` },
    { mode: 'on', title: 'On', blurb: 'Heavy jobs take turns, and the lab and eval session pause' },
    { mode: 'off', title: 'Off', blurb: 'Everything runs side by side' },
  ];
}

export function modeLine(low, state) {
  if (!low) return null;
  if (low.on) return low.why ? `On right now. ${low.why}` : 'On right now.';
  if (low.mode === 'off' && state === 'tight') return 'Off, and the box is tight on memory, so a job may be stopped part way.';
  if (low.mode === 'off') return 'Off. Everything runs side by side.';
  return `Off right now. It switches itself on under ${size(low.low_mb) || '1.5 GB'} free.`;
}

export function pausedLine(low) {
  const names = (low?.paused || []).map((p) => PAUSED[p] || p);
  if (!low?.on || !names.length) return null;
  return `Paused until it is off: ${list(names)}.`;
}

export function modeRefusal(err) {
  const body = err?.body || {};
  if (typeof body.message === 'string' && body.message) return body.message;
  if (err?.status === 404) return 'This switch arrives with the next desk update.';
  return err?.message || 'The desk didn’t take that. Try again in a moment.';
}

// ---------- the card ----------
export function memoryView(block, now = new Date()) {
  if (!block || typeof block !== 'object' || !block.low_memory) return null;
  const state = STATE[block.state] ? block.state : 'unknown';
  const total = Number(block.total_mb);
  const free = Number(block.available_mb);
  const known = state !== 'unknown' && total > 0 && Number.isFinite(free);
  const facts = [];
  if (known) facts.push({ k: 'Swap', v: block.swap_mb ? size(block.swap_mb) : 'None' });
  if (block.cache_mb != null) facts.push({ k: 'File cache', v: size(block.cache_mb), hint: 'Handed back under pressure, but slowly' });
  if (block.scheduler?.limit_mb) facts.push({ k: 'Scheduler', v: block.scheduler.used_mb != null ? `${size(block.scheduler.used_mb)} of ${size(block.scheduler.limit_mb)}` : `Up to ${size(block.scheduler.limit_mb)}` });
  const low = block.low_memory;
  return {
    state,
    chip: STATE[state],
    head: known ? `${size(free)} free of ${size(total)}` : 'The box’s memory can’t be read from here',
    used: known ? Math.min(1, Math.max(0, 1 - free / total)) : null,
    facts,
    low: { on: Boolean(low.on), mode: ['auto', 'on', 'off'].includes(low.mode) ? low.mode : 'auto' },
    line: modeLine(low, state),
    paused: pausedLine(low),
    choices: modeChoices(low),
    waiting: (block.waiting || []).map((w) => ({ job: w.job, title: jobWord({ name: w.job, title: w.title }).title, since: when(w.since, now) })),
    killed: (block.killed || []).filter((k) => k?.words).map((k) => ({ at: k.at, when: when(k.at, now), words: k.words, scope: k.scope === 'cap' ? 'cap' : 'box' })),
    hostSeen: block.host_seen !== false,
  };
}

// ---------- the one-line strip ----------
export function memoryStrip(mem) {
  if (!mem || typeof mem !== 'object') return null;
  const killed = Number(mem.killed) || 0;
  const low = Boolean(mem.low_memory);
  if (!low && !killed) return null;
  const parts = [];
  if (low) parts.push('Low-memory mode is on, so heavy jobs run one at a time.');
  if (killed) parts.push(`${killed === 1 ? 'One thing was' : `${killed} things were`} stopped for memory in the last two days.`);
  return { key: `${low ? 1 : 0}:${killed}`, tone: killed ? 'watch' : 'info', head: killed ? 'The box is short on memory' : 'Taking it slow', line: parts.join(' '), to: '/settings/box#memory', label: 'See memory' };
}

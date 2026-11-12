import { dayWords } from './charts.js';
import { etTime } from './format.js';
import { plainLine, stepTitle } from './jobs.js';
import { todayEt } from './tax.js';

// ---------- when ----------
export function whenWords(iso, now = new Date()) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const day = todayEt(d);
  return day === todayEt(now) ? `Today, ${etTime(d)}` : `${dayWords(day)}, ${etTime(d)}`;
}

export function passWords(next, now = new Date()) {
  if (!next) return null;
  const text = String(next);
  if (!/^\d{4}-\d{2}-\d{2}T/.test(text)) return text;
  const words = whenWords(text, now);
  return words ? `${words} ET` : null;
}

// ---------- overnight steps ----------
const STEP_WORD = {
  ok: { t: 'Done', dot: 'ok' },
  skipped: { t: 'Skipped', dot: 'skipped' },
  failed: { t: 'Didn’t finish', dot: 'failed' },
  running: { t: 'Running now', dot: 'running' },
  waiting: { t: 'Waiting for its turn', dot: 'waiting' },
};

export function nightSteps(night, now = new Date()) {
  const steps = Array.isArray(night?.steps) ? night.steps : [];
  if (!night || night.state === 'idle') return [];
  return steps.map((s) => {
    const word = STEP_WORD[s.state] || { t: 'To come', dot: 'never' };
    const lines = [plainLine(s.ready), plainLine(s.detail)].filter(Boolean);
    return { id: s.id, title: stepTitle(s), state: s.state, word: word.t, dot: word.dot, when: whenWords(s.finished_at || s.started_at, now), line: lines.join(' ') || null };
  });
}

// ---------- doors ----------
const DOWN = 'The desk did not answer. It tries again by itself.';

function gate(api, soon) {
  if (api?.data) return null;
  if (!api || api.loading) return { state: 'loading', count: '…', unit: '', line: 'Checking…', fresh: null };
  if (api.error?.status === 404) return { state: 'off', count: '—', unit: '', line: soon, fresh: null };
  return { state: 'down', count: '—', unit: '', line: DOWN, fresh: null };
}

function parts(pairs) {
  return pairs
    .filter(([n]) => n > 0)
    .map(([n, word]) => `${n} ${word}`)
    .join(', ');
}

export function strategiesDoor(api, now = new Date()) {
  const g = gate(api, 'The strategy library arrives with the next desk update.');
  if (g) return g;
  const d = api.data;
  const c = d.counts || {};
  const tested = c.tested || 0;
  const total = c.total || 0;
  if (!tested) {
    const why = (d.rows || []).find((r) => r.reason)?.reason;
    return { state: 'waiting', count: `0 of ${total}`, unit: 'tested', line: why || 'Nothing has been tested yet.', fresh: null };
  }
  const rest = parts([
    [c.within_noise, 'inside the noise'],
    [c.fell_short, 'fell short'],
    [c.inconclusive, 'inconclusive'],
    [(c.waiting || 0) + (c.not_run || 0), 'still to run'],
  ]);
  return {
    state: 'ready',
    count: tested === total ? `${tested}` : `${tested} of ${total}`,
    unit: 'tested',
    line: `${c.held_up || 'None'} held up out of sample.${rest ? ` ${rest[0].toUpperCase()}${rest.slice(1)}.` : ''}`,
    fresh: whenWords(d.as_of, now),
  };
}

export function holdingsDoor(api, now = new Date()) {
  const g = gate(api, 'One analysis per holding arrives with the next desk update.');
  if (g) return g;
  const d = api.data;
  const analysed = d.analysed || 0;
  return {
    state: analysed ? 'ready' : 'waiting',
    count: `${analysed} of ${d.held || 0}`,
    unit: 'analysed',
    line: d.line || (analysed ? '' : 'No holding has been analysed yet.'),
    fresh: whenWords(d.fresh_at, now),
    tone: d.failed ? 'watch' : '',
  };
}

export function opportunitiesDoor(api, now = new Date()) {
  const g = gate(api, 'The ranked list arrives with the next desk update.');
  if (g) return g;
  const d = api.data;
  const total = d.counts?.total ?? (d.rows || []).length;
  return {
    state: total ? 'ready' : 'waiting',
    count: `${total}`,
    unit: total === 1 ? 'idea' : 'ideas',
    line: total ? d.headline : d.note || d.headline || 'Nothing on the list yet.',
    fresh: total ? whenWords(d.freshness?.night_run_at || d.built_at, now) : null,
  };
}

export const DOORS = [
  { key: 'strategies', title: 'Strategies tested', to: '/strategies', icon: 'flag', api: '/api/lab/library', view: strategiesDoor, go: 'See what held up' },
  { key: 'holdings', title: 'Your holdings analysed', to: '/research', icon: 'book', api: '/api/agents/holdings', view: holdingsDoor, go: 'Read each one' },
  { key: 'opportunities', title: 'Buying opportunities', to: '/research/opportunities', icon: 'bolt', api: '/api/opportunities', view: opportunitiesDoor, go: 'See the list' },
];

// ---------- strategy library ----------
export const LIB_VERDICT = {
  held_up: { t: 'Held up', tone: 'ok' },
  within_noise: { t: 'Inside the noise', tone: '' },
  fell_short: { t: 'Fell short', tone: 'watch' },
  inconclusive: { t: 'Inconclusive', tone: 'lilac' },
};
export const LIB_STATUS = { waiting: { t: 'Waiting to run', tone: 'info' }, not_run: { t: 'Not run', tone: '' } };

export function libraryChip(row) {
  if (row.status === 'tested') return LIB_VERDICT[row.verdict] || { t: row.yardstick ? 'Yardstick' : 'Tested', tone: '' };
  return LIB_STATUS[row.status] || { t: 'Waiting to run', tone: 'info' };
}

export function excessWords(row) {
  const v = row.out_of_sample?.excess_pts;
  if (row.status !== 'tested' || v == null || Number.isNaN(v)) return null;
  const s = Math.abs(v).toFixed(1);
  const zero = !/[1-9]/.test(s);
  return `${zero ? '' : v < 0 ? '−' : '+'}${s} pts a year`;
}

export function libraryGroups(d) {
  if (!d || !Array.isArray(d.rows)) return [];
  const kinds = Array.isArray(d.kinds) && d.kinds.length ? d.kinds : [...new Set(d.rows.map((r) => r.kind))].map((key) => ({ key, title: key }));
  return kinds
    .map((k) => {
      const rows = d.rows.filter((r) => r.kind === k.key);
      const tested = rows.filter((r) => r.status === 'tested').length;
      const held = rows.filter((r) => r.verdict === 'held_up').length;
      return { key: k.key, title: k.title, rows, tested, held, line: tested ? `${tested} tested · ${held || 'none'} held up` : `${rows.length} waiting` };
    })
    .filter((g) => g.rows.length);
}

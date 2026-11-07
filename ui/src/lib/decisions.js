import { dayLabel } from './charts.js';

export const DECISION_TABS = [
  { to: '/decisions', label: 'Queue', end: true },
  { to: '/decisions/journal', label: 'Journal' },
  { to: '/decisions/flight', label: 'Flight record' },
];

export const DESK_NAME = {
  plan_keeper: 'Plan keeper',
  tax: 'Tax desk',
  risk: 'Risk desk',
  research: 'Research desk',
  skeptic: 'Skeptic',
  scout: 'Scout',
  strategy: 'Strategy lab',
  you: 'You',
};

export const DESK_KEY = { plan_keeper: 'plan', tax: 'tax', risk: 'risk', research: 'research', skeptic: 'skeptic', scout: 'scout', strategy: 'plan', you: 'me' };

export const FUNDING = { deposit: 'From deposit', cash: 'From cash', margin: 'On margin', sale_proceeds: 'Sale proceeds' };

export const KIND = {
  buy: 'Buy',
  sell: 'Sell',
  trim: 'Trim',
  rebalance: 'Rebalance',
  harvest: 'Harvest',
  deposit_route: 'Deposit route',
  hold_off: 'Hold off',
  alert: 'Alert',
  memo: 'Memo',
  rule_change: 'Rule change',
  logged_trade: 'Logged trade',
};

export const LAMPS = [
  { id: 'concentration', label: 'Concentration' },
  { id: 'drift_after', label: 'Drift after' },
  { id: 'funding', label: 'Funding' },
  { id: 'wash_sales', label: 'Wash sales' },
  { id: 'lots_tax', label: 'Lots and tax' },
  { id: 'plan_rules', label: 'Plan rules' },
];

export const LAMP_WORD = { ok: 'clear', watch: 'heads up', act: 'needs a reason' };
export const LAMP_COLOR = { ok: 'var(--mint)', watch: 'var(--mustard)', act: 'var(--coral)' };

export const STATUS = {
  proposed: { t: 'Waiting', tone: 'info' },
  snoozed: { t: 'Snoozed', tone: '' },
  approved: { t: 'To place', tone: 'watch' },
  placed: { t: 'Placed', tone: 'info' },
  filled: { t: 'Filled', tone: 'ok' },
  done: { t: 'Done', tone: 'ok' },
  dismissed: { t: 'Dismissed', tone: '' },
  passed: { t: 'Passed', tone: 'info' },
  expired: { t: 'Expired', tone: '' },
  rejected: { t: 'Rejected', tone: '' },
  logged: { t: 'Logged', tone: '' },
};

export const PREFLIGHT_WORD = { clear: 'All clear', flagged: 'Heads up', blocked: 'Needs a reason', pending: 'Not checked yet', error: "Preflight couldn't run", none: 'No trade to check' };

export function lampsOf(d) {
  const lights = d?.preflight?.lights;
  if (!Array.isArray(lights) || !lights.length) return null;
  const by = Object.fromEntries(lights.map((l) => [l.id, l]));
  return LAMPS.map((l) => ({ ...l, ...(by[l.id] || {}), status: by[l.id]?.status || 'ok', label: by[l.id]?.label || l.label }));
}

export function needsReason(d) {
  return d?.preflight_status === 'flagged' || d?.preflight_status === 'blocked';
}

export function lampSummary(lamps) {
  if (!lamps) return null;
  const act = lamps.filter((l) => l.status === 'act').length;
  const watch = lamps.filter((l) => l.status === 'watch').length;
  if (act) return { tone: 'act', text: `${act} need${act === 1 ? 's' : ''} a reason` };
  if (watch) return { tone: 'watch', text: `${watch} heads up` };
  return { tone: 'ok', text: 'All clear' };
}

export function preflightMetric(d, id) {
  return (d?.preflight?.metrics || []).find((m) => m.metric_id === id) || null;
}

export function originName(origin) {
  return DESK_NAME[origin] || origin || 'Unknown';
}

export function kindName(kind) {
  return KIND[kind] || (kind ? kind.replace(/_/g, ' ') : '');
}

export function expiresLabel(iso) {
  if (!iso) return null;
  return `Expires ${dayLabel(iso.slice(0, 10))}`;
}

export function scoreOf(d, window = '30D') {
  const sc = d?.scores || {};
  const s = sc[window] ?? sc[window.toUpperCase()] ?? sc[window.toLowerCase()];
  if (s == null) return null;
  if (typeof s === 'number') return s;
  return typeof s.value === 'number' ? s.value : typeof s.usd === 'number' ? s.usd : typeof s.vs_plan === 'number' ? s.vs_plan : null;
}

export const SCORE_WINDOWS = [
  { v: '30D', t: '30 days' },
  { v: '90D', t: '90 days' },
  { v: '365D', t: 'a year' },
];

export function latestScore(d) {
  for (const w of [...SCORE_WINDOWS].reverse()) {
    const v = scoreOf(d, w.v);
    if (v != null) return { w: w.v, t: w.t, v };
  }
  return null;
}

export function scoresOn(d, days = 30) {
  if (!d?.created_at) return null;
  const t = new Date(Date.parse(d.created_at) + days * 86400000);
  return dayLabel(t.toISOString().slice(0, 10));
}

export function reasonOf(d) {
  return d?.override_reason || d?.status_reason || null;
}

export function oneLine(text) {
  if (!text) return '';
  const first = text.split(/(?<=[.!?])\s/)[0];
  return first.length > 160 ? `${first.slice(0, 157)}…` : first;
}

import { accountLabel } from '../live/context.js';
import { pct } from './format.js';

export const LAB_TABS = [
  { to: '/lab', label: 'Compare', end: true },
  { to: '/lab/risk', label: 'Risk' },
  { to: '/lab/mixes', label: 'Mixes' },
  { to: '/lab/strategies', label: 'Strategies' },
  { to: '/lab/patterns', label: 'Patterns' },
  { to: '/lab/boards', label: 'Boards' },
];

export const WINDOWS = ['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', '10Y', 'MAX'].map((v) => ({ v, t: { '1M': '1 month', '3M': '3 months', '6M': '6 months', YTD: 'Year to date', '1Y': '1 year', '3Y': '3 years', '5Y': '5 years', '10Y': '10 years', MAX: 'All history' }[v] }));

export const SLOT_COLORS = ['var(--s1)', 'var(--s2)', 'var(--s3)', 'var(--s4)', 'var(--s5)'];
export const MAX_SLOTS = 5;
export const DEFAULT_IDS = ['portfolio', 'shadow:plan_shadow', 'shadow:sp500_shadow'];

export const SPECIAL = [
  { v: 'portfolio', t: 'Your portfolio' },
  { v: 'shadow:plan_shadow', t: 'Plan shadow' },
  { v: 'shadow:sp500_shadow', t: 'S&P 500 shadow' },
];

export function idLabel(id) {
  const s = SPECIAL.find((x) => x.v === id);
  if (s) return s.t;
  if (id.startsWith('account:')) return accountLabel(id.slice(8));
  if (id.startsWith('shadow:')) return id.slice(7).replace(/_/g, ' ');
  return id;
}

export function isSymbol(id) {
  return !!id && id !== 'portfolio' && !id.includes(':');
}

export function parseIds(raw) {
  const ids = String(raw || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => (s.includes(':') || s === 'portfolio' ? s : s.toUpperCase()));
  return [...new Set(ids)].slice(0, MAX_SLOTS);
}

const signed = (v, d = 1) => pct(v / 100, d, true);

export const COMPARE_METRICS = [
  { key: 'return_pct', t: 'Return', fmt: (v) => signed(v), tone: 'sign', tag: '' },
  { key: 'vol_pct', t: 'Volatility', fmt: (v) => pct(v / 100), tone: 'item', tag: 'sky' },
  { key: 'mdd_pct', t: 'Max drawdown', fmt: (v) => pct(v / 100), tone: 'sign', tag: 'mustard' },
  { key: 'return_per_risk', t: 'Return per unit of risk', fmt: (v) => v.toFixed(2), tone: 'sign', tag: 'mint' },
  { key: 'expense_pct', t: 'Expense ratio', fmt: (v) => pct(v / 100, 2), tone: 'item', tag: 'coral', none: 'Not on file' },
  { key: 'corr_sp500', t: 'Correlation to the S&P 500', fmt: (v) => v.toFixed(2), tone: 'item', tag: 'lilac' },
];

export const TABLE_COLS = [
  { key: 'return_pct', t: 'Return', fmt: (v) => signed(v) },
  { key: 'ann_return_pct', t: 'A year, averaged', fmt: (v) => signed(v), none: 'Under a year' },
  { key: 'vol_pct', t: 'Volatility', fmt: (v) => pct(v / 100) },
  { key: 'mdd_pct', t: 'Max drawdown', fmt: (v) => pct(v / 100) },
  { key: 'return_per_risk', t: 'Return per risk', fmt: (v) => v.toFixed(2) },
  { key: 'corr', t: 'Correlation to first', fmt: (v) => v.toFixed(2) },
  { key: 'beta', t: 'Beta to first', fmt: (v) => v.toFixed(2) },
  { key: 'corr_sp500', t: 'Correlation to S&P', fmt: (v) => v.toFixed(2) },
  { key: 'expense_pct', t: 'Expense', fmt: (v) => pct(v / 100, 2) },
  { key: 'yield_pct', t: 'Yield', fmt: (v) => pct(v / 100, 1) },
  { key: 'overlap_pct', t: 'Overlap with first', fmt: (v) => pct(v / 100, 0) },
  { key: 'after_tax_pct', t: 'After tax', fmt: (v) => signed(v) },
];

export function seriesRows(data) {
  const ids = data?.ids || [];
  const maps = ids.map((id) => new Map((data?.series?.[id] || []).map((r) => [r.date, r.value])));
  const x = [...new Set(ids.flatMap((id) => (data?.series?.[id] || []).map((r) => r.date)))].sort();
  return { x, values: maps.map((m) => x.map((d) => (m.has(d) ? m.get(d) : null))) };
}

export function drawdown(values) {
  let hi = null;
  return values.map((v) => {
    if (v == null) return null;
    hi = hi == null ? v : Math.max(hi, v);
    return hi ? (v / hi - 1) * 100 : 0;
  });
}

export function alignSeries(a, b) {
  const bm = new Map((b || []).map((r) => [r.date, r.value]));
  const rows = (a || []).filter((r) => bm.has(r.date));
  return { x: rows.map((r) => r.date), a: rows.map((r) => r.value), b: rows.map((r) => bm.get(r.date)) };
}

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function monthlyReturns(rows, months = 12) {
  const last = new Map();
  (rows || []).forEach((r) => {
    if (r.close != null) last.set(r.date.slice(0, 7), r.close);
  });
  const keys = [...last.keys()].sort();
  const out = [];
  for (let k = 1; k < keys.length; k += 1) out.push({ month: keys[k], ret: last.get(keys[k]) / last.get(keys[k - 1]) - 1 });
  return out.slice(-months);
}

export function monthGrid(bySymbol, months = 12) {
  const per = Object.fromEntries(Object.entries(bySymbol).map(([s, rows]) => [s, monthlyReturns(rows, months + 1)]));
  const cols = [...new Set(Object.values(per).flatMap((r) => r.map((m) => m.month)))].sort().slice(-months);
  const rows = Object.keys(per);
  const values = rows.map((s) => cols.map((c) => per[s].find((m) => m.month === c)?.ret ?? null));
  return { rows, cols, labels: cols.map((c) => MON[Number(c.slice(5, 7)) - 1]), values };
}

export function chunkIds(ids, size = MAX_SLOTS) {
  if (ids.length < 2) return [];
  const out = [];
  for (let k = 0; k < ids.length; k += size) out.push(ids.slice(k, k + size));
  const tail = out[out.length - 1];
  if (tail.length === 1 && out.length > 1) tail.unshift(out[out.length - 2].pop());
  return out;
}

export function pairMatrix(rows) {
  const pairs = rows.filter((m) => m.metric_id === 'risk.corr' && m.scope === 'pair' && m.value != null);
  const syms = [...new Set(pairs.flatMap((m) => m.scope_id.split('|')))].sort();
  const get = (a, b) => pairs.find((m) => m.scope_id === `${a}|${b}` || m.scope_id === `${b}|${a}`)?.value ?? null;
  return { syms, values: syms.map((a) => syms.map((b) => (a === b ? null : get(a, b)))) };
}

export const SCENARIOS = [
  { id: 'gfc_2008', t: '2008 replay' },
  { id: 'covid_2020', t: 'March 2020 replay' },
  { id: 'rates_2022', t: '2022 rates replay' },
  { id: 'market_-20', t: 'Market −20%' },
  { id: 'satellite_-50', t: 'Single stocks −50%' },
  { id: 'rates_+2', t: 'Rates +2 points' },
];

export function scenarioItems(rows) {
  return SCENARIOS.map((s) => {
    const usd = rows.find((m) => m.metric_id === 'risk.scenario' && m.scope_id === s.id);
    const p = rows.find((m) => m.metric_id === 'risk.scenario_pct' && m.scope_id === s.id);
    if (!usd) return null;
    const short = usd.quality === 'insufficient_history' || usd.value == null;
    return { label: s.t, value: short ? null : usd.value, pct: p?.value ?? null, quality: usd.quality, note: short ? 'Needs older prices' : undefined, hint: usd.quality && usd.quality !== 'ok' ? usd.quality.replace(/_/g, ' ') : undefined };
  }).filter(Boolean);
}

// ---------- saved boards ----------
const KEY = 'desk.boards.v1';

export function readBoards(store = globalThis.localStorage) {
  try {
    const v = JSON.parse(store?.getItem(KEY) || '[]');
    return Array.isArray(v) ? v.filter((b) => b && typeof b.path === 'string' && b.path.startsWith('/lab')) : [];
  } catch {
    return [];
  }
}

export function writeBoards(list, store = globalThis.localStorage) {
  try {
    store?.setItem(KEY, JSON.stringify(list.slice(0, 50)));
    return true;
  } catch {
    return false;
  }
}

export function addBoard(board, store = globalThis.localStorage, now = new Date()) {
  const list = readBoards(store).filter((b) => b.path !== board.path);
  const next = [{ id: `b${now.getTime().toString(36)}`, saved_at: now.toISOString(), ...board }, ...list];
  return writeBoards(next, store) ? next : null;
}

export function removeBoard(id, store = globalThis.localStorage) {
  const next = readBoards(store).filter((b) => b.id !== id);
  writeBoards(next, store);
  return next;
}

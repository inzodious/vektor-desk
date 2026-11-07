import { FACTOR_WORD } from './strategy.js';

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export const FACTORS = ['mkt_rf', 'smb', 'hml', 'rmw', 'cma', 'mom'];
const LEAN = {
  smb: ['small companies', 'big companies'],
  hml: ['value', 'growth'],
  rmw: ['profitable firms', 'thin-margin firms'],
  cma: ['careful spenders', 'heavy spenders'],
  mom: ['recent winners', 'recent losers'],
};
const TILT = 0.15;
const SHORT = { mkt_rf: 'Mkt', smb: 'Size', hml: 'Value', rmw: 'Profit', cma: 'Invest', mom: 'Mom' };

// ---------- FI path ----------
export function monthYear(day) {
  if (!day) return null;
  return `${MON[Number(day.slice(5, 7)) - 1]} ${day.slice(0, 4)}`;
}

export function shortUsd(v) {
  if (v == null || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  const s = a >= 1e6 ? `${(a / 1e6).toFixed(2).replace(/\.?0+$/, '')}M` : a >= 1e3 ? `${Math.round(a / 1e3)}K` : `${Math.round(a)}`;
  return `${v < 0 ? '−' : ''}$${s}`;
}

export function fiState(v) {
  if (!v || v.fi_number == null) return 'no_goal';
  if (v.status !== 'ok' || !v.lines?.length) return 'no_history';
  return 'ok';
}

export function fiChart(v) {
  if (fiState(v) !== 'ok') return null;
  const x = [v.as_of, ...v.lines.map((l) => l.date)];
  const pick = (k) => [v.start_value, ...v.lines.map((l) => l[k])];
  const series = [
    { name: 'Fast 10%', short: 'Fast 10%', values: pick('p90'), color: 'var(--s5)', dash: true },
    { name: 'Middle', short: 'Middle', values: pick('p50'), color: 'var(--s1)', width: 2.5 },
    { name: 'Slow 10%', short: 'Slow 10%', values: pick('p10'), color: 'var(--s4)', dash: true },
  ];
  const t = v.target_date ? x.findIndex((d) => d >= v.target_date) : -1;
  return { x, series, target: t > 0 ? t : null };
}

export function yearTicks(x, narrow) {
  const every = narrow ? 10 : 5;
  const first = Number(x[0]?.slice(0, 4));
  return x
    .map((d, i) => ({ i, y: Number(d.slice(0, 4)) }))
    .filter((t) => t.i > 0 && (t.y - first) % every === 0)
    .map((t) => ({ i: t.i, label: String(t.y) }));
}

export function fiHeadline(v) {
  const mid = v?.fi_date?.p50;
  const years = v?.months ? Math.round(v.months / 12) : null;
  if (mid) return { big: monthYear(mid), line: 'on the middle path' };
  if (v?.reached_share) return { big: 'Past the horizon', line: `${Math.round(v.reached_share * 100)}% of paths get there within ${years} years` };
  return { big: 'Not in view yet', line: `no path gets there within ${years} years` };
}

export function onTimeText(share) {
  if (share == null) return null;
  const p = Math.round(share * 100);
  if (p >= 90) return 'Nearly every path makes it';
  if (p >= 60) return 'Most paths make it';
  if (p >= 40) return 'About a coin flip';
  if (p >= 15) return 'Some paths make it; the middle one runs later';
  return 'Few paths make it as things stand';
}

export function fiRange(v) {
  const d = v?.fi_date || {};
  const years = v?.months ? Math.round(v.months / 12) : null;
  const when = (day) => (day ? `by ${monthYear(day)}` : `beyond ${years} years`);
  return { fast: when(d.p10), slow: when(d.p90) };
}

// ---------- factor exposure ----------
export function leanWord(f, v) {
  if (v == null) return null;
  if (f === 'mkt_rf') return v >= 1.1 ? 'swings more than the market' : v <= 0.9 ? 'swings less than the market' : 'moves with the market';
  if (Math.abs(v) < TILT) return 'no lean';
  return `leans to ${LEAN[f][v > 0 ? 0 : 1]}`;
}

export function factorBars(loadings = {}) {
  return FACTORS.filter((f) => loadings?.[f] != null).map((f) => ({ label: FACTOR_WORD[f], value: loadings[f], hint: leanWord(f, loadings[f]) }));
}

export function leanSummary(loadings = {}) {
  const tilts = FACTORS.slice(1)
    .filter((f) => loadings?.[f] != null && Math.abs(loadings[f]) >= TILT)
    .sort((a, b) => Math.abs(loadings[b]) - Math.abs(loadings[a]))
    .slice(0, 2)
    .map((f) => LEAN[f][loadings[f] > 0 ? 0 : 1]);
  if (!tilts.length) return 'Mostly the market, no strong lean';
  return `Leans to ${tilts.join(' and ')}`;
}

export function holdingGrid(holdings = {}) {
  const rows = Object.keys(holdings || {}).sort((a, b) => (holdings[b].weight || 0) - (holdings[a].weight || 0));
  return {
    rows,
    cols: FACTORS.map((f) => FACTOR_WORD[f]),
    short: FACTORS.map((f) => SHORT[f]),
    values: rows.map((s) => FACTORS.map((f) => holdings[s].loadings?.[f] ?? null)),
  };
}

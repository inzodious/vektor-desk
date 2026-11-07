import { dayLabel } from './charts.js';
import { pct } from './format.js';

// ---------- words ----------
export const STAGES = [
  { v: 'draft', t: 'Draft', line: 'Written, not run' },
  { v: 'lab', t: 'Lab', line: 'Backtested, tuning' },
  { v: 'paper', t: 'Paper', line: 'Six months of fake money' },
  { v: 'eligible', t: 'Eligible', line: 'May back a proposal' },
];

export const STATUS = {
  draft: { t: 'Draft', tone: '' },
  lab: { t: 'In the lab', tone: 'info' },
  research: { t: 'Research only', tone: 'lilac' },
  paper: { t: 'Paper trading', tone: 'watch' },
  eligible: { t: 'Eligible', tone: 'ok' },
  failed: { t: 'Failed the lab', tone: '' },
  retired: { t: 'Retired', tone: '' },
  rejected: { t: 'Sent back', tone: '' },
};

export const VERDICT = {
  pass: { t: 'Passed', tone: 'ok' },
  fail: { t: 'Failed', tone: '' },
  inconclusive: { t: 'Inconclusive', tone: 'lilac' },
  helps: { t: 'Helps', tone: 'ok' },
  hurts: { t: 'Hurts', tone: 'watch' },
  no_clear_edge: { t: 'No clear edge', tone: '' },
};

export const RULE_WORD = {
  rebalance_band: 'Rebalance band',
  deposit_steering: 'Steer deposits',
  harvest: 'Harvest losses',
  margin: 'Margin in a dip',
};

const PARAM_WORD = {
  band_pts: (v) => `${v} pt band`,
  threshold_usd: (v) => `$${Number(v).toLocaleString('en-US')} threshold`,
  dip_pct: (v) => `${v}% dip`,
  borrow_pct: (v) => `borrow ${v}%`,
  rate_pct: (v) => `${v}% rate`,
  top_n: (v) => `top ${v}`,
  lookback: (v) => `${v}-day lookback`,
};

export const BARS = [
  { key: 'excess_interval', t: 'Beats the plan', line: 'Excess return interval above zero' },
  { key: 'deflated_sharpe', t: 'Deflated Sharpe', line: 'Still good after counting every variant tried' },
  { key: 'pbo', t: 'Overfit odds', line: 'Best in-sample pick holds out of sample' },
  { key: 'holdout', t: 'Holdout', line: 'Holds on the years it never saw' },
  { key: 'factor', t: 'Factor check', line: 'Alpha left after the six French factors' },
  { key: 'criteria_excess', t: 'Its own target', line: 'Pre-registered excess target' },
  { key: 'criteria_drawdown', t: 'Drawdown cap', line: 'Pre-registered worst drop' },
];

export const PAPER_DAYS = 182;

const MINUS = '−';
export function signedPts(v, d = 1) {
  if (v == null || Number.isNaN(v)) return '—';
  const s = Math.abs(v).toFixed(d);
  const zero = !/[1-9]/.test(s);
  return `${zero ? '' : v < 0 ? MINUS : '+'}${s} pts`;
}
export const signedPct = (v, d = 1) => (v == null ? '—' : pct(v / 100, d, true));

// ---------- helpers ----------
export const dayOf = (stamp) => (stamp ? dayLabel(String(stamp).slice(0, 10), true) : '—');

export function statusOf(s) {
  return STATUS[s] || { t: s ? s.replace(/_/g, ' ') : 'Unknown', tone: '' };
}

export function verdictOf(v) {
  return VERDICT[v] || { t: v ? v.replace(/_/g, ' ') : 'No verdict yet', tone: '' };
}

export function paramText(params) {
  const e = Object.entries(params || {});
  if (!e.length) return 'Default settings';
  return e.map(([k, v]) => (PARAM_WORD[k] ? PARAM_WORD[k](v) : `${k.replace(/_/g, ' ')} ${v}`)).join(', ');
}

export function stageCounts(strategies = []) {
  const out = Object.fromEntries(STAGES.map((s) => [s.v, 0]));
  let off = 0;
  strategies.forEach((s) => {
    if (s.status in out) out[s.status] += 1;
    else off += 1;
  });
  return { ...out, off };
}

export function paperSummary(paper) {
  if (!paper?.summary) return null;
  if (typeof paper.summary === 'object') return paper.summary;
  try {
    return JSON.parse(paper.summary);
  } catch {
    return null;
  }
}

export function paperProgress(paper) {
  if (!paper) return null;
  const days = Math.max(0, paper.days || 0);
  return { days, share: Math.min(1, days / PAPER_DAYS), left: Math.max(0, PAPER_DAYS - days), done: days >= PAPER_DAYS };
}

export function verdictLamps(bars) {
  if (!bars) return [];
  return BARS.filter((b) => b.key in bars).map((b) => {
    const v = bars[b.key];
    return { id: b.key, label: b.t, status: v === true ? 'ok' : v === false ? 'act' : 'watch', detail: v == null ? `${b.line}. Did not run.` : b.line, short: v === true ? 'Clear' : v === false ? 'Missed' : 'Not run' };
  });
}

export function foldItems(folds = []) {
  return folds.map((f) => ({
    label: (f.test?.start || f.test_window?.[0] || '').slice(0, 4),
    value: f.test?.excess_vs_bench_pts ?? null,
    hint: f.params ? paramText(f.params) : undefined,
  }));
}

export function horizonRows(horizons = []) {
  return [...horizons]
    .sort((a, b) => a.years - b.years)
    .map((h) => ({ years: h.years, starts: h.starts, mean: h.mean_pts, lo: h.p5_pts, mid: h.p50_pts ?? null, hi: h.p95_pts, share: h.share_positive ?? h.share_better ?? null, basis: h.basis }));
}

export function sensitivityItems(ps = {}) {
  return Object.entries(ps).map(([param, byValue]) => ({
    param,
    items: Object.entries(byValue)
      .sort((a, b) => Number(a[0]) - Number(b[0]))
      .map(([v, s]) => ({ label: PARAM_WORD[param] ? PARAM_WORD[param](v) : `${param} ${v}`, value: s })),
  }));
}

const REGIME = { bull: 'Rising markets', bear: 'Falling markets', high_rates: 'High rates', low_rates: 'Low rates' };

export function regimeItems(rs = {}) {
  return Object.entries(rs)
    .filter(([, r]) => r && r.excess_pts != null)
    .map(([k, r]) => ({ label: REGIME[k] || k.replace(/_/g, ' '), value: r.excess_pts, hint: `${r.days} days` }));
}

export function costItems(tc = []) {
  return tc.map((c) => ({ label: c.cost_x === 1 ? 'Lab costs' : `${c.cost_x}x costs`, value: c.excess_vs_bench_pts }));
}

export function ruleVariants(rule) {
  if (!rule) return [];
  return (rule.variants || []).map((v) => ({
    params: v.params,
    label: paramText(v.params),
    full: v.full_diff_pts,
    holdout: v.holdout_diff_pts,
    verdict: v.verdict,
    end: v.full?.after_liquidation ?? v.full?.end_value ?? null,
    taxes: v.full?.taxes ?? null,
    interest: v.full?.interest ?? null,
    calls: v.full?.margin_calls ?? 0,
    horizons: horizonRows(v.horizons),
    best: rule.best && JSON.stringify(rule.best) === JSON.stringify(v.params),
  }));
}

export function mixText(mix) {
  return Object.entries(mix || {})
    .sort((a, b) => b[1] - a[1])
    .map(([s, w]) => `${s} ${Math.round(w * 100)}%`)
    .join(' · ');
}

export function splitStrategies(data) {
  const list = data?.strategies || [];
  const order = ['paper', 'eligible', 'lab', 'research', 'draft', 'failed', 'retired', 'rejected'];
  return [...list].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status) || (b.registered_at || '').localeCompare(a.registered_at || ''));
}

export const FACTOR_LABEL = { alpha: 'Alpha left', factor_in_disguise: 'A factor in disguise', no_alpha: 'No alpha' };
export const FACTOR_WORD = { mkt_rf: 'Market', smb: 'Size', hml: 'Value', rmw: 'Profitability', cma: 'Investment', mom: 'Momentum' };

export function factorItems(loadings = {}) {
  return Object.entries(loadings || {}).map(([k, l]) => ({ label: FACTOR_WORD[k] || k, value: l?.beta ?? null, hint: l?.t != null ? `t ${l.t}` : undefined }));
}

const METRIC_WORD = { ret: 'return', ret_skip: 'return skipping the last month', vol: 'volatility', ma_gap: 'gap to its average', range_52w: 'place in its range', dd: 'drop from the high' };
const TRANSFORM_WORD = { raw: '', rank: 'ranked high to low', inverse_rank: 'ranked low to high', zscore: 'as a z-score', inverse: 'flipped' };
const SET_WORD = { sector_etfs: 'US sector ETFs', core_etfs: 'core ETFs', benchmarks: 'benchmarks' };

function universeText(u) {
  if (!u) return null;
  if (typeof u === 'string') return u;
  if (u.set) return SET_WORD[u.set] || u.set.replace(/_/g, ' ');
  if (u.symbols?.length) return u.symbols.join(', ');
  return u.rule || u.type || null;
}

function fill(text, params = {}) {
  return String(text).replace(/\{(\w+)\}/g, (m, k) => {
    const p = params[k];
    const v = p == null ? null : Array.isArray(p) ? p[0] : typeof p === 'object' ? (p.default ?? p.min) : p;
    return v == null ? k : String(v);
  });
}

const UNIT = { d: 'days', m: 'months', y: 'years' };
const windowText = (w) => String(w).replace(/^(\d+)\s*([dmy])$/i, (m, n, u) => `${n} ${UNIT[u.toLowerCase()]}`);

function signalText(g, params) {
  if (typeof g === 'string') return fill(g, params);
  const w = g.window ? windowText(fill(g.window, params)) : '';
  return [METRIC_WORD[g.metric_id] || g.metric_id, w ? `over ${w}` : '', TRANSFORM_WORD[g.transform] ?? g.transform].filter(Boolean).join(' ');
}

const asText = (v, params) => (v == null ? null : typeof v === 'string' ? fill(v, params) : fill(JSON.stringify(v).replace(/[{}"]/g, '').replace(/:/g, ' ').replace(/,/g, ', '), params));

const paramVal = (v, params) => (typeof v === 'string' && v.startsWith('param:') ? fill(`{${v.slice(6)}}`, params) : v);

function entryText(e, params) {
  if (e && typeof e === 'object' && e.top_n != null) return `top ${paramVal(e.top_n, params)} by rank${e.min_signal != null ? `, signal at least ${e.min_signal}` : ''}`;
  return asText(e, params);
}

function exitText(e, params) {
  if (e === 'rebalance') return 'at the next rebalance';
  if (e && typeof e === 'object' && e.hold_rank != null) return `keeps a holding while it ranks in the top ${paramVal(e.hold_rank, params)}`;
  return asText(e, params);
}

export function specLines(spec) {
  if (!spec) return [];
  return [
    { k: 'Picks from', v: universeText(spec.universe) },
    { k: 'Signal', v: (spec.signals || []).map((g) => signalText(g, spec.params)).join('; ') || null },
    { k: 'Buys', v: entryText(spec.entry, spec.params) },
    { k: 'Sells', v: exitText(spec.exit, spec.params) },
    { k: 'Trades', v: spec.rebalance ? `${spec.rebalance}, ${(asText(spec.sizing) || 'equal').replace(/_/g, ' ')} weights` : null },
    { k: 'Horizons', v: spec.horizons?.length ? spec.horizons.map((h) => `${h} years`).join(', ') : null },
  ].filter((l) => l.v);
}

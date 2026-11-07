import { kindName, originName } from './decisions.js';

// ---------- words ----------
export const CHIP = {
  keep: { t: 'Keep it on', tone: 'ok', line: 'Ahead of the plan over its scored record' },
  behind: { t: 'Behind the plan', tone: 'watch', line: 'Following the plan would have done better' },
  too_early: { t: 'Too early', tone: '', line: 'Needs six months and ten scored calls' },
};

export const GROUP_BY = [
  { v: 'origin', t: 'By desk' },
  { v: 'kind', t: 'By kind' },
  { v: 'path', t: 'By Preflight path' },
  { v: 'taken', t: 'Taken or not' },
];

const GROUP_WORD = { clean: 'Clean', flagged: 'Flagged', override: 'Override', taken: 'Taken', not_taken: 'Not taken' };

export function groupLabel(by, group) {
  if (by === 'origin') return originName(group);
  if (by === 'kind') return kindName(group);
  return GROUP_WORD[group] || String(group).replace(/_/g, ' ');
}

export function chipOf(chip) {
  return CHIP[chip] || { t: chip ? chip.replace(/_/g, ' ') : '—', tone: '', line: '' };
}

// ---------- helpers ----------
export function totalRecord(desks = []) {
  if (!desks.length) return null;
  return desks.reduce((a, d) => a + (d.record_usd || 0), 0);
}

export function scoredCount(desks = []) {
  return desks.reduce((a, d) => a + (d.scored_90 || 0), 0);
}

export function groupItems(groups = [], by, window) {
  return groups
    .filter((g) => g.by === by && g.window === window)
    .map((g) => ({ label: groupLabel(by, g.group), value: g.total_usd, hint: `${g.n} scored · mean ${g.mean_usd == null ? '—' : Math.round(g.mean_usd)}`, g }));
}

export function intervalGeo(lo, hi, mean) {
  const vals = [lo, hi, mean, 0].filter((v) => v != null);
  if (vals.length < 3) return null;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const at = (v) => ((v - min) / span) * 100;
  return { zero: at(0), lo: at(lo), hi: at(hi), mean: mean == null ? null : at(mean), straddles: lo <= 0 && hi >= 0 };
}

export function calibrationPoints(cal) {
  return (cal?.bins || []).filter((b) => b.n > 0).map((b) => ({ said: b.said, happened: b.happened, n: b.n, low: b.low, high: b.high }));
}

export function decisionRows(decisions = [], { origin, limit = 40 } = {}) {
  return decisions
    .filter((d) => !origin || d.origin === origin)
    .filter((d) => d.start)
    .sort((a, b) => b.start.localeCompare(a.start))
    .slice(0, limit)
    .map((d) => ({
      id: d.id,
      start: d.start,
      origin: d.origin,
      kind: d.kind,
      symbol: d.symbol,
      taken: d.taken,
      amount: d.amount_usd ?? null,
      s30: d.scores?.['30D']?.usd ?? null,
      s90: d.scores?.['90D']?.usd ?? null,
      s365: d.scores?.['365D']?.usd ?? null,
    }));
}

// ---------- patterns ----------
export function patternValue(p) {
  if (p?.value == null) return '—';
  if (p.id === 'pat.range_52w') return `${Math.round(p.value)}% up the range`;
  if (/percentile/i.test(p.label || '')) return `${Math.round(p.value)}${ordinal(Math.round(p.value))} pctl`;
  if (p.unit === 'pts') return `${p.value > 0 ? '+' : p.value < 0 ? '−' : ''}${Math.abs(p.value).toFixed(2)} pts`;
  if (p.unit === 'pct') return `${p.value > 0 ? '+' : p.value < 0 ? '−' : ''}${Math.abs(p.value).toFixed(1)}%`;
  return String(p.value);
}

function ordinal(n) {
  const t = n % 100;
  if (t >= 11 && t <= 13) return 'th';
  return { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th';
}

export function baseRateText(p) {
  if (!p?.followed_by) return null;
  if (!p.n) return `Not enough history yet to say how often it was ${p.followed_by}.`;
  if (p.base_rate == null) return `${p.n} past ${p.n === 1 ? 'case' : 'cases'}${p.forward_mean_pct != null ? `, averaging ${p.forward_mean_pct > 0 ? '+' : '−'}${Math.abs(p.forward_mean_pct).toFixed(1)}%` : ''}. Too few for a rate.`;
  return `${Math.round(p.base_rate * 100)}% of ${p.n} past cases were ${p.followed_by}${p.ci_low != null && p.ci_high != null ? ` (${Math.round(p.ci_low * 100)} to ${Math.round(p.ci_high * 100)}%)` : ''}.`;
}

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function seasonGrid(seasonality = {}) {
  const rows = Object.keys(seasonality).filter((s) => seasonality[s]?.length);
  const cols = MON.map((m, k) => k + 1);
  const values = rows.map((s) => cols.map((m) => {
    const cell = seasonality[s].find((x) => x.month === m);
    return cell ? cell.mean_pct / 100 : null;
  }));
  return { rows, cols: MON, values };
}

const SETUP = { after_drop: 'After a 5% drop', after_rise: 'After a 5% rise', flat: 'After a flat month' };
const FUNDING = { on_schedule: 'On the deposit schedule', off_schedule: 'Off schedule', margin: 'On margin', sale_proceeds: 'From a sale' };

export function setupItems(b = {}) {
  return Object.entries(b).map(([k, v]) => ({ label: SETUP[k] || k.replace(/_/g, ' '), value: v.mean_usd, hint: `${v.n} buys · total ${Math.round(v.total_usd)}` }));
}

export function fundingItems(f = {}) {
  return Object.entries(f).map(([k, v]) => ({ label: FUNDING[k] || k.replace(/_/g, ' '), value: v.mean_usd, hint: `${v.n} buys` }));
}

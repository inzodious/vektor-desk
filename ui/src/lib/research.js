import { parseDay } from './charts.js';
import { pct, usd } from './format.js';

export const RESEARCH_TABS = [
  { to: '/research', label: 'Holdings', end: true },
  { to: '/research/opportunities', label: 'Opportunities' },
  { to: '/research/sources', label: 'Sources' },
  { to: '/research/watchlist', label: 'Watchlist' },
  { to: '/research/calendar', label: 'Calendar' },
  { to: '/research/compare', label: 'Compare' },
  { to: '/research/boards', label: 'Boards' },
];

export const VERDICT = {
  add: { t: 'Add on plan', tone: 'ok' },
  hold: { t: 'Hold in band', tone: 'ok' },
  trim: { t: 'Trim to target', tone: 'watch' },
  watch: { t: 'Watching', tone: 'info' },
  avoid: { t: 'Stay out', tone: 'lilac' },
};

export const STALE_DAYS = 14;

const PRIMARY = /(^|\.)(sec\.gov|stlouisfed\.org|fidelity\.com|vanguard\.com|treasury\.gov|bls\.gov|finnhub\.io)$/i;

export function sourceKind(s) {
  const url = s?.url || '';
  if (/^note:/i.test(url) || /^your note/i.test(s?.title || '')) return 'note';
  if (/^(engine|edgar|fred):/i.test(url)) return 'primary';
  try {
    return PRIMARY.test(new URL(url).hostname) ? 'primary' : 'web';
  } catch {
    return 'primary';
  }
}

export const SOURCE_WORD = { primary: { t: 'Primary', tone: 'ok' }, web: { t: 'Web', tone: '' }, note: { t: 'Note', tone: 'lilac' } };

export function isLink(s) {
  return /^https?:\/\//i.test(s?.url || '');
}

const HOLD_STATUS = {
  running: { t: 'Running now', tone: 'info' },
  waiting: { t: 'In tonight’s pass', tone: 'info' },
  failed: { t: 'Last try failed', tone: 'watch' },
  none: { t: 'Not analysed yet', tone: '' },
};

export function holdingChip(h) {
  if (h?.verdict && VERDICT[h.verdict]) return VERDICT[h.verdict];
  return HOLD_STATUS[h?.status] || { t: 'Analysed', tone: '' };
}

export function verdictOf(d) {
  const v = d?.dossier?.verdict;
  return v && VERDICT[v] ? { key: v, ...VERDICT[v] } : null;
}

export function ageDays(iso, now = new Date()) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((now.getTime() - t) / 86400000));
}

export function freshness(iso, now = new Date()) {
  const days = ageDays(iso, now);
  if (days == null) return { t: 'Never refreshed', tone: 'watch' };
  if (days > STALE_DAYS) return { t: `Due for a refresh · ${days} days old`, tone: 'watch' };
  return { t: days === 0 ? 'Refreshed today' : `Refreshed ${days === 1 ? 'yesterday' : `${days} days ago`}`, tone: '' };
}

export function triggersOf(text) {
  if (!text) return [];
  return String(text)
    .split(/\n+|;\s+|(?<=\.)\s+(?=[A-Z])/)
    .map((t) => t.replace(/^\s*[-*•\d.)]+\s*/, '').trim())
    .filter(Boolean)
    .slice(0, 6);
}

export function rangeGeo(range) {
  if (!range || range.low == null || range.high == null || !(range.high > range.low)) return null;
  const now = range.now ?? null;
  const lo = Math.min(range.low, now ?? range.low);
  const hi = Math.max(range.high, now ?? range.high);
  const pad = (hi - lo) * 0.14 || 1;
  const a = lo - pad;
  const b = hi + pad;
  const at = (v) => ((v - a) / (b - a)) * 100;
  const mid = (range.low + range.high) / 2;
  let where = null;
  if (now != null) {
    if (now < range.low) where = 'below';
    else if (now > range.high) where = 'above';
    else where = now >= mid ? 'upper' : 'lower';
  }
  return { left: at(range.low), width: at(range.high) - at(range.low), now: now == null ? null : at(now), mid: at(mid), where };
}

const MULTIPLE = /p\/e|\bpe\b|multiple|ev\/|p\/s|p\/b|price[- ]to[- ]|times (earnings|sales|book)/i;

function basisLead(basis) {
  return String(basis || '').split(/[.(;:]/)[0];
}

export function isMultipleBasis(basis) {
  const lead = basisLead(basis);
  if (/per share/i.test(lead)) return false;
  if (MULTIPLE.test(lead)) return true;
  return !/\bprice\b|\$/i.test(lead) && MULTIPLE.test(String(basis || ''));
}

export function basisKind(basis, unit) {
  if (unit !== undefined) return ['price', 'multiple', 'percent'].includes(unit) ? unit : 'plain';
  if (isMultipleBasis(basis)) return 'multiple';
  if (/\bprice\b|\$|per share/i.test(basis || '')) return 'price';
  return /yield|%|percent/i.test(basis || '') ? 'percent' : 'plain';
}

export function isPriceBasis(basis, unit) {
  return basisKind(basis, unit) === 'price';
}

export function basisParts(basis) {
  const text = String(basis || '').trim();
  if (!text) return { label: null, note: null };
  if (text.length <= 48) return { label: text.replace(/\.$/, ''), note: null };
  const lead = basisLead(text).trim();
  return lead && lead.length <= 48 ? { label: lead, note: text } : { label: null, note: text };
}

export function fmtBasis(v, basis, unit) {
  if (v == null) return '—';
  const kind = basisKind(basis, unit);
  if (kind === 'price') return `$${v.toFixed(v >= 100 ? 0 : 2)}`;
  if (kind === 'multiple') return `${Number(v.toFixed(1))}x`;
  if (kind === 'percent') return `${Number(v.toFixed(2))}%`;
  return String(Number(v.toFixed(2)));
}

export function rangeLine(range, nowValue) {
  const now = range?.now ?? nowValue ?? null;
  const g = rangeGeo({ ...range, now });
  if (!g) return 'No range written yet.';
  if (now == null) return `Fair range ${fmtBasis(range.low, range.basis, range.unit)} to ${fmtBasis(range.high, range.basis, range.unit)}. Today's value isn't tracked for this basis.`;
  const word = { below: 'below the range', above: 'above the range', upper: 'inside the range, upper half', lower: 'inside the range, lower half' }[g.where];
  return `Now ${fmtBasis(now, range.basis, range.unit)}: ${word}.`;
}

export function rebase(a, b) {
  const bm = new Map((b?.rows || []).filter((r) => r.close != null).map((r) => [r.date, r.close]));
  const rows = (a?.rows || []).filter((r) => r.close != null && (!b || bm.has(r.date)));
  if (!rows.length) return { x: [], a: [], b: [] };
  const a0 = rows[0].close;
  const b0 = b ? bm.get(rows[0].date) : null;
  return {
    x: rows.map((r) => r.date),
    a: rows.map((r) => (r.close / a0) * 100),
    b: b ? rows.map((r) => (bm.get(r.date) / b0) * 100) : [],
  };
}

export function coreFund(rows) {
  const targets = rows.filter((m) => m.metric_id === 'plan.target' && m.scope === 'holding' && m.value != null);
  return targets.sort((a, b) => b.value - a.value)[0]?.scope_id || null;
}

const sp = (v) => pct(v / 100, 1, true);

export const KEY_NUMBERS = [
  { id: 'value.weight', t: 'Your weight', f: (v) => pct(v / 100) },
  { id: 'plan.target', t: 'Plan target', f: (v) => pct(v / 100, 0) },
  { id: 'plan.drift', t: 'Drift', f: (v) => `${v < 0 ? '−' : v > 0 ? '+' : ''}${Math.abs(v).toFixed(1)} pts` },
  { id: 'value.market', t: 'Position', f: (v) => usd(v) },
  { id: 'risk.beta', window: '252D', t: 'Beta, 1 year', f: (v) => v.toFixed(2) },
  { id: 'sig.earnings_days', t: 'Next earnings', f: (v) => (v === 0 ? 'Today' : `In ${v} ${v === 1 ? 'day' : 'days'}`) },
  { id: 'sig.eps_surprise', t: 'Last EPS vs estimate', f: sp },
  { id: 'sig.revenue_surprise', t: 'Last revenue vs estimate', f: sp },
  { id: 'fund.revenue_growth', t: 'Revenue growth, last year', f: sp },
  { id: 'fund.operating_margin', t: 'Operating margin', f: (v) => pct(v / 100) },
  { id: 'fund.net_margin', t: 'Net margin', f: (v) => pct(v / 100) },
  { id: 'sig.dilution', t: 'Share count, 1 year', f: sp },
  { id: 'sig.insider_net', t: 'Insiders, 90 days', f: (v) => (v === 0 ? 'No open-market trades' : `${usd(v, { sign: true })} net`) },
  { id: 'tax.wash_window', t: 'Wash window', f: (v) => (v > 0 ? `Clears in ${v} days` : 'Clear') },
];

export function keyNumbers(rows, symbol) {
  return KEY_NUMBERS.map((k) => {
    const m = rows.find((r) => r.metric_id === k.id && r.scope_id === symbol && (!k.window || r.window === k.window));
    if (!m || m.value == null || m.quality === 'insufficient_history') return null;
    return { id: k.id, t: k.t, v: k.f(m.value), quality: m.quality };
  }).filter(Boolean);
}

const FORM_WORD = { '10-K': 'Annual report', '10-Q': 'Quarterly report', '8-K': 'Current report', 4: 'Insider filing', 'NPORT-P': 'Fund holdings', '497K': 'Summary prospectus', 'S-1': 'Offering', 'S-1/A': 'Offering amendment', 'DEF 14A': 'Proxy' };

export function formWord(form) {
  return FORM_WORD[form] || form;
}

const eps = (v) => `${v < 0 ? '−' : ''}$${Math.abs(v).toFixed(2)}`;

const CODE_WORD = { P: 'bought', S: 'sold', M: 'exercised options for', A: 'was granted', G: 'gifted', F: 'had shares withheld for tax on' };

export function eventsOf(research, today) {
  if (!research) return [];
  const out = [];
  (research.filings || []).forEach((f) =>
    out.push({ date: f.filed, kind: 'filing', title: `${f.form} · ${formWord(f.form)}`, detail: f.description || '', url: f.url, key: `f-${f.form}-${f.filed}-${f.description}` }),
  );
  (research.earnings || []).forEach((e) => {
    const future = e.date > today;
    const hour = e.hour === 'bmo' ? 'before the open' : e.hour === 'amc' ? 'after the close' : '';
    const detail = future
      ? `Q${e.quarter} ${e.year}${hour ? `, ${hour}` : ''}${e.eps_estimate != null ? ` · EPS estimate ${eps(e.eps_estimate)}` : ''}`
      : e.eps_actual != null && e.eps_estimate != null
        ? `EPS ${eps(e.eps_actual)} against ${eps(e.eps_estimate)} expected`
        : `Q${e.quarter} ${e.year}`;
    out.push({ date: e.date, kind: future ? 'earnings_next' : 'earnings', title: future ? 'Earnings report' : 'Earnings reported', detail, key: `e-${e.date}` });
  });
  (research.insiders || [])
    .filter((t) => t.code === 'P' || t.code === 'S')
    .forEach((t) =>
      out.push({
        date: t.txn_date,
        kind: 'insider',
        title: `${t.name} ${CODE_WORD[t.code] || t.code} ${Math.abs(t.change || 0).toLocaleString('en-US')} shares`,
        detail: t.price ? `At $${t.price.toFixed(2)}, about ${usd(Math.abs((t.change || 0) * t.price))}` : '',
        key: `i-${t.name}-${t.txn_date}-${t.change}`,
      }),
    );
  return out.sort((a, b) => b.date.localeCompare(a.date));
}

export function upcomingOf(events, today, days = 60) {
  const end = parseDay(today).getTime() + days * 86400000;
  return events.filter((e) => e.date >= today && parseDay(e.date).getTime() <= end).sort((a, b) => a.date.localeCompare(b.date));
}

export function allSources(dossiers) {
  return dossiers
    .flatMap((d) => (d.dossier?.sources || []).map((s) => ({ ...s, symbol: d.symbol, kind: sourceKind(s) })))
    .sort((a, b) => (b.date || '').localeCompare(a.date || '') || a.symbol.localeCompare(b.symbol));
}

export const MACRO = [
  { id: 'macro.rf_3m', t: '3-month T-bill', f: (v) => `${v.toFixed(2)}%` },
  { id: 'macro.y10', t: '10-year Treasury', f: (v) => `${v.toFixed(2)}%` },
  { id: 'macro.curve_10y2y', t: '10Y minus 2Y', f: (v) => `${v < 0 ? '−' : '+'}${Math.abs(v).toFixed(2)} pts`, hint: (v) => (v < 0 ? 'Inverted' : 'Normal') },
  { id: 'macro.hy_spread', t: 'High-yield spread', f: (v) => `${v.toFixed(2)} pts` },
  { id: 'macro.vix', t: 'VIX', f: (v) => v.toFixed(1), hint: (v) => (v >= 30 ? 'Stormy' : v >= 20 ? 'Choppy' : 'Calm') },
  { id: 'macro.cpi_yoy', t: 'Inflation, 1 year', f: (v) => `${v.toFixed(1)}%` },
];

export const RATE_SERIES = [
  { id: 'DGS3MO', name: '3-month', color: 'var(--s5)' },
  { id: 'DGS2', name: '2-year', color: 'var(--s2)' },
  { id: 'DGS10', name: '10-year', color: 'var(--s1)' },
];

export function rateLines(series) {
  const maps = RATE_SERIES.map((s) => new Map((series?.[s.id] || []).map((r) => [r.date, r.value])));
  const days = [...new Set(RATE_SERIES.flatMap((s) => (series?.[s.id] || []).map((r) => r.date)))].sort().filter((d) => maps.every((m) => m.has(d)));
  return { x: days, series: RATE_SERIES.map((s, k) => ({ name: s.name, color: s.color, values: days.map((d) => maps[k].get(d)) })) };
}

export function overnightStart(profile) {
  const w = profile?.profile?.usage?.overnight_window || '01:00-05:00';
  const m = /^(\d{1,2}):(\d{2})/.exec(w);
  if (!m) return '1:00 AM';
  const h = Number(m[1]);
  return `${h % 12 || 12}:${m[2]} ${h < 12 ? 'AM' : 'PM'}`;
}

export const ASK_DESKS = [
  { v: 'plan_keeper', t: 'Plan keeper' },
  { v: 'tax', t: 'Tax desk' },
  { v: 'risk', t: 'Risk desk' },
  { v: 'research', t: 'Research desk' },
  { v: 'strategy', t: 'Strategy desk' },
  { v: 'plans', t: 'Plan desk' },
];
export const SYMBOL_DESKS = ['plans'];

export const ASK_STATUS = {
  queued: { icon: 'clock', t: 'Queued' },
  running: { icon: 'layers', t: 'Working on it' },
  done: { icon: 'check', t: 'Answered' },
  failed: { icon: 'x', t: "Didn't finish" },
};

export const SUGGESTED = [
  { desk: 'risk', q: 'What would a 20% drop cost me?' },
  { desk: 'plan_keeper', q: 'Where does the next deposit go?' },
  { desk: 'tax', q: 'Is anything worth harvesting before December?' },
];

export function deskTitle(desk) {
  return ASK_DESKS.find((d) => d.v === desk)?.t || desk;
}

export function cleanSymbol(s) {
  const v = String(s || '')
    .trim()
    .toUpperCase();
  return /^[A-Z][A-Z0-9.-]{0,9}$/.test(v) ? v : null;
}

// ---------- filing chip ----------
const DIRECTION = {
  '-2': { t: 'Reads clearly bad', tone: 'watch' },
  '-1': { t: 'Leans bad', tone: 'watch' },
  0: { t: 'Reads neutral', tone: '' },
  1: { t: 'Leans good', tone: 'ok' },
  2: { t: 'Reads clearly good', tone: 'ok' },
};

export function directionWord(d) {
  return DIRECTION[Math.max(-2, Math.min(2, Math.round(Number(d) || 0)))];
}

export function eventWord(e) {
  if (!e) return null;
  const s = String(e).replace(/_/g, ' ').replace('merger acquisition', 'merger or acquisition');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function filingChip(research) {
  const rows = Array.isArray(research?.filing_signals) ? research.filing_signals : [];
  const r = rows[0];
  if (!r) return null;
  const dir = directionWord(r.direction);
  return {
    ...r,
    dir,
    sure: r.confidence == null ? null : `${Math.round(r.confidence * 100)}% sure`,
    event: eventWord(r.event_type),
    form: formWord(r.form),
    more: rows.length - 1,
  };
}

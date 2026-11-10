import { dayLabel } from './charts.js';
import { originName, kindName } from './decisions.js';
import { usd } from './format.js';
import { signedPct } from './strategy.js';

export const KINDS = ['day', 'week', 'month', 'year'];
export const RESULT_TABS = [
  { to: '/results/day', label: 'Day' },
  { to: '/results/week', label: 'Week' },
  { to: '/results/month', label: 'Month' },
  { to: '/results/year', label: 'Year' },
];
export const KIND_WORD = { day: 'day', week: 'week', month: 'month', year: 'year' };
const FLOW = { deposit: 'Deposit', withdrawal: 'Withdrawal', transfer_in: 'Transfer in', transfer_out: 'Transfer out', dividend: 'Dividend', interest: 'Interest', fee: 'Fee' };
const EVENT = { discount: 'Discount day', discount_day: 'Discount day', filing: 'Filing', earnings: 'Earnings', dividend: 'Dividend' };
const DECISION_STATUS = { placed: 'Placed', approved: 'Approved', dismissed: 'Dismissed', pending: 'Waiting', snoozed: 'Snoozed', expired: 'Expired' };
const FIT = { fits: 'Fits your band', below: 'Calmer than your band', above: 'Riskier than your band' };

export const cleanKind = (kind) => (KINDS.includes(kind) ? kind : 'day');

// ---------- stepper ----------
export function stepper(index, kind, end) {
  const rows = index?.kinds?.[kind] || [];
  if (!rows.length) return { rows, at: -1, current: null, older: null, newer: null, latest: true };
  const found = end ? rows.findIndex((r) => r.end === end) : 0;
  const at = found < 0 ? 0 : found;
  return { rows, at, current: rows[at], older: rows[at + 1] || null, newer: at > 0 ? rows[at - 1] : null, latest: at === 0 };
}

export function periodPath(kind, row, latest) {
  return `/results/${kind}${row && row.end !== latest?.end ? `?end=${row.end}` : ''}`;
}

export function stateChip(r) {
  if (!r) return null;
  if (!r.closed) return { t: 'So far', tone: 'info', title: 'This period is still open' };
  if (!r.final) return { t: 'May restate once', tone: '', title: 'Late fund prices can still nudge it' };
  return { t: 'Final', tone: 'ok', title: 'Closed and frozen' };
}

// ---------- hero ----------
export function changeText(value) {
  if (!value) return { usd: '—', pct: '', tone: '' };
  const tone = value.change_usd > 0 ? 'up' : value.change_usd < 0 ? 'dn' : '';
  return { usd: usd(value.change_usd, { sign: true }), pct: signedPct(value.change_pct, 2), tone };
}

export function gainLine(value) {
  if (!value) return null;
  const flows = value.net_flows || 0;
  if (!flows) return `All of it from the market: ${usd(value.gain_usd, { sign: true })}`;
  return `${usd(value.gain_usd, { sign: true })} from the market, ${usd(flows, { sign: true })} ${flows > 0 ? 'you put in' : 'you took out'}`;
}

export function kpis(pack) {
  if (!pack) return [];
  const v = pack.value || {};
  const inc = pack.income || {};
  const earned = (inc.dividends || 0) + (inc.interest || 0);
  const out = [
    { id: 'start', label: 'Started', value: usd(v.start), sub: pack.coverage?.base ? `close of ${dayLabel(pack.coverage.base)}` : null },
    { id: 'end', label: 'Ended', value: usd(v.end), sub: pack.as_of ? `as of ${dayLabel(pack.as_of)}` : null },
    { id: 'flows', label: 'Money in', value: usd(v.net_flows, { sign: true }), sub: (pack.flows || []).length ? `${pack.flows.length} ${pack.flows.length === 1 ? 'move' : 'moves'}` : 'No deposits' },
    { id: 'gain', label: 'Market gain', value: usd(v.gain_usd, { sign: true }), tone: v.gain_usd > 0 ? 'up' : v.gain_usd < 0 ? 'dn' : '', sub: `${signedPct(v.change_pct, 2)} time-weighted` },
    { id: 'income', label: 'Income', value: usd(earned, { cents: earned > 0 && earned < 100 }), sub: inc.margin_interest ? `${usd(Math.abs(inc.margin_interest), { cents: true })} margin interest` : 'Dividends and interest' },
  ];
  const r = pack.realized;
  if (r?.sales) out.push({ id: 'realized', label: 'Realized', value: usd(r.total, { sign: true }), tone: r.total > 0 ? 'up' : r.total < 0 ? 'dn' : '', sub: `${usd(r.short_term, { sign: true })} short, ${usd(r.long_term, { sign: true })} long` });
  if (pack.fi) out.push({ id: 'fi', label: 'FI progress', value: `${pack.fi.progress_end_pct.toFixed(1)}%`, sub: `${pack.fi.change_pts > 0 ? '+' : pack.fi.change_pts < 0 ? '−' : ''}${Math.abs(pack.fi.change_pts).toFixed(2)} pts` });
  return out;
}

// ---------- versus ----------
export function versusRows(pack) {
  if (!pack?.value) return [];
  const you = { id: 'you', name: 'You', kind: 'you', return_pct: pack.value.change_pct, excess_pts: null, diff_usd: null };
  return [you, ...(pack.vs || [])];
}

export function versusScale(rows) {
  const vals = rows.map((r) => r.return_pct || 0);
  const hi = Math.max(0, ...vals);
  const lo = Math.min(0, ...vals);
  const span = Math.max(0.01, hi - lo);
  return { zero: (-lo / span) * 100, width: (v) => (Math.abs(v || 0) / span) * 100 };
}

export function diffText(row) {
  if (row.kind === 'you' || row.diff_usd == null) return '';
  if (Math.abs(row.diff_usd) < 0.5) return 'Level with you';
  return row.diff_usd > 0 ? `You’re ${usd(row.diff_usd)} ahead` : `You’re ${usd(Math.abs(row.diff_usd))} behind`;
}

export function versusLine(pack) {
  const spy = (pack?.vs || []).find((r) => r.kind === 'benchmark');
  if (!spy) return null;
  const pts = spy.excess_pts;
  if (pts == null) return null;
  if (Math.abs(pts) < 0.005) return `Level with the ${spy.name}`;
  return `${Math.abs(pts).toFixed(2)} pts ${pts > 0 ? 'ahead of' : 'behind'} the ${spy.name}`;
}

// ---------- movers ----------
export function moverRows(movers) {
  if (!movers) return [];
  const rows = [...(movers.up || []), ...(movers.down || [])].map((m) => ({ ...m, tone: m.contribution_usd >= 0 ? 'up' : 'dn' }));
  if (Math.abs(movers.other_usd || 0) >= 0.5) rows.push({ symbol: null, name: 'Dividends, cash and same-day trades', contribution_usd: movers.other_usd, return_pct: null, weight_pct: null, tone: movers.other_usd >= 0 ? 'up' : 'dn' });
  const max = Math.max(0.01, ...rows.map((r) => Math.abs(r.contribution_usd)));
  return rows.map((r) => ({ ...r, share: (Math.abs(r.contribution_usd) / max) * 100 }));
}

export function moverLine(m) {
  const parts = [];
  if (m.return_pct != null) parts.push(`${signedPct(m.return_pct)} itself`);
  if (m.weight_pct != null) parts.push(`${m.weight_pct.toFixed(1)}% of the portfolio`);
  return parts.join(' · ');
}

// ---------- ledger ----------
export function ledger(pack) {
  if (!pack) return [];
  const flows = (pack.flows || []).map((f, i) => ({ key: `f${i}`, date: f.date, type: 'flow', title: FLOW[f.kind] || kindName(f.kind) || 'Cash move', symbol: null, account: f.account, amount: f.amount, detail: null }));
  const trades = (pack.trades || []).map((t, i) => ({
    key: `t${i}`,
    date: t.date,
    type: t.side === 'sell' ? 'sell' : 'buy',
    title: t.side === 'sell' ? 'Sold' : 'Bought',
    symbol: t.symbol,
    account: t.account,
    amount: t.amount,
    detail: t.shares != null && t.price != null ? `${Number(t.shares.toFixed(3))} sh at $${t.price.toFixed(2)}` : null,
  }));
  return [...flows, ...trades].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.type === 'flow' ? -1 : 1));
}

export function accountName(id) {
  const base = String(id || '').replace(/-\d+$/, '');
  if (!base) return 'Account';
  return base.length <= 4 ? base.toUpperCase() : `${base[0].toUpperCase()}${base.slice(1)}`;
}

// ---------- risk ----------
export function riskFacts(pack) {
  const r = pack?.risk;
  if (!r) return [];
  const out = [];
  const multi = (pack.coverage?.days || 0) > 1;
  if (multi && r.max_drawdown_pct != null) out.push({ id: 'dd', label: 'Deepest dip', value: signedPct(r.max_drawdown_pct, 2), sub: 'peak to trough inside the period' });
  if (r.volatility_pct != null) out.push({ id: 'vol', label: 'Swing', value: `${r.volatility_pct.toFixed(1)}%`, sub: 'yearly pace of the daily moves' });
  if (multi && r.best_day) out.push({ id: 'best', label: 'Best day', value: signedPct(r.best_day.pct, 2), sub: dayLabel(r.best_day.date) });
  if (multi && r.worst_day) out.push({ id: 'worst', label: 'Worst day', value: signedPct(r.worst_day.pct, 2), sub: dayLabel(r.worst_day.date) });
  return out;
}

export function bandLine(band) {
  if (!band) return null;
  const fit = FIT[band.fit] || null;
  const worst = band.worst_year_p10_pct != null ? ` A bad year for this mix is about ${signedPct(band.worst_year_p10_pct, 0)}; your band takes −${Math.round(band.worst_year_loss_pct)}%.` : '';
  return { chip: `Band ${band.band} · ${band.label}`, fit, tone: band.fit === 'above' ? 'watch' : band.fit === 'fits' ? 'ok' : 'info', text: worst.trim() };
}

// ---------- decisions, paper, events ----------
export function decisionRows(decisions) {
  const made = (decisions?.made || []).map((d) => ({ key: d.id, id: d.id, date: d.date, title: d.title, who: originName(d.origin), status: DECISION_STATUS[d.status] || kindName(d.status) }));
  const matured = (decisions?.matured || []).map((d) => ({
    key: `${d.id}-${d.horizon}`,
    id: d.id,
    date: d.end,
    title: `${kindName(d.kind)} ${d.symbol || ''}`.trim(),
    who: originName(d.origin),
    horizon: d.horizon,
    usd: d.usd,
    tone: d.usd > 0 ? 'up' : d.usd < 0 ? 'dn' : '',
  }));
  return { made, matured };
}

export function scoreLine(m) {
  const span = String(m.horizon || '').replace(/D$/i, ' days');
  if (m.usd == null) return `${span} on`;
  return `${span} on: ${m.usd >= 0 ? 'helped by' : 'cost'} ${usd(Math.abs(m.usd))}`;
}

export function eventWord(e) {
  return EVENT[e.type] || kindName(e.type) || 'Event';
}

// ---------- debrief ----------
export function debriefState(review) {
  if (!review?.pack) return { state: 'none', hint: null };
  const d = review.debrief;
  if (!d) return { state: 'waiting', hint: review.closed ? 'The debrief desk writes this up after its next run.' : `The debrief lands when the ${KIND_WORD[review.kind] || 'period'} closes.` };
  return { state: d.stale ? 'stale' : 'ok', hint: d.stale ? 'Written before the final numbers.' : null };
}

export function firstRunNote(index, review) {
  if (review?.note) return review.note;
  if (index?.note) return index.note;
  return 'The first review runs tonight, after the 5:35 PM numbers.';
}

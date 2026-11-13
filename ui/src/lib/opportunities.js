import { dayLabel } from './charts.js';
import { usd } from './format.js';
import { plainLine } from './jobs.js';

const price = (v) => usd(v, { cents: true });

export const STANCE = {
  buy: { tone: 'ok', t: 'Worth buying now' },
  watch: { tone: 'info', t: 'Watch' },
  screen: { tone: '', t: 'Cheap by the numbers' },
};

export function stanceOf(row) {
  const s = STANCE[row.stance] || STANCE.screen;
  return { tone: s.tone, t: row.stance_label || s.t };
}

export function heldLine(row) {
  if (!row.held) return 'Not held';
  return row.weight_pct ? `You hold ${Number(row.weight_pct).toFixed(1)}%` : 'You hold it';
}

export function entryLine(entry) {
  if (!entry || entry.low == null || entry.high == null) return null;
  const now = entry.price != null ? ` Now ${price(entry.price)}${entry.in_zone ? ', inside the zone' : ', outside the zone'}.` : '';
  return `${price(entry.low)} to ${price(entry.high)}.${now}`;
}

export function sizeLine(size) {
  if (!size) return null;
  if (!size.usd) return size.blocked || size.note || 'Nothing to buy now.';
  const shares = size.shares ? ` (about ${Number(size.shares).toFixed(2)} shares)` : '';
  return `${usd(size.usd)}${shares}. ${size.note || ''}`.trim();
}

export function earningsLine(e) {
  if (!e?.date) return null;
  const when = dayLabel(e.date);
  if (e.days == null) return `Earnings ${when}`;
  return e.days <= 0 ? `Earnings ${when}` : `Earnings in ${e.days} ${e.days === 1 ? 'day' : 'days'} (${when})`;
}

export function opportunityNotes(d) {
  if (!d) return [];
  return [d.prices?.words || null, d.freshness?.note || null, d.profile?.source === 'default_moderate' ? d.profile.note : null, d.cash?.note || null].filter(Boolean);
}

export function inQueue(row) {
  if (!row?.decision_id) return false;
  return row.queued === undefined ? true : row.queued === true;
}

const GROUPS = [
  { key: 'buy', t: 'Worth buying' },
  { key: 'could', t: 'Could become a buy' },
  { key: 'not_now', t: 'Not now' },
];

export function opportunityGroups(rows) {
  const list = Array.isArray(rows) ? rows : [];
  if (!list.some((r) => r.group)) return null;
  return GROUPS.map((g) => {
    const mine = list.filter((r) => (GROUPS.some((x) => x.key === r.group) ? r.group : 'not_now') === g.key);
    return { key: g.key, title: mine[0]?.group_label || g.t, rows: mine, fold: g.key === 'not_now' };
  }).filter((g) => g.rows.length);
}

// ---------- what would make a could a buy ----------
export function becomesBuy(row) {
  if (!row || (row.group && row.group !== 'could')) return null;
  return plainLine(row.becomes_buy);
}

export function evidenceLines(d) {
  const list = Array.isArray(d?.evidence) ? d.evidence : [];
  return list
    .filter((e) => e && plainLine(e.line))
    .map((e, k) => ({ key: e.id || `e${k}`, title: plainLine(e.title), line: plainLine(e.line), outdated: Boolean(e.outdated) }));
}

import { dayLabel } from './charts.js';
import { usd } from './format.js';

const EVERY = { weekly: 'every week', biweekly: 'every two weeks', semimonthly: 'twice a month', monthly: 'every month' };
const LANDED_MAX = 4;

// ---------- words ----------
export function ordinal(n) {
  const k = n % 100;
  const suf = k >= 11 && k <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th';
  return `${n}${suf}`;
}

export function rhythmText(d) {
  const amt = d.amount_usd ?? d.amount;
  const every = d.every || d.cadence || d.frequency;
  const days = d.days || (d.day ?? d.day_of_month ? [d.day ?? d.day_of_month] : []);
  const on = days.length ? `on the ${days.map(ordinal).join(' and ')}` : null;
  return [amt != null ? usd(amt) : null, every ? EVERY[every] || `every ${every}` : null, on, d.account ? `to ${d.account}` : null].filter(Boolean).join(' ');
}

export function seenText(d) {
  if (!d.observed) return null;
  return `seen ${d.observed} times${d.last ? `, last ${dayLabel(d.last)}` : ''}`;
}

export function emptyText(mode) {
  return mode === 'auto' ? 'Deposits are read from your activity. None on a steady rhythm right now.' : 'No deposit schedule in your profile yet.';
}

// ---------- money in ----------
export function moneyIn(list = []) {
  const items = list || [];
  const late = items.filter((d) => d.scheduled !== false && d.status === 'late').sort((a, b) => a.date.localeCompare(b.date));
  const seen = new Set();
  const next = items
    .filter((d) => d.status === 'expected')
    .sort((a, b) => a.date.localeCompare(b.date))
    .filter((d) => (seen.has(d.id) ? false : seen.add(d.id)));
  const landed = items
    .filter((d) => d.status === 'landed')
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, LANDED_MAX);
  const row = (d) => {
    const free = d.scheduled === false;
    const amount = d.landed?.amount ?? d.amount_usd;
    const where = d.account ? ` · ${d.account}` : '';
    const when =
      d.status === 'landed' ? `Landed ${dayLabel(d.date)}${where}` : d.status === 'late' ? `Not seen yet, due ${dayLabel(d.date)}${where}` : `Expected ${dayLabel(d.date)}${where}`;
    return { key: `${d.id}-${d.date}`, label: free ? 'Money in' : d.id, when, amount, status: d.status, scheduled: !free };
  };
  return [...late, ...next, ...landed].map(row);
}

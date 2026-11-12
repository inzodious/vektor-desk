import { createContext, useContext } from 'react';
import { dayWords } from './charts.js';
import { usd } from './format.js';
import { todayEt } from './tax.js';

export const AsOfContext = createContext(null);

export function useAsOf() {
  return useContext(AsOfContext);
}

// ---------- words ----------
function restOf(words) {
  const text = String(words || '').trim();
  const cut = text.indexOf('. ');
  return cut < 0 ? null : text.slice(cut + 2).trim() || null;
}

function firstSentence(words) {
  const text = String(words || '').trim();
  const cut = text.indexOf('. ');
  return (cut < 0 ? text : text.slice(0, cut)).replace(/\.$/, '');
}

export function fromDay(day, deskDay) {
  const mine = String(day || '').slice(0, 10);
  if (!mine || !deskDay || mine >= deskDay) return null;
  const label = dayWords(mine);
  return label ? `from ${label}` : null;
}

export function dayStamp(day, clock) {
  return clock ? fromDay(day, clock.day) : null;
}

export function dayWord(day, now = new Date()) {
  if (!day) return 'today';
  return day === todayEt(now) ? 'today' : `on ${dayWords(day)}`;
}

function signedPct(v) {
  if (v == null || Number.isNaN(v)) return null;
  const s = Math.abs(v).toFixed(2);
  const zero = !/[1-9]/.test(s);
  return `${zero ? '' : v < 0 ? '−' : '+'}${s}%`;
}

function figures(n, live) {
  if (!n) return null;
  const day = live || n;
  return {
    change: usd(day.day_change, { sign: true }),
    pct: signedPct(day.day_change_pct),
    tone: day.day_change > 0 ? 'up' : day.day_change < 0 ? 'dn' : '',
    cash: usd(n.cash_ready),
    pending: n.cash_pending ? usd(n.cash_pending) : null,
    margin: n.margin_debit ? usd(n.margin_debit) : 'none',
  };
}

// ---------- the desk's one "as of" ----------
export function asOfView(d, now = new Date()) {
  if (!d || typeof d !== 'object' || !d.day || d.status === 'empty') return null;
  const live = d.live && d.live.value != null ? d.live : null;
  const numbers = d.numbers && d.numbers.value != null ? d.numbers : null;
  const behind = d.behind?.reason || null;
  const book = firstSentence(d.words) || dayWords(d.day);
  const quoted = live ? firstSentence(live.words) || dayWords(live.day) : null;
  const label = quoted ? quoted.replace(/^Live,\s*/, '') : book;
  const older = Boolean(live && live.day && live.day > d.day);
  const head = live ? { value: live.value, change: live.day_change, pct: live.day_change_pct, when: dayWord(live.day, now), live: true } : numbers ? { value: numbers.value, change: numbers.day_change, pct: numbers.day_change_pct, when: dayWord(d.day, now), live: false } : null;
  return {
    day: d.day,
    dayWords: dayWords(d.day),
    shown: live?.day || d.day,
    text: `As of ${label}`,
    ticking: Boolean(live && /^Live\b/.test(quoted)),
    provisional: Boolean(d.provisional) && !older,
    behind: live ? null : behind,
    waiting: !live && d.prices?.waiting?.length ? restOf(d.words) : null,
    books: older ? `Book as of ${book}` : null,
    title: [live ? `Prices: ${quoted}. Cash, margin and the review come from the closed book, ${book}.` : d.words, behind].filter(Boolean).join(' ') || null,
    tone: behind && !live ? 'watch' : '',
    numbers,
    figures: figures(numbers, live),
    live,
    liveWords: live?.words || null,
    headline: head,
    review: d.review?.day || null,
    debrief: d.debrief || null,
  };
}

export function asOfFromMetrics(day) {
  return day ? asOfView({ day, status: 'final', words: null }) : null;
}

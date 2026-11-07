const ET = 'America/New_York';

export const HOLIDAYS = new Set([
  '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
  '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
]);

export const EARLY_CLOSE = new Set(['2026-11-27', '2026-12-24', '2027-11-26']);

const OPEN = 9 * 60 + 30;
const CLOSE = 16 * 60;
const EARLY = 13 * 60;
const PRE = 4 * 60;
const AFTER = 20 * 60;

export function etParts(date) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', { timeZone: ET, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short' })
      .formatToParts(date)
      .map((p) => [p.type, p.value]),
  );
  return { day: `${parts.year}-${parts.month}-${parts.day}`, minutes: Number(parts.hour) * 60 + Number(parts.minute), weekday: parts.weekday };
}

export function isTradingDay(day, weekday) {
  return weekday !== 'Sat' && weekday !== 'Sun' && !HOLIDAYS.has(day);
}

export function closeFor(day) {
  return EARLY_CLOSE.has(day) ? EARLY : CLOSE;
}

function fmtMinutes(m) {
  const h = Math.floor(m / 60);
  const mm = String(m % 60).padStart(2, '0');
  return `${((h + 11) % 12) + 1}:${mm} ${h < 12 ? 'AM' : 'PM'}`;
}

function nextOpen(date) {
  for (let i = 1; i <= 10; i += 1) {
    const p = etParts(new Date(date.getTime() + i * 86400000));
    if (isTradingDay(p.day, p.weekday)) return `${i === 1 ? 'tomorrow' : p.weekday} 9:30 AM`;
  }
  return '9:30 AM';
}

export function marketState(date = new Date()) {
  const { day, minutes, weekday } = etParts(date);
  const close = closeFor(day);
  if (!isTradingDay(day, weekday)) {
    return { state: 'closed', label: HOLIDAYS.has(day) ? 'Market holiday' : 'Market closed', hint: `Opens ${nextOpen(date)} ET` };
  }
  if (minutes >= OPEN && minutes < close) {
    return { state: 'open', label: close === EARLY ? 'Open · early close' : 'Market open', hint: `Closes ${fmtMinutes(close)} ET` };
  }
  if (minutes >= PRE && minutes < OPEN) return { state: 'pre', label: 'Pre-market', hint: 'Opens 9:30 AM ET' };
  if (minutes >= close && minutes < AFTER) return { state: 'after', label: 'After hours', hint: `Closed at ${fmtMinutes(close)} ET` };
  if (minutes < PRE) return { state: 'closed', label: 'Market closed', hint: 'Opens 9:30 AM ET' };
  return { state: 'closed', label: 'Market closed', hint: `Opens ${nextOpen(date)} ET` };
}

const LIVE = ['pre', 'open', 'after'];

export function clockState(now, live) {
  const m = marketState(now);
  if (!live || !live.state || (live.day && live.day !== etParts(now).day)) return { ...m, feed: m.state === 'open' ? 'live' : 'off' };
  const state = live.state;
  const base = state === m.state ? m : { ...m, state, label: { open: 'Market open', pre: 'Pre-market', after: 'After hours', closed: 'Market closed' }[state] || m.label };
  if (!LIVE.includes(state)) return { ...base, feed: 'off' };
  const fresh = live.as_of && now - new Date(live.as_of) <= 10 * 60000;
  if (fresh && live.quality !== 'stale') return { ...base, feed: 'live', hint: `${base.hint} · quotes refresh every 5 min` };
  return { ...base, feed: 'delayed', label: state === 'open' ? 'Quotes delayed' : base.label, hint: live.as_of ? `Last quote ${new Intl.DateTimeFormat('en-US', { timeZone: ET, hour: 'numeric', minute: '2-digit' }).format(new Date(live.as_of))} ET` : 'Waiting on the first quote' };
}

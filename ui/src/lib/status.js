import { ago, etStamp, plainDate, plural } from './format.js';

export const MIRROR = {
  ok: { tone: 'ok', chip: 'Fresh', icon: 'check' },
  stale: { tone: 'watch', chip: 'Stale', icon: 'clock' },
  failing: { tone: 'act', chip: 'Last pull failed', icon: 'bolt' },
  empty: { tone: 'info', chip: 'Not yet', icon: 'info' },
  error: { tone: 'act', chip: 'Unreadable', icon: 'bolt' },
};

export const TOKEN = {
  ok: { tone: 'ok', chip: 'Good', icon: 'check' },
  renew: { tone: 'watch', chip: 'Renew soon', icon: 'clock' },
  expired: { tone: 'act', chip: 'Expired', icon: 'bolt' },
  unknown: { tone: 'info', chip: 'Not set', icon: 'info' },
};

export const THEMES = [
  { v: 'light', t: 'Light' },
  { v: 'dark', t: 'Graphite dark' },
];

export const JOBS = { mirror: 'Mirror pull', backup: 'Backup', prices: 'Price refresh' };

export function mirrorLine(m) {
  if (m.state === 'empty') return m.note || "The mirror hasn't run yet.";
  if (m.state === 'error' && !m.last_ok) return 'The mirror database could not be read.';
  const when = etStamp(m.last_ok);
  return when ? `Last good pull ${when} · ${ago(m.age_hours)}` : 'No good pull yet';
}

export function tokenLine(t) {
  if (t.state === 'unknown') return 'Expiry date not set';
  if (t.state === 'expired') return `Expired ${plainDate(t.expires)}`;
  return `Good to ${plainDate(t.expires)}`;
}

export function daysLabel(t) {
  if (t.days_left == null) return null;
  if (t.days_left < 0) return `${plural(-t.days_left, 'day')} over`;
  return plural(t.days_left, 'day');
}

export function summary(s) {
  const issues = [s.mirror.state !== 'ok', s.claude_token.state !== 'ok'].filter(Boolean).length;
  return issues === 0 ? 'All fresh' : `${issues} to look at`;
}

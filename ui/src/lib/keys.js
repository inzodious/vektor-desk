import { when } from './box.js';

const FILES = { 'desk.env': 'Desk', 'settings.env': 'Settings', 'caddy.env': 'Certificates', 'tailscale.env': 'Tailscale' };

// ---------- words ----------
export function fileWord(file) {
  return FILES[file] || file;
}

export function keyCount(d) {
  const keys = d?.keys || [];
  return { set: keys.filter((k) => k.set).length, total: keys.length, pending: keys.filter((k) => k.pending).length };
}

export function keyState(k, now = new Date()) {
  if (!k) return { state: 'unset', line: '' };
  if (k.pending) return { state: 'pending', line: 'Sealed and on its way. The box saves it within 5 min, then redeploys.' };
  const last = k.last;
  if (last?.result === 'refused') return { state: 'refused', line: `The box turned it down${last.at ? ` ${when(last.at, now)}` : ''}: ${last.message || 'no reason given'}` };
  if (last?.result === 'failed') return { state: 'failed', line: `Didn’t save${last.at ? ` ${when(last.at, now)}` : ''}: ${last.message || 'try again'}` };
  if (k.set) return { state: 'set', line: last?.result === 'saved' && last.at ? `Saved ${when(last.at, now)}` : 'Set on the box' };
  return { state: 'unset', line: 'Not set yet' };
}

// ---------- checks ----------
export function keyCheck(name, value) {
  const v = value ?? '';
  if (!v.trim()) return 'Paste a value first.';
  if (v.length > 1024) return 'That’s longer than 1,024 characters. Check the paste.';
  if (/[\r\n]/.test(v)) return 'Keys are one line. Remove the line break.';
  if (v.includes("'")) return 'Keys can’t contain a single quote.';
  if (name === 'ALPACA_API_KEY_ID' && !v.trim().startsWith('PK')) return 'Paper key IDs start with PK. Live keys are never accepted.';
  if (name === 'DESK_CLAUDE_TOKEN_EXPIRES' && !/^\d{4}-\d{2}-\d{2}$/.test(v.trim())) return 'Use a date like 2027-11-03.';
  return null;
}

export function keyRefusal(err) {
  const b = err?.body || {};
  if (b.error === 'host_down') return 'The box hasn’t checked in with its lock yet, so the key would have nowhere to go. Try again once it has.';
  if (b.error === 'refused' || b.error === 'bad_body') return b.message || 'The desk turned that value down.';
  return err?.message || 'The desk didn’t take that. Try again in a moment.';
}

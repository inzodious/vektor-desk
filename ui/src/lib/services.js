import { plainLine } from './jobs.js';
import { whenWords } from './morning.js';

const STATE = {
  up: { t: 'Up', dot: 'ok', tone: 'ok' },
  starting: { t: 'Starting', dot: 'queued', tone: '' },
  stopped: { t: 'Down', dot: 'failed', tone: 'watch' },
  restarting: { t: 'Restarting', dot: 'failed', tone: 'watch' },
  unhealthy: { t: 'Unwell', dot: 'failed', tone: 'watch' },
  missing: { t: 'Missing', dot: 'failed', tone: 'watch' },
};
const HEAD = { ok: { chip: 'All running', tone: 'ok' }, trouble: { chip: 'Needs a look', tone: 'watch' } };

const cap = (text) => (text ? `${text[0].toUpperCase()}${text.slice(1)}` : '');

// ---------- the box's services, in words ----------
export function servicesView(c, now = new Date()) {
  if (!c || typeof c !== 'object' || !c.state) return null;
  const head = HEAD[c.state] || { chip: 'Not reported', tone: '' };
  const rows = (Array.isArray(c.services) ? c.services : []).map((s) => ({
    name: s.name,
    title: cap(s.title || s.name),
    words: plainLine(s.words),
    ...(STATE[s.state] || { t: 'Unknown', dot: 'never', tone: '' }),
  }));
  const link = c.tailnet && typeof c.tailnet === 'object' ? c.tailnet : null;
  const checked = whenWords(c.checked_at, now);
  const note = plainLine(c.note);
  const words = link?.state === 'trouble' ? plainLine(link.words) : null;
  return {
    state: c.state,
    chip: head.chip,
    tone: head.tone,
    note,
    checked: checked ? `Checked ${checked} ET` : null,
    rows,
    link: words && !(note || '').includes(words) ? words : null,
  };
}

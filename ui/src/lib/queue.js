import { originName } from './decisions.js';
import { plainLine } from './jobs.js';
import { whenWords } from './morning.js';

// ---------- snoozed ----------
export function snoozedRows(q, now = new Date()) {
  const items = Array.isArray(q?.snoozed_items) ? q.snoozed_items : [];
  return items
    .filter((d) => d && d.id)
    .map((d) => {
      const back = whenWords(d.snoozed_until, now);
      return { id: d.id, title: d.title || 'Untitled proposal', why: plainLine(d.status_reason), who: originName(d.origin), back: back ? `back ${back.replace(/^Today/, 'today')} ET` : null };
    });
}

// ---------- what became of a replaced proposal ----------
const ENDED = {
  approved: 'You approved the latest one',
  placed: 'You placed the latest one',
  filled: 'The latest one was placed and filled',
  done: 'The latest one is done',
  dismissed: 'You dismissed the latest one',
  passed: 'You passed on the latest one',
  logged: 'The latest one was kept as a note',
};

export function successorLine(d) {
  const s = d?.successor;
  if (!s || typeof s !== 'object') return null;
  const name = s.title ? `, “${s.title}”` : '';
  if (s.open) return { open: true, id: s.id || null, text: `The latest one${name}${name ? ',' : ''} is ${s.status === 'snoozed' ? 'snoozed' : 'waiting in your queue'}.` };
  const why = plainLine(s.status_reason);
  const head = ENDED[s.status] ? `${ENDED[s.status]}${name}.` : `The latest one${name}${name ? ',' : ''} has left the queue too.`;
  return { open: false, id: s.id || null, text: why && !ENDED[s.status] ? `${head} ${why}` : head };
}

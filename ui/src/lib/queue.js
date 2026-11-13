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
export function successorLine(d) {
  const s = d?.successor;
  if (!s || typeof s !== 'object') return null;
  const head = plainLine(s.title) ? `It became “${plainLine(s.title)}”.` : null;
  const outcome = plainLine(s.outcome);
  if (!head && !outcome) return null;
  return { open: Boolean(s.open), id: s.id || null, text: [head, outcome].filter(Boolean).join(' ') };
}

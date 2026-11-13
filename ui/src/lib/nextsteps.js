import { postJson } from './api.js';
import { dayLabel } from './charts.js';
import { plainLine } from './jobs.js';

const STATE = { open: 'Due now', partial: 'Partly done' };
const UNDO_BASE = '/api/decisions/next-steps/';

// ---------- one row ----------
function evidenceOf(s, readings) {
  if (s.backed === 'untested') return { tests: [], chip: null };
  const list = (Array.isArray(s.evidence) ? s.evidence : []).filter((e) => e && typeof e === 'object');
  const tests = list.filter((e) => plainLine(e.sentence) || plainLine(e.title)).map((e, k) => ({ key: e.row || `t${k}`, row: typeof e.row === 'string' && e.row ? e.row : null, title: plainLine(e.title), sentence: plainLine(e.sentence) }));
  const words = plainLine(readings?.[s.backed]) || plainLine(list[0]?.words);
  return { tests, chip: words ? { text: words, tone: s.backed === 'no' ? 'watch' : '' } : null };
}

function span(from, to) {
  const a = dayLabel(from || '');
  const b = dayLabel(to || '');
  return a && b ? `${a} to ${b}` : a || (b ? `until ${b}` : '');
}

export function readWords(read) {
  if (!read || typeof read !== 'object') return null;
  const when = span(read.date, read.until);
  if (!when) return null;
  const phrase = plainLine(read.phrase);
  return `read as ${when}${phrase ? `, from “${phrase}”` : ''}`;
}

export function undoPath(undo) {
  return undo && undo.method === 'DELETE' && typeof undo.path === 'string' && undo.path.startsWith(UNDO_BASE) && undo.path.length > UNDO_BASE.length ? undo.path : null;
}

export function stepRow(s, readings = null) {
  const date = dayLabel(s.date || '');
  const until = dayLabel(s.until || '');
  const mine = s.source === 'you';
  const read = mine ? readWords(s.read) : null;
  const window = read ? null : date && until ? `Any day to ${until}` : !date && until ? `Until ${until}` : null;
  const meta = [mine ? 'Your words' : null, STATE[s.status] || null, read, window, plainLine(s.when)].filter(Boolean);
  const queued = s.completes === 'you' && typeof s.ref?.decision_id === 'string' ? s.ref.decision_id : null;
  return {
    id: s.id,
    symbol: s.symbol || null,
    mine,
    stamp: date || null,
    text: plainLine(s.text) || 'A step with no words yet',
    detail: plainLine(s.detail),
    meta: meta.join(' · ') || null,
    read,
    why: plainLine(s.why),
    basis: plainLine(s.basis),
    changes: plainLine(s.changes_if),
    queue: queued ? `/decisions?d=${encodeURIComponent(queued)}` : null,
    undo: mine ? undoPath(s.undo) : null,
    ...evidenceOf(s, readings),
  };
}

// ---------- the list ----------
export function nextSteps(d) {
  const rows = (list) => (Array.isArray(list) ? list : []).filter((s) => s && s.id).map((s) => stepRow(s, d?.readings));
  const items = rows(d?.items);
  const standing = rows(d?.standing);
  const days = Number(d?.days) > 0 ? Number(d.days) : 90;
  return { items, standing, days, empty: !items.length && !standing.length };
}

// ---------- a pass that became a step ----------
export function addedStep(out) {
  const s = out?.step;
  if (!s || typeof s !== 'object' || !s.id) return null;
  const row = stepRow(s);
  return { id: row.id, text: row.text, read: row.read, undo: row.undo };
}

export async function undoStep(path) {
  try {
    await postJson(path, null, { method: 'DELETE' });
    return 'Taken off your next steps.';
  } catch (e) {
    if (e.status === 404 || e.status === 409) return 'It had already left your next steps.';
    throw e;
  }
}

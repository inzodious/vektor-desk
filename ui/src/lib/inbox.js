import { when } from './box.js';

export const BROKER = 'fidelity';

// ---------- words ----------
export function fileSize(bytes) {
  if (bytes == null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function inboxFiles(inbox, broker = BROKER) {
  const files = inbox?.brokers?.[broker]?.files || [];
  return [...files].sort((a, b) => (b.modified || '').localeCompare(a.modified || ''));
}

export function fileLine(f, now = new Date()) {
  return `${fileSize(f.size)} · added ${when(f.modified, now) || '—'}`;
}

export function limitText(inbox) {
  const mb = inbox?.max_bytes ? Math.round(inbox.max_bytes / (1024 * 1024)) : 25;
  const kinds = (inbox?.suffixes || ['.csv', '.json']).map((s) => s.replace('.', '').toUpperCase()).join(' or ');
  return `${kinds}, up to ${mb} MB`;
}

// ---------- checks ----------
export function precheck(file, inbox) {
  if (!file) return 'Pick a file first.';
  const suffixes = inbox?.suffixes || ['.csv', '.json'];
  if (!suffixes.some((s) => file.name.toLowerCase().endsWith(s))) return `That’s not a ${limitText(inbox).split(',')[0]} file. Export the lots as CSV and try again.`;
  if (!file.size) return 'That file is empty.';
  if (inbox?.max_bytes && file.size > inbox.max_bytes) return `That file is ${fileSize(file.size)}; the inbox takes ${limitText(inbox).split(', ')[1]}.`;
  return null;
}

export function savedText(r) {
  if (!r) return '';
  return r.duplicate ? `Already in the inbox as ${r.name}. Nothing new to save.` : `Saved as ${r.name} (${fileSize(r.size)}).`;
}

export function inboxRefusal(err) {
  const b = err?.body || {};
  if (b.error === 'too_large') return `Too big for the inbox. ${b.message || ''}`.trim();
  if (b.error === 'bad_name') return 'The file name has characters the desk won’t take. Rename it to letters, numbers and dashes, then try again.';
  if (b.error === 'bad_csv') return 'That CSV has no header line. Export it from Fidelity again and try once more.';
  if (b.error === 'bad_json') return 'That JSON file doesn’t parse. Export it again and try once more.';
  if (b.error === 'not_text' || b.error === 'empty') return b.message || 'That isn’t a text export.';
  if (b.error === 'unknown_broker') return 'The desk only takes Fidelity files for now.';
  return err?.message || 'The upload didn’t go through. Try again in a moment.';
}

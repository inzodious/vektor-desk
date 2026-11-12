import { dayWords } from './charts.js';
import { plural } from './format.js';
import { plainLine } from './jobs.js';
import { whenWords } from './morning.js';

const ROLE = { held: 'You hold it', benchmark: 'Yardstick', plan: 'In your plan', watch: 'Watched', past: 'Held before', universe: 'Scanner list' };
export const BACKFILL_TOP = 4;

// ---------- one name ----------
export function backfillRow(r, now = new Date()) {
  const asked = whenWords(r.fetched_at, now);
  const parked = whenWords(r.parked_until, now);
  const error = plainLine(r.error);
  return {
    symbol: r.symbol,
    role: ROLE[r.role] || 'Followed',
    last: r.last_bar ? `Last close ${dayWords(r.last_bar) || r.last_bar}` : 'No price history yet',
    asked: asked ? `asked ${asked} ET` : 'not asked yet',
    note: parked ? `Set aside until ${parked} ET${error ? `: ${error}` : ''}` : error,
    held: r.role === 'held',
  };
}

// ---------- the card ----------
export function backfillView(d, now = new Date()) {
  if (!d || !Array.isArray(d.symbols)) return null;
  const target = dayWords(d.target) || d.target || 'the last trading day';
  const said = plainLine(d.last_run?.detail);
  const when = whenWords(d.last_run?.finished_at, now);
  const lastLine = said ? `Last ask${when ? `, ${when} ET` : ''}: ${said}` : null;
  if (!d.symbols.length) return { state: 'none', chip: 'Not started', tone: '', icon: 'info', line: 'No price history yet. It fills in on the first ask.', rows: [], lastLine };
  const behind = d.symbols.filter((s) => s.behind);
  if (!behind.length) return { state: 'ok', chip: 'Up to date', tone: 'ok', icon: 'check', line: `Every name the desk follows daily has its close for ${target}.`, rows: [], lastLine };
  const held = behind.filter((s) => s.role === 'held').length;
  const asks = d.asks ? ` The desk asks ${d.asks}.` : '';
  return {
    state: 'behind',
    chip: `${behind.length} behind`,
    tone: held ? 'watch' : '',
    icon: 'info',
    line: `${plural(behind.length, 'name')} still waiting on the close for ${target}${held ? `, ${held} of them yours` : ''}.${asks}`,
    rows: behind.map((r) => backfillRow(r, now)),
    lastLine,
  };
}

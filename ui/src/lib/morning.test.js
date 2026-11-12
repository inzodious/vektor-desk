import { describe, expect, it } from 'vitest';
import { excessWords, holdingsDoor, libraryChip, libraryGroups, opportunitiesDoor, strategiesDoor, whenWords } from './morning.js';
import { guideFor } from './guide.js';
import { earningsLine, entryLine, heldLine, inQueue, opportunityNotes, sizeLine, stanceOf } from './opportunities.js';
import { holdingChip } from './research.js';

const NOW = new Date('2026-11-12T15:00:00Z');
const ok = (data) => ({ data, loading: false, error: null });
const LIB = {
  as_of: '2026-11-12T08:12:00+00:00',
  counts: { total: 6, tested: 5, held_up: 1, within_noise: 2, fell_short: 2, inconclusive: 0, waiting: 1, not_run: 0 },
  kinds: [
    { key: 'classic', title: 'Old and tested' },
    { key: 'novel', title: 'Novel and creative' },
  ],
  rows: [
    { id: 'a', kind: 'classic', status: 'tested', verdict: 'held_up', out_of_sample: { excess_pts: 3.14 } },
    { id: 'b', kind: 'classic', status: 'tested', verdict: 'fell_short', out_of_sample: { excess_pts: -1.26 } },
    { id: 'c', kind: 'novel', status: 'waiting', verdict: null, reason: 'In tonight’s queue.', out_of_sample: null },
  ],
};

describe('this morning', () => {
  it('says when in plain words', () => {
    expect(whenWords('2026-11-12T08:12:00+00:00', NOW)).toBe('Today, 3:12 AM');
    expect(whenWords('2026-11-11T22:21:00+00:00', NOW)).toBe('Wed Nov 11, 5:21 PM');
    expect(whenWords(null, NOW)).toBeNull();
    expect(whenWords('soon', NOW)).toBeNull();
  });

  it('counts the strategies tested and what held up', () => {
    expect(strategiesDoor(ok(LIB), NOW)).toEqual({ state: 'ready', count: '5 of 6', unit: 'tested', line: '1 held up out of sample. 2 inside the noise, 2 fell short, 1 still to run.', fresh: 'Today, 3:12 AM' });
    const none = strategiesDoor(ok({ ...LIB, counts: { total: 6, tested: 6, held_up: 0, within_noise: 0, fell_short: 6 } }), NOW);
    expect(none.count).toBe('6');
    expect(none.line).toBe('None held up out of sample. 6 fell short.');
  });

  it('gives the reason when nothing has run yet', () => {
    const waiting = strategiesDoor(ok({ as_of: null, counts: { total: 3, tested: 0, waiting: 3 }, rows: [LIB.rows[2]] }), NOW);
    expect(waiting).toEqual({ state: 'waiting', count: '0 of 3', unit: 'tested', line: 'In tonight’s queue.', fresh: null });
  });

  it('never leaves a door blank', () => {
    expect(strategiesDoor({ data: null, loading: true, error: null }).line).toBe('Checking…');
    expect(holdingsDoor({ data: null, loading: false, error: { status: 404 } })).toMatchObject({ state: 'off', count: '—', line: 'One analysis per holding arrives with the next desk update.' });
    expect(opportunitiesDoor({ data: null, loading: false, error: { status: 500 } })).toMatchObject({ state: 'down', line: 'The desk did not answer. It tries again by itself.' });
  });

  it('reads the holdings pass and the opportunities list as given', () => {
    expect(holdingsDoor(ok({ held: 5, analysed: 4, failed: 1, fresh_at: '2026-11-12T08:44:00+00:00', line: '4 of 5 holdings analysed.' }), NOW)).toEqual({ state: 'ready', count: '4 of 5', unit: 'analysed', line: '4 of 5 holdings analysed.', fresh: 'Today, 3:44 AM', tone: 'watch' });
    expect(holdingsDoor(ok({ held: 5, analysed: 0, line: 'The first pass runs tonight.' }), NOW)).toMatchObject({ state: 'waiting', count: '0 of 5', fresh: null, tone: '' });
    expect(opportunitiesDoor(ok({ counts: { total: 1 }, headline: '1 worth buying now.', freshness: { night_run_at: null }, built_at: '2026-11-12T10:05:00Z' }), NOW)).toEqual({ state: 'ready', count: '1', unit: 'idea', line: '1 worth buying now.', fresh: 'Today, 5:05 AM' });
    expect(opportunitiesDoor(ok({ counts: { total: 0 }, headline: 'No list yet.', note: 'No list yet: the engine has not run.', rows: [] }), NOW)).toEqual({ state: 'waiting', count: '0', unit: 'ideas', line: 'No list yet: the engine has not run.', fresh: null });
  });

  it('groups the library by kind and words each result', () => {
    const groups = libraryGroups(LIB);
    expect(groups.map((g) => [g.title, g.rows.length, g.line])).toEqual([
      ['Old and tested', 2, '2 tested · 1 held up'],
      ['Novel and creative', 1, '1 waiting'],
    ]);
    expect(libraryChip(LIB.rows[0])).toEqual({ t: 'Held up', tone: 'ok' });
    expect(libraryChip(LIB.rows[2])).toEqual({ t: 'Waiting to run', tone: 'info' });
    expect(libraryChip({ status: 'not_run' }).t).toBe('Not run');
    expect(excessWords(LIB.rows[0])).toBe('+3.1 pts a year');
    expect(excessWords(LIB.rows[1])).toBe('−1.3 pts a year');
    expect(excessWords(LIB.rows[2])).toBeNull();
    expect(libraryGroups(null)).toEqual([]);
  });
});

describe('page guides', () => {
  it('says what each page is and where to go next', () => {
    expect(guideFor('/')).toEqual({ what: 'The whole desk at a glance: what you own, what ran overnight and what needs you.', next: { to: '/decisions', label: 'Decisions' } });
    expect(guideFor('/results/day').next).toEqual({ to: '/portfolio', label: 'Portfolio' });
    expect(guideFor('/research/opportunities').next.to).toBe('/decisions');
    expect(guideFor('/research').next.to).toBe('/research/opportunities');
    expect(guideFor('/strategies/sector-momentum').next).toEqual({ to: '/strategies', label: 'All strategies' });
    expect(guideFor('/strategies/habits/replay').what).toContain('habits');
    expect(guideFor('/plan').next.to).toBe('/portfolio/stocks');
    expect(guideFor('/lab/risk').next.to).toBe('/portfolio/tax');
    expect(guideFor('/nowhere')).toBeNull();
  });
});

describe('buying opportunities', () => {
  it('words the stance, the holding and the zone', () => {
    expect(stanceOf({ stance: 'buy', stance_label: 'Worth buying with the next deposit' })).toEqual({ tone: 'ok', t: 'Worth buying with the next deposit' });
    expect(stanceOf({ stance: 'screen' }).t).toBe('Cheap by the numbers');
    expect(heldLine({ held: true, weight_pct: 6.2 })).toBe('You hold 6.2%');
    expect(heldLine({ held: false })).toBe('Not held');
    expect(entryLine({ low: 171.2, high: 180.4, price: 180.4, in_zone: true })).toBe('$171.20 to $180.40. Now $180.40, inside the zone.');
    expect(entryLine({ low: null, high: 180.4 })).toBeNull();
  });

  it('never shows a size of zero dollars', () => {
    expect(sizeLine({ usd: 800, shares: 4.43, note: 'A starter slice.' })).toBe('$800 (about 4.43 shares). A starter slice.');
    expect(sizeLine({ usd: 0, funding: 'wait', blocked: null, note: 'No free cash today; it waits for the next deposit.' })).toBe('No free cash today; it waits for the next deposit.');
    expect(sizeLine({ usd: 0, blocked: 'Past its 5% band.', note: 'Nothing to add.' })).toBe('Past its 5% band.');
    expect(sizeLine(null)).toBeNull();
  });

  it('carries the notes that explain the list', () => {
    expect(earningsLine({ date: '2026-11-20', days: 9 })).toBe('Earnings in 9 days (Nov 20)');
    expect(earningsLine(null)).toBeNull();
    expect(opportunityNotes({ freshness: { note: '3 have no written case yet.' }, profile: { source: 'default_moderate', note: 'Sizes use the Moderate band.' }, cash: { note: 'Never from margin.' } })).toEqual(['3 have no written case yet.', 'Sizes use the Moderate band.', 'Never from margin.']);
    expect(opportunityNotes({ profile: { source: 'risk_check', note: 'x' }, cash: {} })).toEqual([]);
    expect(opportunityNotes({ prices: { words: 'Prices run to Wed Nov 11.' }, freshness: { note: 'One has no case.' } })).toEqual(['Prices run to Wed Nov 11.', 'One has no case.']);
    expect(inQueue({ decision_id: 'd_1', queued: true })).toBe(true);
    expect(inQueue({ decision_id: 'd_1', queued: false })).toBe(false);
    expect(inQueue({ decision_id: 'd_1' })).toBe(true);
    expect(inQueue({ decision_id: null, queued: true })).toBe(false);
  });
});

describe('research by holding', () => {
  it('shows the verdict when there is one, the status when there is not', () => {
    expect(holdingChip({ status: 'today', verdict: 'add' }).t).toBe('Add on plan');
    expect(holdingChip({ status: 'failed', verdict: 'hold' }).t).toBe('Hold in band');
    expect(holdingChip({ status: 'failed', verdict: null })).toEqual({ t: 'Last try failed', tone: 'watch' });
    expect(holdingChip({ status: 'none' }).t).toBe('Not analysed yet');
    expect(holdingChip({ status: 'running' }).t).toBe('Running now');
  });
});

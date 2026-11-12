import { describe, expect, it } from 'vitest';
import d from '../fixtures/engine.backfill.json';
import current from '../fixtures/engine.backfill.current.json';
import { backfillRow, backfillView } from './backfill.js';

const NOW = new Date('2026-11-09T16:42:00Z');

describe('price history', () => {
  it('lists only the names that are behind, held first, in plain words', () => {
    const v = backfillView(d, NOW);
    expect(v.state).toBe('behind');
    expect(v.chip).toBe('8 behind');
    expect(v.tone).toBe('watch');
    expect(v.line).toBe('8 names still waiting on the close for Fri Nov 6, 1 of them yours. The desk asks every hour, day and night.');
    expect(v.rows.map((r) => r.symbol)).toEqual(['FXAIX', 'NOVA', 'ZZNEW', 'HLTH', 'IDXA', 'IDXB', 'IDXC', 'IDXD']);
    expect(v.rows[0]).toEqual({ symbol: 'FXAIX', role: 'You hold it', last: 'Last close Thu Nov 5', asked: 'asked Today, 6:13 AM ET', note: null, held: true });
    expect(v.rows[1].note).toBe('Tiingo did not answer for NOVA');
    expect(v.rows[2]).toMatchObject({ role: 'Watched', last: 'No price history yet', note: 'Set aside until Mon Nov 16, 6:13 AM ET: Tiingo has no prices for ZZNEW' });
    expect(v.lastLine).toBe('Last ask, Today, 11:13 AM ET: Asked Tiingo for 8 names. Failed: NOVA: Tiingo did not answer for NOVA. FXAIX and 5 others answered with nothing new for 2026-11-06.');
  });

  it('says so when nothing is behind, before the first ask, and stays quiet on a desk without the endpoint', () => {
    const ok = backfillView(current, NOW);
    expect(ok).toMatchObject({ state: 'ok', chip: 'Up to date', tone: 'ok', rows: [], line: 'Every name the desk follows daily has its close for Fri Nov 6.' });
    expect(ok.lastLine).toBe('Last ask, Today, 11:13 AM ET: Nothing was behind, so Tiingo was not asked.');
    expect(backfillView({ target: '2026-11-06', symbols: [], last_run: null }, NOW)).toMatchObject({ state: 'none', chip: 'Not started', lastLine: null });
    expect(backfillView(null, NOW)).toBeNull();
    expect(backfillView({ detail: 'Not Found' }, NOW)).toBeNull();
    expect(backfillView({ ...d, symbols: d.symbols.filter((s) => s.role !== 'held') }, NOW).tone).toBe('');
  });

  it('never prints raw output and names an unknown role plainly', () => {
    expect(backfillRow({ symbol: 'X', role: 'new_role', last_bar: '2026-11-05', fetched_at: null, error: '{"status": 500}' }, NOW)).toEqual({ symbol: 'X', role: 'Followed', last: 'Last close Thu Nov 5', asked: 'not asked yet', note: null, held: false });
    expect(backfillView({ ...d, last_run: { finished_at: null, detail: '{"fetched": []}' } }, NOW).lastLine).toBeNull();
  });
});

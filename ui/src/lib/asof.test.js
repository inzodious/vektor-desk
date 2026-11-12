import { describe, expect, it } from 'vitest';
import { asOfFromMetrics, asOfView, dayStamp, dayWord, fromDay } from './asof.js';
import { dayWords } from './charts.js';

const NOW = new Date('2026-11-12T19:20:00Z');
const NUMBERS = { value: 41262.18, day_change: 524.14, day_change_pct: 1.2866, cash_ready: 603.12, cash_pending: 250, cash_pending_days: 6, margin_debit: 1500, margin_cost_month: 15.09 };
const FINAL = { day: '2026-11-11', at: '2026-11-12T06:26:10+00:00', provisional: false, status: 'final', words: 'Wed Nov 11, at the close.', behind: null, numbers: NUMBERS, live: null, review: { day: '2026-11-11' }, debrief: { day: '2026-11-11', stale: true } };
const LIVE = { day: '2026-11-12', state: 'open', at: '2026-11-12T19:15:04+00:00', value: 41010.77, day_change: -251.41, day_change_pct: -0.6093, words: 'Live, Thu Nov 12, 2:15 PM ET' };

describe('one clock', () => {
  it('names a day in words', () => {
    expect(dayWords('2026-11-11')).toBe('Wed Nov 11');
    expect(dayWords('nope')).toBe('');
  });

  it('labels a number only when its day is older than the desk day', () => {
    expect(fromDay('2026-11-10', '2026-11-11')).toBe('from Tue Nov 10');
    expect(fromDay('2026-11-11', '2026-11-11')).toBeNull();
    expect(fromDay('2026-11-12', '2026-11-11')).toBeNull();
    expect(fromDay(null, '2026-11-11')).toBeNull();
    expect(dayStamp('2026-11-10', { day: '2026-11-11' })).toBe('from Tue Nov 10');
    expect(dayStamp('2026-11-10', null)).toBeNull();
  });

  it('says today only when the day is today in New York', () => {
    expect(dayWord('2026-11-12', NOW)).toBe('today');
    expect(dayWord('2026-11-11', NOW)).toBe('on Wed Nov 11');
    expect(dayWord('2026-11-11', new Date('2026-11-12T02:00:00Z'))).toBe('today');
  });

  it('reads the closed book when there is no live block', () => {
    const v = asOfView(FINAL, NOW);
    expect(v.text).toBe('As of Wed Nov 11, at the close');
    expect(v.provisional).toBe(false);
    expect(v.headline).toEqual({ value: 41262.18, change: 524.14, pct: 1.2866, when: 'on Wed Nov 11', live: false });
    expect(v.figures).toEqual({ change: '+$524', pct: '+1.29%', tone: 'up', cash: '$603', pending: '$250', margin: '$1,500' });
    expect(v.liveWords).toBeNull();
  });

  it('keeps the first sentence of the words and marks a provisional day', () => {
    const v = asOfView({ ...FINAL, provisional: true, status: 'provisional', words: 'Wed Nov 11, 5:21 PM ET. Provisional until official closes land this evening; fund prices can follow in the morning.' }, NOW);
    expect(v.text).toBe('As of Wed Nov 11, 5:21 PM ET');
    expect(v.provisional).toBe(true);
    expect(v.title).toContain('Provisional until official closes land this evening; fund prices can follow in the morning.');
  });

  it('prints the funds still waiting on a close, in the desk’s words, and drops them once live quotes lead', () => {
    const waiting = { ...FINAL, provisional: true, status: 'provisional', words: 'Wed Nov 11, at the close. Waiting on the official close for FXAIX and FTIHX; the day is restated when it lands.', prices: { official: 3, quoted: 0, carried: [], waiting: ['FXAIX', 'FTIHX'] } };
    const v = asOfView(waiting, NOW);
    expect(v.text).toBe('As of Wed Nov 11, at the close');
    expect(v.provisional).toBe(true);
    expect(v.waiting).toBe('Waiting on the official close for FXAIX and FTIHX; the day is restated when it lands.');
    expect(asOfView(FINAL, NOW).waiting).toBeNull();
    expect(asOfView({ ...FINAL, prices: { official: 5, quoted: 0, carried: [], waiting: [] } }, NOW).waiting).toBeNull();
    expect(asOfView({ ...waiting, live: LIVE }, NOW).waiting).toBeNull();
    expect(asOfView({ ...waiting, words: 'Wed Nov 11, at the close.' }, NOW).waiting).toBeNull();
  });

  it('leads with the live day and its change when quotes are newer than the book', () => {
    const v = asOfView({ ...FINAL, live: LIVE }, NOW);
    expect(v.headline).toEqual({ value: 41010.77, change: -251.41, pct: -0.6093, when: 'today', live: true });
    expect(v.liveWords).toBe('Live, Thu Nov 12, 2:15 PM ET');
    expect(v.text).toBe('As of Thu Nov 12, 2:15 PM ET');
    expect(v.ticking).toBe(true);
    expect(v.shown).toBe('2026-11-12');
    expect(v.day).toBe('2026-11-11');
    expect(v.books).toBe('Book as of Wed Nov 11, at the close');
    expect(v.figures).toEqual({ change: '−$251', pct: '−0.61%', tone: 'dn', cash: '$603', pending: '$250', margin: '$1,500' });
    const late = asOfView({ ...FINAL, behind: { sessions: 1, reason: 'Closing quotes are in for Thu Nov 12.' }, live: { ...LIVE, state: 'after', words: 'Thu Nov 12, last quotes 7:40 PM ET' } }, NOW);
    expect(late.text).toBe('As of Thu Nov 12, last quotes 7:40 PM ET');
    expect(late.ticking).toBe(false);
    expect(late.behind).toBeNull();
    expect(late.tone).toBe('');
    expect(late.title).toContain('Closing quotes are in for Thu Nov 12.');
    expect(asOfView({ ...FINAL, live: LIVE }, new Date('2026-11-13T15:00:00Z')).headline.when).toBe('on Thu Nov 12');
  });

  it('warns when the book is behind and says nothing before the first run', () => {
    const v = asOfView({ ...FINAL, behind: { sessions: 1, reason: 'No closing quotes for Thu Nov 12 yet.' } }, NOW);
    expect(v.tone).toBe('watch');
    expect(v.behind).toBe('No closing quotes for Thu Nov 12 yet.');
    expect(asOfView({ day: null, status: 'empty', numbers: {} }, NOW)).toBeNull();
    expect(asOfView(null)).toBeNull();
  });

  it('shows no borrowed money as none and falls back to the numbers day on an older desk', () => {
    expect(asOfView({ ...FINAL, numbers: { ...NUMBERS, margin_debit: 0 } }, NOW).figures.margin).toBe('none');
    const old = asOfFromMetrics('2026-11-10');
    expect(old.text).toBe('As of Tue Nov 10');
    expect(old.figures).toBeNull();
    expect(old.headline).toBeNull();
    expect(asOfFromMetrics(null)).toBeNull();
  });
});

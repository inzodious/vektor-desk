import { describe, expect, it } from 'vitest';
import { allSources, cleanSymbol, directionWord, eventWord, filingChip, coreFund, eventsOf, freshness, keyNumbers, overnightStart, rangeGeo, rangeLine, rateLines, rebase, sourceKind, triggersOf, upcomingOf, verdictOf } from './research.js';

describe('research helpers', () => {
  it('grades sources by where they come from', () => {
    expect(sourceKind({ url: 'https://www.sec.gov/edgar/search/' })).toBe('primary');
    expect(sourceKind({ url: 'https://fred.stlouisfed.org/series/DGS10' })).toBe('primary');
    expect(sourceKind({ url: 'https://example.com/press' })).toBe('web');
    expect(sourceKind({ url: 'note:2026-09-12', title: 'Your note' })).toBe('note');
    expect(sourceKind({ url: 'engine:plan.drift' })).toBe('primary');
  });

  it('reads verdicts and freshness', () => {
    expect(verdictOf({ dossier: { verdict: 'trim' } }).t).toBe('Trim to target');
    expect(verdictOf({ dossier: { verdict: 'moon' } })).toBeNull();
    const now = new Date('2026-11-09T12:00:00Z');
    expect(freshness('2026-11-09T06:00:00Z', now).t).toBe('Refreshed today');
    expect(freshness('2026-11-08T06:00:00Z', now).t).toBe('Refreshed yesterday');
    expect(freshness('2026-10-01T06:00:00Z', now)).toEqual({ t: 'Due for a refresh · 39 days old', tone: 'watch' });
  });

  it('splits what would change the call into triggers', () => {
    expect(triggersOf('A goes up.\nB goes down.')).toEqual(['A goes up.', 'B goes down.']);
    expect(triggersOf('- one; - two')).toEqual(['one', 'two']);
    expect(triggersOf('First thing. Second thing.')).toEqual(['First thing.', 'Second thing.']);
    expect(triggersOf(null)).toEqual([]);
  });

  it('places the range and today marker', () => {
    const g = rangeGeo({ low: 24, high: 35, now: 32 });
    expect(g.where).toBe('upper');
    expect(g.now).toBeGreaterThan(g.left);
    expect(g.now).toBeLessThan(g.left + g.width);
    expect(rangeGeo({ low: 5, high: 5 })).toBeNull();
    expect(rangeLine({ low: 2.4, high: 4.2, basis: 'price per share, $' }, 3.03)).toBe('Now $3.03: inside the range, lower half.');
    expect(rangeLine({ low: 24, high: 35, basis: 'forward P/E' })).toContain("isn't tracked");
    expect(rangeLine({ low: 24, high: 35, basis: 'forward P/E', now: 40 })).toBe('Now 40x: above the range.');
  });

  it('rebases two price series on shared days', () => {
    const r = rebase({ rows: [{ date: 'a', close: 10 }, { date: 'b', close: 12 }, { date: 'c', close: 11 }] }, { rows: [{ date: 'b', close: 50 }, { date: 'c', close: 55 }] });
    expect(r.x).toEqual(['b', 'c']);
    expect(r.a.map((v) => Math.round(v))).toEqual([100, 92]);
    expect(r.b.map((v) => Math.round(v))).toEqual([100, 110]);
    expect(rebase({ rows: [{ date: 'a', close: 2 }] }, null).a).toEqual([100]);
  });

  it('finds the core fund and key numbers', () => {
    const rows = [
      { metric_id: 'plan.target', scope: 'holding', scope_id: 'FTEC', value: 20 },
      { metric_id: 'plan.target', scope: 'holding', scope_id: 'FXAIX', value: 60 },
      { metric_id: 'sig.earnings_days', scope: 'holding', scope_id: 'ACME', window: 'now', value: 1, quality: 'ok' },
      { metric_id: 'sig.insider_net', scope: 'holding', scope_id: 'ACME', window: '90D', value: -1500, quality: 'ok' },
      { metric_id: 'risk.beta', scope: 'holding', scope_id: 'ACME', window: '63D', value: 2 },
    ];
    expect(coreFund(rows)).toBe('FXAIX');
    expect(keyNumbers(rows, 'ACME')).toEqual([
      { id: 'sig.earnings_days', t: 'Next earnings', v: 'In 1 day', quality: 'ok' },
      { id: 'sig.insider_net', t: 'Insiders, 90 days', v: '−$1,500 net', quality: 'ok' },
    ]);
  });

  it('turns research into dated events', () => {
    const ev = eventsOf(
      {
        filings: [{ form: '10-Q', filed: '2026-10-30', description: 'Q3', url: 'https://www.sec.gov/x' }],
        earnings: [
          { date: '2026-11-12', hour: 'amc', quarter: 3, year: 2026, eps_estimate: -0.14 },
          { date: '2026-07-30', quarter: 2, year: 2026, eps_estimate: 0.16, eps_actual: 0.19 },
        ],
        insiders: [
          { name: 'A', txn_date: '2026-10-17', code: 'S', change: -100, price: 3 },
          { name: 'B', txn_date: '2026-10-01', code: 'M', change: 50, price: 1 },
        ],
      },
      '2026-11-09',
    );
    expect(ev.map((e) => e.kind)).toEqual(['earnings_next', 'filing', 'insider', 'earnings']);
    expect(ev[0].detail).toBe('Q3 2026, after the close · EPS estimate −$0.14');
    expect(ev[2].title).toBe('A sold 100 shares');
    expect(ev[3].detail).toBe('EPS $0.19 against $0.16 expected');
    expect(upcomingOf(ev, '2026-11-09').map((e) => e.date)).toEqual(['2026-11-12']);
    expect(eventsOf(null, '2026-11-09')).toEqual([]);
  });

  it('collects sources across dossiers newest first', () => {
    const out = allSources([
      { symbol: 'A', dossier: { sources: [{ url: 'https://example.com', title: 'w', date: '2026-11-01' }] } },
      { symbol: 'B', dossier: { sources: [{ url: 'https://www.sec.gov/y', title: 'p', date: '2026-11-03' }] } },
    ]);
    expect(out.map((s) => [s.symbol, s.kind])).toEqual([
      ['B', 'primary'],
      ['A', 'web'],
    ]);
  });

  it('lines up yields on days every series has', () => {
    const r = rateLines({ DGS3MO: [{ date: 'a', value: 4 }, { date: 'b', value: 4.1 }], DGS2: [{ date: 'b', value: 3.9 }], DGS10: [{ date: 'b', value: 4.2 }] });
    expect(r.x).toEqual(['b']);
    expect(r.series.map((s) => s.values[0])).toEqual([4.1, 3.9, 4.2]);
  });

  it('reads the overnight window and cleans symbols', () => {
    expect(overnightStart({ profile: { usage: { overnight_window: '02:30-05:00' } } })).toBe('2:30 AM');
    expect(overnightStart(null)).toBe('1:00 AM');
    expect(cleanSymbol(' brk.b ')).toBe('BRK.B');
    expect(cleanSymbol('1ABC')).toBeNull();
    expect(cleanSymbol('')).toBeNull();
  });
});

describe('filing chip', () => {
  it('reads the newest scored filing in plain words', () => {
    const f = filingChip({ filing_signals: [{ form: '8-K', direction: 1, confidence: 0.72, event_type: 'merger_acquisition', lane_open: true }, { form: '4', direction: -1 }] });
    expect(f.dir).toEqual({ t: 'Leans good', tone: 'ok' });
    expect(f.sure).toBe('72% sure');
    expect(f.event).toBe('Merger or acquisition');
    expect(f.form).toBe('Current report');
    expect(f.more).toBe(1);
    expect(f.lane_open).toBe(true);
  });

  it('stays quiet without scored filings', () => {
    expect(filingChip(null)).toBeNull();
    expect(filingChip({ filing_signals: [] })).toBeNull();
    expect(filingChip({ filings: [] })).toBeNull();
  });

  it('clamps direction and words events', () => {
    expect(directionWord(-2).t).toBe('Reads clearly bad');
    expect(directionWord(5).t).toBe('Reads clearly good');
    expect(directionWord(0).tone).toBe('');
    expect(eventWord('insider_sell')).toBe('Insider sell');
    expect(eventWord(null)).toBeNull();
  });
});

import { describe, expect, it } from 'vitest';
import { latestScore } from './decisions.js';
import { baseRateText, calibrationPoints, chipOf, decisionRows, fundingItems, groupItems, groupLabel, intervalGeo, patternValue, scoredCount, seasonGrid, setupItems, totalRecord } from './flight.js';

describe('flight record', () => {
  const desks = [
    { desk: 'plan_keeper', record_usd: -114.5, scored_90: 33 },
    { desk: 'scout', record_usd: 394, scored_90: 10 },
  ];

  it('totals desk records and scored calls', () => {
    expect(totalRecord(desks)).toBeCloseTo(279.5);
    expect(totalRecord([])).toBeNull();
    expect(scoredCount(desks)).toBe(43);
  });

  it('names chips and groups', () => {
    expect(chipOf('keep').t).toBe('Keep it on');
    expect(chipOf('odd_one').t).toBe('odd one');
    expect(groupLabel('origin', 'plan_keeper')).toBe('Plan keeper');
    expect(groupLabel('path', 'override')).toBe('Override');
    expect(groupLabel('kind', 'deposit_route')).toMatch(/deposit/i);
  });

  it('picks groups for one split and window', () => {
    const groups = [
      { by: 'kind', group: 'trim', window: '90D', n: 4, total_usd: -20, mean_usd: -5 },
      { by: 'kind', group: 'trim', window: '30D', n: 6, total_usd: 10, mean_usd: 1.7 },
      { by: 'origin', group: 'risk', window: '90D', n: 2, total_usd: 50, mean_usd: 25 },
    ];
    expect(groupItems(groups, 'kind', '90D')).toMatchObject([{ label: 'Trim', value: -20, hint: '4 scored · mean -5' }]);
  });

  it('places an interval around zero', () => {
    const g = intervalGeo(-10, 30, 5);
    expect(g.zero).toBe(25);
    expect(g.lo).toBe(0);
    expect(g.hi).toBe(100);
    expect(g.straddles).toBe(true);
    expect(intervalGeo(null, null, null)).toBeNull();
    expect(intervalGeo(5, 15, 10).straddles).toBe(false);
  });

  it('keeps calibration bins with calls', () => {
    expect(calibrationPoints({ bins: [{ low: 0, high: 0.2, n: 0, said: 0.1, happened: 0 }, { low: 0.6, high: 0.8, n: 5, said: 0.7, happened: 0.6 }] })).toEqual([{ said: 0.7, happened: 0.6, n: 5, low: 0.6, high: 0.8 }]);
    expect(calibrationPoints(null)).toEqual([]);
  });

  it('lists scored calls newest first', () => {
    const rows = decisionRows([
      { id: 'a', origin: 'risk', kind: 'hold_off', symbol: 'X', taken: true, start: '2026-01-02', amount_usd: 10, scores: { '30D': { usd: 2 } } },
      { id: 'b', origin: 'scout', kind: 'buy', symbol: 'Y', taken: false, start: '2026-03-02', scores: {} },
      { id: 'c', origin: 'scout', kind: 'buy', symbol: 'Z', taken: false, start: null, scores: {} },
    ]);
    expect(rows.map((r) => r.id)).toEqual(['b', 'a']);
    expect(rows[1]).toMatchObject({ s30: 2, s90: null, amount: 10 });
    expect(decisionRows([{ id: 'a', origin: 'risk', start: '2026-01-02' }], { origin: 'scout' })).toEqual([]);
  });

  it('takes the longest score a journal row has', () => {
    expect(latestScore({ scores: { '30D': 5, '90D': { usd: -3 } } })).toEqual({ w: '90D', t: '90 days', v: -3 });
    expect(latestScore({ scores: {} })).toBeNull();
  });
});

describe('patterns', () => {
  it('formats each kind of reading', () => {
    expect(patternValue({ id: 'pat.mkt_drawdown', unit: 'pct', value: -19.43 })).toBe('−19.4%');
    expect(patternValue({ id: 'pat.vix_pctl', label: 'VIX percentile over 10 years', unit: 'pct', value: 56.2 })).toBe('56th pctl');
    expect(patternValue({ id: 'pat.hy_pctl', label: 'spread percentile', unit: 'pct', value: 12.4 })).toBe('12th pctl');
    expect(patternValue({ id: 'pat.range_52w', unit: 'pct', value: 66.3 })).toBe('66% up the range');
    expect(patternValue({ id: 'pat.curve_10y3m', unit: 'pts', value: -0.12 })).toBe('−0.12 pts');
    expect(patternValue({ value: null })).toBe('—');
  });

  it('says when history is too short for a base rate', () => {
    expect(baseRateText({ followed_by: 'higher 12 months later', n: 0 })).toMatch(/^Not enough history/);
    expect(baseRateText({ followed_by: 'higher', n: 3, base_rate: null, forward_mean_pct: 12.36 })).toBe('3 past cases, averaging +12.4%. Too few for a rate.');
    expect(baseRateText({ followed_by: 'higher a year later', n: 40, base_rate: 0.725, ci_low: 0.6, ci_high: 0.83 })).toBe('73% of 40 past cases were higher a year later (60 to 83%).');
    expect(baseRateText({ followed_by: null })).toBeNull();
  });

  it('lays seasonality out by calendar month', () => {
    const g = seasonGrid({ A: [{ month: 1, mean_pct: 2 }, { month: 3, mean_pct: -1 }], B: [] });
    expect(g.rows).toEqual(['A']);
    expect(g.cols).toHaveLength(12);
    expect(g.values[0].slice(0, 3)).toEqual([0.02, null, -0.01]);
  });

  it('names habit groups', () => {
    expect(setupItems({ after_rise: { n: 4, mean_usd: -63.7, total_usd: -254.6 } })).toEqual([{ label: 'After a 5% rise', value: -63.7, hint: '4 buys · total -255' }]);
    expect(fundingItems({ off_schedule: { n: 6, mean_usd: -53 } })).toEqual([{ label: 'Off schedule', value: -53, hint: '6 buys' }]);
  });
});

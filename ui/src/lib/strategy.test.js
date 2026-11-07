import { describe, expect, it } from 'vitest';
import { costItems, factorItems, foldItems, horizonRows, mixText, paperProgress, paperSummary, paramText, regimeItems, ruleVariants, sensitivityItems, signedPts, specLines, splitStrategies, stageCounts, statusOf, verdictLamps, verdictOf } from './strategy.js';

describe('words', () => {
  it('names statuses and verdicts, with a fallback', () => {
    expect(statusOf('paper').t).toBe('Paper trading');
    expect(statusOf('something_new').t).toBe('something new');
    expect(verdictOf('no_clear_edge').t).toBe('No clear edge');
    expect(verdictOf(null).t).toBe('No verdict yet');
  });

  it('writes settings in words', () => {
    expect(paramText({ band_pts: 3 })).toBe('3 pt band');
    expect(paramText({ borrow_pct: 5, dip_pct: 20 })).toBe('borrow 5%, 20% dip');
    expect(paramText({})).toBe('Default settings');
    expect(paramText({ odd_knob: 2 })).toBe('odd knob 2');
  });

  it('signs points without a negative zero', () => {
    expect(signedPts(1.234)).toBe('+1.2 pts');
    expect(signedPts(-0.04)).toBe('0.0 pts');
    expect(signedPts(-2)).toBe('−2.0 pts');
    expect(signedPts(null)).toBe('—');
  });

  it('turns a frozen spec into plain lines', () => {
    const lines = specLines({
      universe: { type: 'fund_list', set: 'sector_etfs' },
      signals: [{ metric_id: 'ret', window: '{lookback}d', transform: 'rank' }],
      entry: 'top {top_n} by rank',
      exit: { hold_rank: 5 },
      rebalance: 'monthly',
      sizing: 'inverse_vol',
      params: { top_n: { min: 2, max: 4, default: 3 }, lookback: [126, 252] },
      horizons: [3, 5],
    });
    expect(Object.fromEntries(lines.map((l) => [l.k, l.v]))).toEqual({
      'Picks from': 'US sector ETFs',
      Signal: 'return over 126 days ranked high to low',
      Buys: 'top 3 by rank',
      Sells: 'keeps a holding while it ranks in the top 5',
      Trades: 'monthly, inverse vol weights',
      Horizons: '3 years, 5 years',
    });
    expect(specLines({ entry: { top_n: 'param:top_n' }, params: { top_n: [4, 5] } })[0].v).toBe('top 4 by rank');
    expect(specLines(null)).toEqual([]);
  });
});

describe('list', () => {
  const list = [
    { id: 'a', status: 'failed', registered_at: '2026-01-01' },
    { id: 'b', status: 'lab', registered_at: '2026-01-02' },
    { id: 'c', status: 'paper', registered_at: '2026-01-01' },
    { id: 'd', status: 'lab', registered_at: '2026-01-05' },
  ];

  it('counts each stage and the ones off the track', () => {
    expect(stageCounts(list)).toEqual({ draft: 0, lab: 2, paper: 1, eligible: 0, off: 1 });
  });

  it('sorts paper first, then newest within a stage', () => {
    expect(splitStrategies({ strategies: list }).map((s) => s.id)).toEqual(['c', 'd', 'b', 'a']);
    expect(splitStrategies(null)).toEqual([]);
  });

  it('measures paper progress against six months', () => {
    expect(paperProgress({ days: 91 })).toEqual({ days: 91, share: 0.5, left: 91, done: false });
    expect(paperProgress({ days: 200 }).done).toBe(true);
    expect(paperProgress(null)).toBeNull();
  });

  it('reads the paper summary string or object', () => {
    expect(paperSummary({ summary: '{"trades": 4}' })).toEqual({ trades: 4 });
    expect(paperSummary({ summary: { trades: 2 } })).toEqual({ trades: 2 });
    expect(paperSummary({ summary: 'nope' })).toBeNull();
  });
});

describe('tear sheet', () => {
  it('lights a lamp for each verdict bar', () => {
    const lamps = verdictLamps({ excess_interval: true, pbo: false, factor: null });
    expect(lamps.map((l) => [l.id, l.status, l.short])).toEqual([
      ['excess_interval', 'ok', 'Clear'],
      ['pbo', 'act', 'Missed'],
      ['factor', 'watch', 'Not run'],
    ]);
    expect(verdictLamps(null)).toEqual([]);
  });

  it('labels folds by test year', () => {
    const items = foldItems([{ test_window: ['2015-01-02', '2016-01-02'], test: { start: '2015-01-02', excess_vs_bench_pts: 1.9 }, params: { top_n: 3 } }]);
    expect(items).toEqual([{ label: '2015', value: 1.9, hint: 'top 3' }]);
  });

  it('sorts horizons and keeps the share ahead', () => {
    const rows = horizonRows([
      { years: 5, starts: 48, mean_pts: 1, p5_pts: -1, p95_pts: 3, share_positive: 0.6 },
      { years: 3, starts: 72, mean_pts: 2, p5_pts: -2, p95_pts: 4, share_better: 0.4 },
    ]);
    expect(rows.map((r) => [r.years, r.share])).toEqual([
      [3, 0.4],
      [5, 0.6],
    ]);
  });

  it('turns analyses into bars', () => {
    expect(sensitivityItems({ top_n: { 4: 0.9, 2: 0.6 } })).toEqual([
      {
        param: 'top_n',
        items: [
          { label: 'top 2', value: 0.6 },
          { label: 'top 4', value: 0.9 },
        ],
      },
    ]);
    expect(regimeItems({ bull: { days: 10, excess_pts: 2 }, bear: { days: 5, excess_pts: null } })).toEqual([{ label: 'Rising markets', value: 2, hint: '10 days' }]);
    expect(costItems([{ cost_x: 1, excess_vs_bench_pts: 1 }, { cost_x: 2, excess_vs_bench_pts: 0.5 }]).map((c) => c.label)).toEqual(['Lab costs', '2x costs']);
    expect(factorItems({ mkt_rf: { beta: 0.9, t: 12 } })).toEqual([{ label: 'Market', value: 0.9, hint: 't 12' }]);
  });
});

describe('rule tests', () => {
  it('lists every setting and marks the best', () => {
    const rows = ruleVariants({
      best: { band_pts: 3 },
      variants: [
        { params: { band_pts: 3 }, full_diff_pts: 0.5, holdout_diff_pts: 0, verdict: 'helps', full: { after_liquidation: 100, taxes: 2, interest: 0, margin_calls: 0 }, horizons: [] },
        { params: { band_pts: 5 }, full_diff_pts: -0.4, holdout_diff_pts: 0.1, verdict: 'no_clear_edge', full: { end_value: 90 } },
      ],
    });
    expect(rows.map((r) => [r.label, r.best, r.end])).toEqual([
      ['3 pt band', true, 100],
      ['5 pt band', false, 90],
    ]);
    expect(ruleVariants(null)).toEqual([]);
  });

  it('writes the mix biggest first', () => {
    expect(mixText({ BND: 0.2, FXAIX: 0.8 })).toBe('FXAIX 80% · BND 20%');
  });
});

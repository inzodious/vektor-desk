import { describe, expect, it } from 'vitest';
import { factorBars, fiChart, fiHeadline, fiRange, fiState, holdingGrid, leanSummary, leanWord, monthYear, onTimeText, shortUsd, yearTicks } from './fi.js';

const view = {
  as_of: '2026-11-06',
  status: 'ok',
  fi_number: 700000,
  target_date: '2051-03-20',
  start_value: 16000,
  months: 360,
  fi_date: { p10: '2048-09-06', p50: '2058-02-06', p90: null },
  reached_share: 0.63,
  on_time_share: 0.19,
  lines: Array.from({ length: 30 }, (_, i) => ({ year: i + 1, date: `${2027 + i}-11-06`, p10: 1000 * i, p50: 2000 * i, p90: 3000 * i })),
};

describe('FI path', () => {
  it('formats dates and short dollars', () => {
    expect(monthYear('2058-02-06')).toBe('Feb 2058');
    expect(monthYear(null)).toBeNull();
    expect(shortUsd(700000)).toBe('$700K');
    expect(shortUsd(1250000)).toBe('$1.25M');
    expect(shortUsd(2000000)).toBe('$2M');
    expect(shortUsd(null)).toBe('—');
  });

  it('tells the three states apart', () => {
    expect(fiState(null)).toBe('no_goal');
    expect(fiState({ status: 'not_ready', note: 'x' })).toBe('no_goal');
    expect(fiState({ status: 'not_ready', fi_number: 1 })).toBe('no_history');
    expect(fiState(view)).toBe('ok');
  });

  it('builds the fan from today with the target marked', () => {
    const c = fiChart(view);
    expect(c.x[0]).toBe('2026-11-06');
    expect(c.x).toHaveLength(31);
    expect(c.series.map((s) => s.name)).toEqual(['Fast 10%', 'Middle', 'Slow 10%']);
    expect(c.series[1].values[0]).toBe(16000);
    expect(c.x[c.target] >= '2051-03-20').toBe(true);
    expect(c.x[c.target - 1] < '2051-03-20').toBe(true);
    expect(fiChart({ status: 'not_ready' })).toBeNull();
  });

  it('labels every fifth year', () => {
    const c = fiChart(view);
    expect(yearTicks(c.x, false).map((t) => t.label)).toEqual(['2031', '2036', '2041', '2046', '2051', '2056']);
    expect(yearTicks(c.x, true).map((t) => t.label)).toEqual(['2036', '2046', '2056']);
  });

  it('heads with the middle date or says it is past the horizon', () => {
    expect(fiHeadline(view)).toEqual({ big: 'Feb 2058', line: 'on the middle path' });
    expect(fiHeadline({ ...view, fi_date: {} })).toEqual({ big: 'Past the horizon', line: '63% of paths get there within 30 years' });
    expect(fiHeadline({ ...view, fi_date: {}, reached_share: 0 }).big).toBe('Not in view yet');
    expect(fiRange(view)).toEqual({ fast: 'by Sep 2048', slow: 'beyond 30 years' });
  });

  it('words the on-time odds kindly', () => {
    expect(onTimeText(0.95)).toMatch(/Nearly every/);
    expect(onTimeText(0.5)).toMatch(/coin flip/);
    expect(onTimeText(0.19)).toMatch(/^Some paths/);
    expect(onTimeText(0.05)).toMatch(/^Few paths/);
    expect(onTimeText(null)).toBeNull();
  });
});

describe('factor exposure', () => {
  it('words each lean', () => {
    expect(leanWord('mkt_rf', 1.2)).toBe('swings more than the market');
    expect(leanWord('mkt_rf', 1)).toBe('moves with the market');
    expect(leanWord('hml', -0.4)).toBe('leans to growth');
    expect(leanWord('smb', 0.05)).toBe('no lean');
    expect(leanWord('mom', null)).toBeNull();
  });

  it('bars the portfolio in factor order', () => {
    expect(factorBars({ mom: 0.3, mkt_rf: 0.9 })).toEqual([
      { label: 'Market', value: 0.9, hint: 'swings less than the market' },
      { label: 'Momentum', value: 0.3, hint: 'leans to recent winners' },
    ]);
    expect(factorBars(undefined)).toEqual([]);
  });

  it('sums up the two biggest leans past the market', () => {
    expect(leanSummary({ mkt_rf: 1, smb: 0.05, hml: -0.5, mom: 0.2, rmw: 0.1 })).toBe('Leans to growth and recent winners');
    expect(leanSummary({ mkt_rf: 0.8, hml: 0.1 })).toBe('Mostly the market, no strong lean');
  });

  it('grids holdings by weight', () => {
    const g = holdingGrid({ BND: { weight: 0.1, loadings: { mkt_rf: 0 } }, FXAIX: { weight: 0.6, loadings: { mkt_rf: 1, smb: 0.1 } } });
    expect(g.rows).toEqual(['FXAIX', 'BND']);
    expect(g.cols[0]).toBe('Market');
    expect(g.values[0].slice(0, 3)).toEqual([1, 0.1, null]);
  });
});

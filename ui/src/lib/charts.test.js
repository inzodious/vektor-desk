import { describe, expect, it } from 'vitest';
import { dayLabel, extent, monthTicks, niceTicks, periodStart, sparkPath } from './charts.js';

describe('charts', () => {
  it('makes round ticks that cover the data', () => {
    expect(niceTicks(3, 97, 4)).toEqual([0, 25, 50, 75, 100]);
    const t = niceTicks(19100, 19620, 4);
    expect(t[0]).toBeLessThanOrEqual(19100);
    expect(t[t.length - 1]).toBeGreaterThanOrEqual(19620);
    expect(niceTicks(5, 5).length).toBeGreaterThan(1);
  });

  it('finds the extent across series and reference lines', () => {
    expect(extent([{ values: [3, null, 9] }, { values: [4] }], [{ y: 1 }])).toEqual([1, 9]);
  });

  it('labels month starts and years', () => {
    const days = ['2025-12-30', '2025-12-31', '2026-01-02', '2026-01-05', '2026-02-02'];
    expect(monthTicks(days)).toEqual([
      { i: 2, label: '2026' },
      { i: 4, label: 'Feb' },
    ]);
    expect(dayLabel('2026-11-06', true)).toBe('Nov 6, 2026');
    expect(dayLabel('2026-11-11T01:20:00Z')).toBe('Nov 10');
    expect(dayLabel('2026-11-10T22:20:00+00:00', true)).toBe('Nov 10, 2026');
    expect(dayLabel(undefined)).toBe('');
    expect(dayLabel('soon')).toBe('');
  });

  it('turns a period into a start date', () => {
    expect(periodStart('YTD', '2026-11-06')).toBe('2026-01-01');
    expect(periodStart('1M', '2026-11-06')).toBe('2026-10-06');
    expect(periodStart('MAX', '2026-11-06')).toBeNull();
  });

  it('draws a spark path or nothing', () => {
    expect(sparkPath([1, 2, 3], 120, 26).d.startsWith('M0.0')).toBe(true);
    expect(sparkPath([1], 120, 26).d).toBe('');
  });
});

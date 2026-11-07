import { describe, expect, it } from 'vitest';
import { ago, count, etStamp, pct, plainDate, plural, pts, px, usd } from './format.js';

describe('format', () => {
  it('formats dollars with a true minus and optional sign', () => {
    expect(usd(1234.5)).toBe('$1,235');
    expect(usd(-12.345, { cents: true })).toBe('−$12.35');
    expect(usd(40, { sign: true })).toBe('+$40');
    expect(usd(null)).toBe('—');
    expect(usd(-0.2, { sign: true })).toBe('$0');
    expect(pct(-0.00001, 2, true)).toBe('0.00%');
  });

  it('formats percents and points', () => {
    expect(pct(0.0712)).toBe('7.1%');
    expect(pct(-0.004, 2, true)).toBe('−0.40%');
    expect(pts(0.044)).toBe('+4.4 pts');
  });

  it('formats prices and counts', () => {
    expect(px(31.2)).toBe('31.20');
    expect(px(5432.1)).toBe('5,432');
    expect(count(1288)).toBe('1,288');
    expect(plural(1, 'table')).toBe('1 table');
    expect(plural(15, 'table')).toBe('15 tables');
  });

  it('shows ages in plain words', () => {
    expect(ago(0.5)).toBe('30 min ago');
    expect(ago(1)).toBe('1 hour ago');
    expect(ago(3.7)).toBe('3.7 hours ago');
    expect(ago(72)).toBe('3 days ago');
    expect(ago(null)).toBeNull();
  });

  it('stamps times in Eastern', () => {
    expect(etStamp('2026-11-09T13:00:04+00:00')).toBe('Nov 9, 8:00 AM ET');
    expect(etStamp('2026-07-09T13:00:04+00:00')).toBe('Jul 9, 9:00 AM ET');
    expect(etStamp(null)).toBeNull();
    expect(plainDate('2027-11-03')).toBe('Nov 3, 2027');
  });
});

import { describe, expect, it } from 'vitest';
import d from '../fixtures/engine.discounts.json';
import { discountHead, headLine, listWord, reasonText, valuationText, verdictWord } from './discounts.js';

describe('discount days', () => {
  it('words why a name is on sale', () => {
    expect(reasonText(d.rows[0])).toBe('First close 20% under its 52-week high');
    expect(reasonText(d.rows[1])).toBe('−3.2% today, 2.4× its usual swing');
  });

  it('words valuation against its own history', () => {
    expect(valuationText({ metric: 'pe_annual', value: 29.4, pctile_own: 0.22 })).toBe('P/E 29.4, cheaper than 78% of its last 5 years');
    expect(valuationText({ metric: 'price_vs_5y_avg', value: 1.18, pctile_own: 0.71 })).toBe('118% of its 5-year average price, pricier than 71% of its last 5 years');
    expect(valuationText(null)).toBeNull();
  });

  it('sums up the scan', () => {
    expect(discountHead(d)).toEqual({ total: 5, held: 2, cases: 3, waiting: 2, buys: 1 });
    expect(headLine(d)).toBe('5 names on sale · 2 you hold · 1 with a case to buy · 2 still being read');
    expect(headLine({ rows: [] })).toBeNull();
    expect(listWord('quality').t).toBe('Quality list');
    expect(verdictWord({ verdict: 'avoid' })).toEqual({ t: 'Avoid', tone: 'watch' });
    expect(verdictWord(null)).toBeNull();
  });
});

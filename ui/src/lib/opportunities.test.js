import { describe, expect, it } from 'vitest';
import list from '../fixtures/opportunities.json';
import debit from '../fixtures/opportunities.evening.json';
import fresh from '../fixtures/opportunities.fresh.json';
import { becomesBuy, evidenceLines } from './opportunities.js';

const row = (d, symbol) => d.rows.find((r) => r.symbol === symbol);

describe('what would make a could a buy', () => {
  it('prints the desk’s line on a could row and nothing anywhere else', () => {
    expect(becomesBuy(row(list, 'VXUS'))).toBe('No written case yet. It is next in line tonight; the desk writes up to 6 a night.');
    expect(becomesBuy(row(list, 'NOVA'))).toMatch(/^Skeptic disagreed with Scout’s idea\./);
    expect(becomesBuy(row(list, 'QUAL'))).toBeNull();
    expect(becomesBuy(row(list, 'ACME'))).toBeNull();
    expect(becomesBuy(row(debit, 'NOVA'))).toBeNull();
    expect(becomesBuy({ group: 'buy', becomes_buy: 'A stray line.' })).toBeNull();
    expect(becomesBuy({ group: 'could', becomes_buy: '{"kind":"reread"}' })).toBeNull();
    expect(becomesBuy({ becomes_buy: ' An older desk with no groups. ' })).toBe('An older desk with no groups.');
    expect(becomesBuy(null)).toBeNull();
  });
});

describe('the lab’s sentence for the page’s rule', () => {
  it('quotes each tested row as given, whichever way it came out', () => {
    expect(evidenceLines(list)).toEqual([
      { key: 'lib-stock-dip-hold', title: 'Buy a stock dip and hold', line: 'Ahead by 1.2 points a year out of sample, but inside the luck band for 212 tries.', outdated: false },
      { key: 'lib-average-down', title: 'Average down on the way', line: 'Behind by 0.8 points a year out of sample.', outdated: false },
    ]);
  });

  it('is empty until the lab has tested it, and skips rows with no sentence', () => {
    expect(evidenceLines(fresh)).toEqual([]);
    expect(evidenceLines({})).toEqual([]);
    expect(evidenceLines({ evidence: [null, { id: 'a', line: null }, { title: 'T', line: 'Fine.', outdated: 1 }] })).toEqual([{ key: 'e0', title: 'T', line: 'Fine.', outdated: true }]);
  });
});

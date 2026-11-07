import { describe, expect, it } from 'vitest';
import { accountLabel, groupLive, priceStatus } from './context.js';
import live from '../fixtures/live.json';
import closed from '../fixtures/live.closed.json';
import stale from '../fixtures/live.stale.json';
import { clockState } from '../lib/clock.js';

describe('live grouping', () => {
  it('merges accounts per symbol and pulls cash out', () => {
    const { symbols, cash } = groupLive(live.rows);
    const ftec = symbols.find((s) => s.symbol === 'FTEC');
    expect(ftec.accounts).toHaveLength(2);
    expect(ftec.value).toBeCloseTo(live.rows.filter((r) => r.symbol === 'FTEC').reduce((a, r) => a + r.value, 0));
    expect(symbols.some((s) => s.symbol === 'SPAXX')).toBe(false);
    expect(cash).toBeCloseTo(live.rows.filter((r) => r.source === 'cash').reduce((a, r) => a + r.value, 0));
    expect(cash).toBeGreaterThan(0);
    expect(symbols[0].value).toBeGreaterThanOrEqual(symbols[1].value);
  });

  it('names accounts plainly', () => {
    expect(accountLabel('individual-0001')).toBe('Individual');
    expect(accountLabel('hsa-0002')).toBe('HSA');
    expect(accountLabel('401k-9')).toBe('401(k)');
    expect(accountLabel('crypto')).toBe('Crypto');
  });

  it('labels price freshness', () => {
    const row = (src) => ({ source: src });
    expect(priceStatus(live, row('finnhub')).text).toBe('Live');
    expect(priceStatus(stale, row('finnhub')).text).toBe('Quotes delayed');
    expect(priceStatus(closed, row('holdings')).text).toBe('Close Nov 6');
  });
});

describe('clock with the live feed', () => {
  const monday = new Date('2026-11-09T16:42:00Z');
  it('shows live when quotes are fresh', () => {
    expect(clockState(monday, live)).toMatchObject({ state: 'open', feed: 'live' });
  });
  it('shows delayed when quotes are stale', () => {
    expect(clockState(monday, stale)).toMatchObject({ state: 'open', feed: 'delayed', label: 'Quotes delayed' });
  });
  it('falls back to the local clock when the server day differs', () => {
    expect(clockState(new Date('2026-11-07T16:00:00Z'), live)).toMatchObject({ state: 'closed', feed: 'off' });
  });
});

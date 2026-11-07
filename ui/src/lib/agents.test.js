import { describe, expect, it } from 'vitest';
import { briefLines, briefTone, usageShare, whenLabel } from './agents.js';
import { mergeWindows, windowLine } from './tax.js';
import brief from '../fixtures/agents.brief.json';
import wash from '../fixtures/engine.wash.json';

describe('brief', () => {
  it('splits the summary into toned lines with a bold lead', () => {
    const lines = briefLines(brief.summary);
    expect(lines.length).toBeGreaterThanOrEqual(3);
    expect(lines.length).toBeLessThanOrEqual(5);
    expect(lines[0].tone).toBe('watch');
    expect(lines[lines.length - 1].tone).toBe('ok');
    expect(lines[0].lead.endsWith('.')).toBe(true);
  });

  it('strips bullets and blank lines', () => {
    expect(briefLines('- One thing.\n\n* Two things.').map((l) => l.lead)).toEqual(['One thing.', 'Two things.']);
    expect(briefLines(null)).toEqual([]);
  });

  it('reads tone from plain words', () => {
    expect(briefTone('Margin costs $12 a month.')).toBe('watch');
    expect(briefTone('All 3 rules hold.')).toBe('ok');
    expect(briefTone('$500 lands Tuesday.')).toBe('info');
  });
});

describe('crew', () => {
  it('labels run times relative to today in Eastern time', () => {
    const now = new Date('2026-11-09T16:42:00Z');
    expect(whenLabel('2026-11-09T22:30:00Z', now)).toBe('Today 5:30 PM');
    expect(whenLabel('2026-11-10T07:00:00Z', now)).toBe('Tomorrow 2:00 AM');
    expect(whenLabel('2026-11-06T22:30:00Z', now)).toBe('Fri 5:30 PM');
    expect(whenLabel('2026-12-06T08:00:00Z', now)).toBe('Dec 6, 3:00 AM');
  });

  it('caps the usage meter at full', () => {
    expect(usageShare({ runs: 3, cap: 6 })).toBe(0.5);
    expect(usageShare({ runs: 9, cap: 6 })).toBe(1);
    expect(usageShare({ runs: 1, cap: 0 })).toBe(0);
  });
});

describe('wash windows', () => {
  it('merges accounts per symbol and kind', () => {
    const rows = mergeWindows(wash.windows);
    expect(rows.length).toBe(new Set(wash.windows.map((w) => `${w.symbol}|${w.kind}`)).size);
    const two = rows.find((r) => r.accounts.length > 1);
    expect(two.amount).toBeCloseTo(wash.windows.filter((w) => w.symbol === two.symbol && w.kind === two.kind).reduce((a, w) => a + w.amount, 0));
  });

  it('says what a window means', () => {
    expect(windowLine({ symbol: 'X', kind: 'loss_sale', date: '2026-11-02', clears: '2026-12-03' })).toMatch(/Buying it back before Dec 3/);
    expect(windowLine({ symbol: 'X', kind: 'recent_buy', date: '2026-11-02', clears: '2026-12-03' })).toMatch(/wash sale/);
  });
});

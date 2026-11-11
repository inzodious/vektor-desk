import { describe, expect, it } from 'vitest';
import { dueHead, dueRows, movers } from './bridge.js';

const ids = (n, p) => Array.from({ length: n }, (_, i) => `${p}${i + 1}`);

describe('dueRows', () => {
  it('keeps the card to four rows and leaves room for plan steps', () => {
    const d = dueRows(ids(5, 'q'), ids(3, 's'));
    expect(d.queue).toEqual(['q1', 'q2']);
    expect(d.plan).toEqual(['s1', 's2']);
    expect(d.moreQueue).toBe(3);
    expect(d.moreSteps).toBe(1);
  });

  it('gives spare rows to whichever list has more', () => {
    expect(dueRows(ids(6, 'q'), []).queue).toHaveLength(4);
    expect(dueRows(ids(1, 'q'), ids(6, 's')).plan).toHaveLength(3);
    expect(dueRows([], ids(6, 's')).plan).toHaveLength(4);
  });

  it('handles nothing due', () => {
    expect(dueRows()).toEqual({ queue: [], plan: [], moreQueue: 0, moreSteps: 0 });
  });
});

describe('movers', () => {
  it('ranks by dollars moved and drops flat rows', () => {
    const rows = [
      { symbol: 'A', day_change: -2, change_pct: -0.01 },
      { symbol: 'B', day_change: 0.1, change_pct: 0.001 },
      { symbol: 'C', day_change: 78, change_pct: 0.02 },
      { symbol: 'D', day_change: -6, change_pct: null },
      { symbol: 'E', day_change: -9, change_pct: -0.004 },
      { symbol: 'F', day_change: 4, change_pct: 0.003 },
    ];
    expect(movers(rows).map((r) => r.symbol)).toEqual(['C', 'E', 'F']);
    expect(movers([])).toEqual([]);
  });
});

describe('dueHead', () => {
  it('names what is waiting', () => {
    expect(dueHead(0, 0)).toBe('Nothing due');
    expect(dueHead(4, 0)).toBe('4 to decide');
    expect(dueHead(0, 1)).toBe('1 plan step');
    expect(dueHead(2, 3)).toBe('2 to decide · 3 plan steps');
  });
});

import { describe, expect, it } from 'vitest';
import { expiresLabel, kindName, lampSummary, lampsOf, needsReason, oneLine, originName, scoreOf, journalPage } from './decisions.js';
import queue from '../fixtures/decisions.queue.json';

const byKind = (k) => queue.items.find((d) => d.kind === k);

describe('decisions helpers', () => {
  it('orders lamps the same way every time', () => {
    const lamps = lampsOf(byKind('buy'));
    expect(lamps.map((l) => l.id)).toEqual(['concentration', 'drift_after', 'funding', 'wash_sales', 'lots_tax', 'plan_rules']);
    expect(lampsOf({ preflight: null })).toBeNull();
  });

  it('summarises lamps in words, never colour alone', () => {
    expect(lampSummary(lampsOf(byKind('buy')))).toEqual({ tone: 'act', text: '2 need a reason' });
    expect(lampSummary(lampsOf(byKind('trim')))).toEqual({ tone: 'watch', text: '1 heads up' });
    expect(lampSummary(lampsOf(byKind('deposit_route'))).text).toBe('All clear');
  });

  it('asks for a reason only when Preflight lit up', () => {
    expect(needsReason(byKind('buy'))).toBe(true);
    expect(needsReason(byKind('trim'))).toBe(true);
    expect(needsReason(byKind('deposit_route'))).toBe(false);
  });

  it('names desks, kinds and dates plainly', () => {
    expect(originName('plan_keeper')).toBe('Plan keeper');
    expect(kindName('deposit_route')).toBe('Deposit route');
    expect(kindName('new_kind')).toBe('new kind');
    expect(expiresLabel('2026-11-16T21:00:00+00:00')).toBe('Expires Nov 16');
  });

  it('reads 30-day scores in either shape', () => {
    expect(scoreOf({ scores: { '30d': 12.5 } })).toBe(12.5);
    expect(scoreOf({ scores: { '30d': { value: -4 } } })).toBe(-4);
    expect(scoreOf({ scores: {} })).toBeNull();
    expect(scoreOf({ scores: { '30D': 7 } })).toBe(7);
    expect(scoreOf({ scores: { '90D': { usd: -3 } } }, '90D')).toBe(-3);
  });

  it('keeps the first sentence of a thesis', () => {
    expect(oneLine('First bit. Second bit.')).toBe('First bit.');
    expect(oneLine('x'.repeat(200))).toHaveLength(158);
  });
});

describe('journalPage', () => {
  const days = [
    { day: '2026-11-09', items: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] },
    { day: '2026-11-06', items: [{ id: 'd' }] },
    { day: '2026-11-05', items: [{ id: 'e' }, { id: 'f' }, { id: 'g' }] },
  ];

  it('cuts by entry and keeps the day stamps', () => {
    const p1 = journalPage(days, 1, 2);
    expect(p1.days).toEqual([{ day: '2026-11-09', items: [{ id: 'a' }, { id: 'b' }] }]);
    expect([p1.page, p1.pages, p1.total, p1.from, p1.to]).toEqual([1, 4, 7, 1, 2]);
    const p2 = journalPage(days, 2, 2);
    expect(p2.days.map((g) => g.day)).toEqual(['2026-11-09', '2026-11-06']);
    expect(p2.days.flatMap((g) => g.items.map((d) => d.id))).toEqual(['c', 'd']);
    expect([p2.from, p2.to]).toEqual([3, 4]);
  });

  it('clamps a page outside the range and reads it from a string', () => {
    expect(journalPage(days, '9', 2).page).toBe(4);
    expect(journalPage(days, 'x', 2).page).toBe(1);
    expect(journalPage(days, 0, 2).page).toBe(1);
    expect(journalPage(days, 4, 2).days.flatMap((g) => g.items.map((d) => d.id))).toEqual(['g']);
  });

  it('handles an empty journal', () => {
    expect(journalPage([], 1)).toEqual({ days: [], page: 1, pages: 1, total: 0, from: 0, to: 0 });
    expect(journalPage(undefined).total).toBe(0);
  });
});

import { describe, expect, it } from 'vitest';
import { expiresLabel, kindName, lampSummary, lampsOf, needsReason, oneLine, originName, scoreOf } from './decisions.js';
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
  });

  it('keeps the first sentence of a thesis', () => {
    expect(oneLine('First bit. Second bit.')).toBe('First bit.');
    expect(oneLine('x'.repeat(200))).toHaveLength(158);
  });
});

import { describe, expect, it } from 'vitest';
import plan from '../fixtures/engine.reference.json';
import yardstick from '../fixtures/engine.reference.yardstick.json';
import { driftTone, driftWords, planLimits, referenceOf } from './plan.js';

const limits = planLimits(null, null);

describe('what drift is measured against', () => {
  it('judges drift against a loaded plan, and when the desk does not say', () => {
    expect(referenceOf(plan)).toEqual({ judged: true, name: 'Your plan', mix: 'its target', note: null });
    expect(referenceOf(null).judged).toBe(true);
    expect(referenceOf({ source: null, judged: false, name: null }).judged).toBe(true);
  });

  it('reads the built-in safe mix as a yardstick, not a target', () => {
    const ref = referenceOf(yardstick);
    expect(ref).toMatchObject({ judged: false, name: 'Safe mix', mix: 'the safe mix' });
    expect(ref.note).toMatch(/yardstick, not a target/);
  });

  it('keeps the rebalance prompt and the watch tone for a judged plan', () => {
    const ref = referenceOf(plan);
    const w = driftWords(ref, limits);
    expect(w).toMatchObject({ judged: true, label: 'Largest drift', line: 'Rebalance at 5', tag: 'Drift', target: 'Target', gap: 'Drift' });
    expect(w.hero(1.32)).toBe('largest drift 1.3 pts');
    expect(driftTone(ref, 6.2, limits)).toBe('watch');
    expect(driftTone(ref, -6.2, limits)).toBe('watch');
    expect(driftTone(ref, 1.3, limits)).toBeUndefined();
    expect(driftTone(ref, null, limits)).toBeUndefined();
  });

  it('drops the prompt and the tone when the reference is only a yardstick', () => {
    const ref = referenceOf(yardstick);
    const w = driftWords(ref, limits);
    expect(w).toMatchObject({ judged: false, label: 'Vs the safe mix', line: 'A yardstick, not a target', tag: 'Vs the safe mix', rows: 'Against the safe mix', target: 'Safe mix', gap: 'Gap', step: 'gap' });
    expect(w.hero(20)).toBe('up to 20.0 pts from the safe mix');
    expect(w.split).toBe('split the way the safe mix would, as a yardstick.');
    expect(driftTone(ref, 20, limits)).toBeUndefined();
  });
});

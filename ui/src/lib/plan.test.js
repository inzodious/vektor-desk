import { describe, expect, it } from 'vitest';
import plan from '../fixtures/engine.reference.json';
import yardstick from '../fixtures/engine.reference.yardstick.json';
import { driftTone, driftWords, judgedRuleRows, planLimits, referenceOf, ruleState } from './plan.js';

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

  it('says the drift rule is not judged against a yardstick, whatever the engine sent', () => {
    const ref = referenceOf(yardstick);
    const drift = { id: 'drift-max', kind: 'drift_max_pts', enabled: true };
    const margin = { id: 'no-margin-buys', kind: 'no_margin_buys', enabled: true };
    expect(ruleState(drift, null, ref)).toEqual({ tone: '', word: 'Not judged', icon: 'info', line: 'The safe mix is a yardstick, not a target' });
    expect(ruleState(drift, 1, ref).word).toBe('Not judged');
    expect(ruleState(margin, 1, ref)).toEqual({ tone: 'ok', word: 'Passing', icon: 'check' });
    const rows = [
      { scope_id: 'drift-max', value: 1 },
      { scope_id: 'no-margin-buys', value: 1 },
    ];
    expect(judgedRuleRows(rows, [drift, margin], ref)).toEqual([rows[1]]);
  });

  it('keeps every rule word for a judged plan', () => {
    const ref = referenceOf(plan);
    const drift = { id: 'drift-max', kind: 'drift_max_pts', enabled: true };
    expect(ruleState(drift, 1, ref).word).toBe('Passing');
    expect(ruleState(drift, 0, ref)).toEqual({ tone: 'watch', word: 'Heads up', icon: 'flag' });
    expect(ruleState(drift, null, ref)).toEqual({ tone: 'info', word: 'Not checked', icon: 'flag' });
    expect(ruleState({ ...drift, enabled: false }, 1, ref).word).toBe('Off');
    const rows = [{ scope_id: 'drift-max', value: 1 }];
    expect(judgedRuleRows(rows, [drift], ref)).toBe(rows);
  });
});

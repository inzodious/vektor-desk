import { describe, expect, it } from 'vitest';
import { fundsFromMetrics, indexMetrics, val } from './metrics.js';
import { planLimits } from './plan.js';
import fixture from '../fixtures/engine.metrics.json';
import profile from '../fixtures/decisions.profile.json';
import rules from '../fixtures/decisions.rules.json';

describe('metrics', () => {
  it('looks up by id, scope and window', () => {
    const m = indexMetrics(fixture.metrics);
    expect(m.get('plan.drift_max')).not.toBeNull();
    expect(m.get('bm.excess', { scope: 'shadow', scopeId: 'plan_shadow', window: 'YTD' })).not.toBeNull();
    expect(m.get('nope')).toBeNull();
    expect(m.all('plan.rules', 'rule').length).toBe(3);
  });

  it('hides values without enough history', () => {
    expect(val({ value: 4, quality: 'insufficient_history' })).toBeNull();
    expect(val({ value: 0, quality: 'ok' })).toBe(0);
    expect(val(null)).toBeNull();
  });

  it('groups holding metrics into funds, plan funds first', () => {
    const funds = fundsFromMetrics(fixture.metrics);
    const inPlan = funds.filter((f) => f.target != null);
    expect(inPlan.length).toBe(4);
    expect(funds.indexOf(inPlan[inPlan.length - 1])).toBeLessThan(funds.findIndex((f) => f.target == null));
    inPlan.forEach((f) => expect(f.drift).toBeCloseTo(f.weight - f.target, 1));
  });

  it('reads plan limits from desk.yaml', () => {
    expect(planLimits(profile, rules)).toMatchObject({ driftPts: 5, satelliteCap: 10, version: 2, rulesVersion: 1 });
    expect(planLimits(null, null)).toMatchObject({ driftPts: 5, satelliteCap: 10, version: null });
  });
});

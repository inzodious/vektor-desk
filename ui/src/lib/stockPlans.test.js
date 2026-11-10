import { describe, expect, it } from 'vitest';
import plans from '../fixtures/decisions.plans.json';
import facts from '../fixtures/engine.planfacts.json';
import steps from '../fixtures/decisions.plan-steps.json';
import {
  approvesOnSave,
  bandOf,
  bridgeSteps,
  canMarkDone,
  canUndo,
  draftLine,
  editable,
  planCards,
  planChanges,
  planCheck,
  planFromForm,
  plansHead,
  refusal,
  ruleLines,
  ruler,
  rulerKey,
  savedText,
  sortSteps,
  startPlan,
  startStep,
  stepCheck,
  stepFacts,
  stepFromForm,
  stepShape,
  stepWhen,
  versionChip,
  weightLine,
  weightMeter,
  whereWord,
  withStep,
  withoutStep,
  zonesOf,
} from './stockPlans.js';

const plan = (symbol) => plans.items.find((p) => p.symbol === symbol);
const fact = (symbol) => facts.rows.find((r) => r.symbol === symbol);

describe('stock plans', () => {
  it('puts drafts first and lists holdings without a plan', () => {
    const { cards, bare } = planCards(plans, facts);
    expect(cards.map((c) => c.symbol)).toEqual(['ACME', 'VXUS', 'FXAIX']);
    expect(bare.map((c) => c.symbol)).toEqual(['FTEC', 'BND']);
    expect(plansHead(plans, facts)).toEqual({ big: '3 plans', sub: '1 approved · 2 drafts wait on you · 2 without a plan' });
    expect(plansHead({ items: [] }, facts).big).toBe('No plans yet');
    expect(planCards(null, null)).toEqual({ cards: [], bare: [] });
  });

  it('reads the weight against the plan band, then the conviction band, then the engine', () => {
    expect(bandOf(plan('ACME'), fact('ACME'))).toEqual({ min: 0, max: 5, source: 'plan' });
    expect(bandOf({ weight_band: null, conviction: { band_min_pct: 2, band_max_pct: 12 } }, null)).toEqual({ min: 2, max: 12, source: 'conviction' });
    expect(bandOf(null, fact('BND'))).toBeNull();
    const m = weightMeter(plan('FXAIX'), fact('FXAIX'));
    expect(m.max).toBe(85);
    expect(m.mark).toBeCloseTo((58.84 / 85) * 100, 1);
    expect(weightLine(plan('ACME'), fact('ACME'))).toBe('0.5% of the portfolio · band 0% to 5%');
    expect(weightLine(null, fact('BND'))).toBe('4.9% of the portfolio · no band yet');
    expect(weightMeter(null, null)).toBeNull();
  });

  it('lays add and trim zones on one price ruler', () => {
    const r = ruler(plan('ACME'), fact('ACME'));
    expect(r.where).toBe('between');
    expect(r.add.left).toBeLessThan(r.price.left);
    expect(r.price.left).toBeLessThan(r.trim.left);
    expect(r.high52.left).toBeLessThanOrEqual(100);
    expect(r.add.left).toBeGreaterThanOrEqual(0);
    expect(rulerKey(r).map((k) => k.id)).toEqual(['add', 'price', 'trim', 'range']);
    expect(rulerKey(r)[0].value).toBe('$1.92 to $2.57');
    expect(whereWord(ruler(plan('VXUS'), fact('VXUS'))).t).toBe('In the add zone');
    expect(whereWord(ruler(plan('FXAIX'), fact('FXAIX')))).toBeNull();
    expect(ruler(plan('ACME'), null)).toBeNull();
  });

  it('suggests zones from the monthly swing when there is no plan', () => {
    const z = zonesOf(null, fact('FTEC'));
    expect(z.suggested).toBe(true);
    expect(z.add.low).toBeCloseTo(211.85, 1);
    expect(rulerKey(ruler(null, fact('FTEC')))[0].label).toBe('Suggested add');
  });

  it('writes the rules as sentences', () => {
    const lines = ruleLines(plan('ACME'));
    expect(lines[0].text).toBe('Add between $1.92 and $2.57, up to $50 a month, from new deposits only.');
    expect(lines[1].text).toBe('Trim above 4% of the portfolio, back to 2.5%, or between $3.87 and $4.52.');
    expect(ruleLines(plan('FXAIX'))[0].text).toBe('Add from new deposits only.');
    expect(ruleLines(null)).toEqual([]);
  });

  it('says who drafted it and what changed', () => {
    expect(versionChip(plan('ACME'))).toEqual({ t: 'Draft v2 from the Plan desk', tone: 'watch' });
    expect(versionChip(plan('FXAIX'))).toEqual({ t: 'Approved v1', tone: 'ok' });
    expect(versionChip({ status: 'draft', author: 'you', version: 3 }).t).toBe('Your draft v3');
    expect(planChanges(plan('ACME'))).toEqual(['Trim rule', 'Next review', '1 new step']);
    expect(planChanges(plan('FXAIX'))).toEqual([]);
    expect(draftLine(plan('ACME'))).toBe('v1 stays in force until you approve this one.');
    expect(draftLine(plan('VXUS'))).toBe('Nothing is in force until you approve it.');
    expect(draftLine(plan('FXAIX'))).toBeNull();
  });

  it('orders steps and describes them', () => {
    const acme = plan('ACME');
    expect(sortSteps(acme.steps).map((s) => s.id)).toEqual(['review-2026-11-13', 'margin-repay', 'harvest-2026', 'hold', 'trim']);
    const harvest = acme.steps.find((s) => s.id === 'harvest-2026');
    expect(stepWhen(harvest)).toBe('Dec 7 to Dec 15');
    expect(stepFacts(harvest, plans.lot_methods)).toEqual(['10 shares', 'from Individual', 'Specific Shares, highest-cost lots', 'no buys for 31 days after']);
    expect(stepWhen(acme.steps.find((s) => s.id === 'hold'))).toBe('Always');
    expect(stepFacts({ status: 'done', done_on: '2026-11-18', done_by: 'broker' })).toEqual(['done Nov 18 by a broker fill']);
  });

  it('lets a step be marked done only when it is in force', () => {
    const acme = plan('ACME');
    const repay = acme.steps.find((s) => s.id === 'margin-repay');
    const trim = acme.steps.find((s) => s.id === 'trim');
    expect(canMarkDone(acme, repay)).toBe(true);
    expect(canMarkDone(acme, trim)).toBe(false);
    expect(canMarkDone(plan('VXUS'), plan('VXUS').steps[0])).toBe(false);
    expect(canUndo(plan('FXAIX'), { id: 'add', status: 'done', done_by: 'you' })).toBe(true);
    expect(canUndo(plan('FXAIX'), { id: 'add', status: 'done', done_by: 'broker' })).toBe(false);
  });

  it('sends a plan back whole, without the view-only fields', () => {
    const body = editable(plan('ACME'));
    expect(Object.keys(body)).toEqual(['role', 'thesis', 'weight_band', 'add_rule', 'trim_rule', 'exit_conditions', 'tax_notes', 'catalysts', 'next_review', 'steps']);
    expect(body.steps).toHaveLength(5);
    expect(body.steps[0]).toEqual({ id: 'margin-repay', kind: 'repay', text: 'Pay off the margin debit', due: '2026-11-18', note: 'The 11-18 deposit pays off the margin debit.' });
    expect(withStep(plan('FXAIX'), { kind: 'repay', due: '2026-11-18' }).steps).toHaveLength(2);
    expect(withoutStep(plan('ACME'), 'hold').steps.map((s) => s.id)).not.toContain('hold');
    expect(approvesOnSave(plan('FXAIX'))).toBe(true);
    expect(approvesOnSave(plan('ACME'))).toBe(false);
    expect(approvesOnSave(null)).toBe(false);
  });

  it('starts the plan form from the plan, or from the engine for a new one', () => {
    const f = startPlan(plan('ACME'), fact('ACME'));
    expect(f).toMatchObject({ role: 'conviction', min: '0', max: '5', addLow: '1.92', addHigh: '2.57', addMax: '50', depositsOnly: true, trimAbove: '4', review: '2026-11-20' });
    expect(f.exits).toBe('Two straight quarters of missed launches\nA dilutive raise under $2.50');
    const fresh = startPlan(null, fact('FTEC'));
    expect(fresh).toMatchObject({ role: 'core', thesis: '', min: '', max: '', addLow: '211.85', trimHigh: '292.59' });
    expect(startPlan(null, fact('ACME')).role).toBe('satellite');
  });

  it('checks the plan form before it is sent', () => {
    const ok = startPlan(plan('ACME'), fact('ACME'));
    expect(planCheck(ok)).toBeNull();
    expect(planCheck({ ...ok, thesis: ' ' })).toMatch(/why you hold it/);
    expect(planCheck({ ...ok, max: 'lots' })).toMatch(/doesn’t read as a number/);
    expect(planCheck({ ...ok, min: '6' })).toMatch(/ceiling at or above its floor/);
    expect(planCheck({ ...ok, addHigh: '' })).toMatch(/both prices/);
    expect(planCheck({ ...ok, trimLow: '9' })).toMatch(/low price is above/);
    expect(planCheck({ ...ok, trimTo: '8' })).toMatch(/below the trigger/);
    expect(planCheck({ ...ok, role: 'moon' })).toMatch(/Pick a role/);
  });

  it('turns the plan form into what the desk expects, keeping steps and catalysts', () => {
    const f = { ...startPlan(plan('ACME'), fact('ACME')), max: '6', exits: 'One\n\n Two ', tax: '' };
    const body = planFromForm(f, plan('ACME'));
    expect(body.weight_band).toEqual({ min_pct: 0, max_pct: 6 });
    expect(body.exit_conditions).toEqual(['One', 'Two']);
    expect(body.tax_notes).toBeNull();
    expect(body.catalysts).toHaveLength(2);
    expect(body.steps).toHaveLength(5);
    expect(body.add_rule).toEqual({ zone_low: 1.92, zone_high: 2.57, max_per_month_usd: 50, deposits_only: true, note: 'Only from new deposits, one buy a month.' });
    const blank = planFromForm({ ...startPlan(null, null), role: 'core', thesis: 'Base.' }, null);
    expect(blank).toMatchObject({ role: 'core', thesis: 'Base.', weight_band: null, add_rule: null, trim_rule: null, steps: [], catalysts: [], exit_conditions: [] });
  });

  it('shapes the step form by kind and fills it from the desk templates', () => {
    expect(stepShape('harvest')).toMatchObject({ shares: true, until: true, lots: true, noBuy: true, text: false, amount: false });
    expect(stepShape('repay')).toMatchObject({ shares: false, amount: true, when: false, lots: false });
    expect(stepShape('hold')).toMatchObject({ text: true, when: true, shares: false });
    const h = startStep('harvest', plans.step_templates);
    expect(h).toMatchObject({ kind: 'harvest', lots: 'highest_cost', noBuy: '31', note: 'Tax-loss harvest. Pick Specific Shares at the broker.' });
    expect(startStep('add').lots).toBe('');
  });

  it('checks a step and builds its body', () => {
    const h = { ...startStep('harvest', plans.step_templates), shares: '105', due: '2026-12-07', until: '2026-12-15', account: 'Individual' };
    expect(stepCheck(h)).toBeNull();
    expect(stepFromForm(h)).toEqual({ kind: 'harvest', shares: 105, due: '2026-12-07', until: '2026-12-15', account: 'Individual', lots: 'highest_cost', no_buy_days: 31, note: 'Tax-loss harvest. Pick Specific Shares at the broker.' });
    expect(stepCheck({ ...h, shares: '' })).toMatch(/how many shares/);
    expect(stepFromForm({ ...h, shares: 'All' }).shares).toBe('all');
    expect(stepCheck({ ...h, until: '2026-12-01' })).toMatch(/ends before it starts/);
    expect(stepCheck({ ...h, due: '', until: '' })).toMatch(/date, or say what it waits on/);
    const r = { ...startStep('repay', plans.step_templates), due: '2026-11-18' };
    expect(stepCheck(r)).toBeNull();
    expect(stepFromForm(r)).toEqual({ kind: 'repay', due: '2026-11-18', note: 'The deposit pays off the margin debit.' });
    expect(stepCheck({ ...r, due: '' })).toBe('Give it a date.');
    expect(stepCheck({ ...startStep('hold'), when: 'Always' })).toMatch(/Say what the step is/);
    expect(stepFromForm({ ...startStep('hold'), text: ' No margin ', when: 'Always' })).toEqual({ kind: 'hold', text: 'No margin', when: 'Always' });
    expect(stepCheck({ ...startStep('add'), due: '2026-11-18' })).toMatch(/dollar amount or a share count/);
  });

  it('reads refusals and saves in plain words', () => {
    expect(refusal({ status: 422, message: 'The desk API answered 422.', body: { detail: [{ msg: 'thesis is required' }, 'steps: at most 15'] } })).toBe('thesis is required steps: at most 15');
    expect(refusal({ status: 422, message: 'shares must be above zero' })).toBe('shares must be above zero');
    expect(refusal({ status: 404, message: 'HTTP 404' })).toBe('Stock plans switch on with the next desk update.');
    expect(refusal({ status: 0 })).toBe('The desk API didn’t answer. Nothing was written.');
    expect(savedText({ changed: true, plan: { version: 3, status: 'approved' } }, 'ACME', true)).toBe('ACME plan v3 is saved and in force.');
    expect(savedText({ changed: true, plan: { version: 3, status: 'draft' } }, 'ACME', false)).toBe('Saved as draft v3. Approve it to put it in force.');
    expect(savedText({ changed: false, plan: {} }, 'ACME', false)).toBe('Nothing changed on the ACME plan.');
  });

  it('lists the coming plan steps and no-buy windows for the Bridge', () => {
    const b = bridgeSteps(steps);
    expect(b.count).toBe(3);
    expect(b.rows[0]).toMatchObject({ symbol: 'ACME', text: 'Review the ACME plan', when: 'Nov 13', open: false });
    expect(b.rows[0].stamp).toEqual({ day: 13, mon: 'Nov' });
    expect(b.noBuy).toEqual([{ symbol: 'ACME', text: 'No ACME buys while its loss sale is planned', reason: 'Sell 10 ACME to harvest the loss' }]);
    expect(bridgeSteps({ items: [], no_buy: { NOVA: { until: '2026-12-20' } } }).noBuy[0].text).toBe('No NOVA buys until Dec 20');
    expect(bridgeSteps(null)).toEqual({ rows: [], noBuy: [], count: 0 });
  });
});

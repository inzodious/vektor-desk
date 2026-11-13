import { describe, expect, it } from 'vitest';
import steps from '../fixtures/decisions.next-steps.json';
import none from '../fixtures/decisions.next-steps.fresh.json';
import { addedStep, nextSteps, readWords, stepRow, undoPath } from './nextsteps.js';

describe('next steps', () => {
  const view = nextSteps(steps);

  it('keeps the desk’s order, dated first and standing apart', () => {
    expect(view.items.map((s) => s.id)).toEqual(['plan:ACME:harvest', 'deposit:payday:2026-11-18', 'you:s_20261109150000_32032d_4835']);
    expect(view.standing).toHaveLength(5);
    expect(view.empty).toBe(false);
    expect(view.days).toBe(90);
  });

  it('gives a dated row its stamp, window and words as written', () => {
    expect(view.items[0]).toMatchObject({
      stamp: 'Nov 13',
      text: 'Sell 40 ACME to harvest the loss',
      detail: 'From Individual. Lots: Specific Shares, highest-cost lots.',
      meta: 'to Nov 20',
      why: 'A sale below your cost books the loss against this year’s taxes.',
      basis: 'Your ACME plan, version 2, approved Nov 6.',
      changes: 'No longer worth doing if ACME is back above your cost.',
      queue: null,
    });
  });

  it('shows the lab’s reading as the chip, and only a test that does not back the step stands out', () => {
    expect(view.items[0].chip).toEqual({ text: 'Lab backs it', words: 'The lab’s test backs this.', tone: '' });
    expect(view.items[1].chip).toEqual({ text: 'No clear edge', words: 'The lab’s test shows no clear edge either way.', tone: '' });
    const agreed = view.standing.find((s) => s.id.startsWith('agreed:'));
    expect(agreed.chip).toEqual({ text: 'Lab disagrees', words: 'The lab’s test does not back this.', tone: 'watch' });
    expect(agreed.meta).toBe('Until Dec 9');
    expect(agreed.tests).toEqual([{ key: 'lib-wait-for-rates', row: 'lib-wait-for-rates', title: 'Wait for a rate decision before buying bonds', sentence: 'Hurt: behind in 61% of 120 start months.' }]);
    expect(view.standing.find((s) => s.id === 'nobuy:ACME')).toMatchObject({ chip: null, tests: [], stamp: null, meta: null });
  });

  it('links a step that is his to decide to its proposal, and no other', () => {
    expect(view.items[1].queue).toBe('/decisions?d=d_20261109130500_168372');
    expect(view.standing.every((s) => s.queue === null)).toBe(true);
    expect(view.items[2].queue).toBeNull();
  });

  it('says when an undated step happens and what state a step is in', () => {
    expect(view.standing.find((s) => s.id === 'plan:ACME:add').meta).toBe('On a pullback below $2.60');
    expect(stepRow({ id: 'a', text: 'Sell 10 ACME', status: 'partial', date: '2026-11-10' }).meta).toBe('Partly done');
    expect(stepRow({ id: 'a', text: 'Sell 10 ACME', status: 'open', date: '2026-11-10', until: '2026-11-12' }).meta).toBe('Due now · to Nov 12');
  });

  it('reads an empty or older answer as nothing to show', () => {
    expect(nextSteps(none)).toMatchObject({ items: [], standing: [], empty: true });
    expect(nextSteps(null).empty).toBe(true);
    expect(nextSteps({ items: [null, { text: 'no id' }], standing: 'x' }).empty).toBe(true);
    expect(stepRow({ id: 'a', text: '{"raw":1}' })).toMatchObject({ text: 'A step with no words yet', chip: null, tests: [] });
  });
});

describe('his own words as a step', () => {
  const view = nextSteps(steps);
  const dated = view.items[2];
  const standing = view.standing[0];

  it('keeps his sentence and shows how its date was read', () => {
    expect(dated).toMatchObject({ mine: true, stamp: 'Dec 7', text: 'I’ll trim FTEC after Dec 6, once the year’s gains are clear.', read: 'read as Dec 7 to Dec 31, from “after Dec 6”', meta: 'Your words · to Dec 31' });
    expect(standing).toMatchObject({ mine: true, stamp: null, text: 'I’ll wait for earnings first', read: null, meta: 'Your words' });
    expect(readWords({ date: '2026-12-07', until: null, phrase: null })).toBe('read as Dec 7');
    expect(readWords({ date: null, until: '2026-12-31', phrase: 'by year end' })).toBe('read as until Dec 31, from “by year end”');
    expect(readWords({ date: null, until: null, phrase: 'soon' })).toBeNull();
    expect(readWords(null)).toBeNull();
  });

  it('says nothing about a test the lab has not judged', () => {
    expect(dated.chip).toBeNull();
    expect(dated.tests).toEqual([]);
  });

  it('offers the undo only on his own rows and only on the desk’s own route', () => {
    expect(dated.undo).toBe('/api/decisions/next-steps/s_20261109150000_32032d_4835');
    expect(standing.undo).toBe('/api/decisions/next-steps/s_20261109150000_632595_d3af');
    expect(view.items[0].undo).toBeNull();
    expect(undoPath({ method: 'DELETE', path: 'https://elsewhere.example/x' })).toBeNull();
    expect(undoPath({ method: 'POST', path: '/api/decisions/next-steps/s_1' })).toBeNull();
    expect(undoPath({ method: 'DELETE', path: '/api/decisions/next-steps/' })).toBeNull();
    expect(stepRow({ id: 'plan:x', source: 'plan', text: 'Sell', undo: { method: 'DELETE', path: '/api/decisions/next-steps/s_1' } }).undo).toBeNull();
  });

  it('reads the step a pass became, and nothing when it became none', () => {
    const raw = steps.items[2];
    expect(addedStep({ id: 'd_1', title: 'Trim $90 FTEC', step: raw })).toEqual({ id: raw.id, text: 'I’ll trim FTEC after Dec 6, once the year’s gains are clear.', read: 'read as Dec 7 to Dec 31, from “after Dec 6”', undo: raw.undo.path });
    expect(addedStep({ id: 'd_1', title: 'Trim $90 FTEC' })).toBeNull();
    expect(addedStep({ step: null })).toBeNull();
    expect(addedStep(null)).toBeNull();
  });
});

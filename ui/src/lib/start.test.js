import { describe, expect, it } from 'vitest';
import never from '../fixtures/start.never.json';
import running from '../fixtures/start.starting.json';
import loose from '../fixtures/start.loose.json';
import done from '../fixtures/start.json';
import gaps from '../fixtures/readiness.gaps.json';
import ready from '../fixtures/readiness.json';
import { firstRunScore } from './firstrun.js';
import { gapOf, gapWords, needsYou, readinessMap, setupChip, startRefusal, startView, stepTook, stepWord } from './start.js';

describe('start the desk', () => {
  it('shows nothing when the desk does not serve the chain', () => {
    expect(startView(null)).toMatchObject({ mode: 'none', show: false, canStart: false });
    expect(startView({ state: 'idle', steps: [] }).mode).toBe('none');
  });

  it('offers one button on a desk that has never run', () => {
    const v = startView(never);
    expect(v).toMatchObject({ mode: 'never', show: true, head: 'The desk hasn’t run yet', button: 'Start the desk', canStart: true, total: 10, ended: 0, share: 0, blocked: null });
    expect(v.line).toMatch(/you can leave the page/);
  });

  it('reads the running step in plain words and takes the button away', () => {
    const v = startView(running);
    expect(v).toMatchObject({ mode: 'running', show: true, head: 'Starting the desk', button: null, canStart: false, ended: 3, blocked: null });
    expect(v.short).toBe('Step 4 of 10: Fetch market history');
    expect(v.share).toBeCloseTo(0.3);
  });

  it('keeps the loose ends in view after a partial run', () => {
    const v = startView(loose);
    expect(v).toMatchObject({ mode: 'partial', show: true, button: 'Start again', line: '7 of 10 steps done. 3 need you.' });
    expect(v.needs.map((s) => s.id)).toEqual(['discounts', 'debrief', 'plans']);
  });

  it('goes away once a run finished clean', () => {
    expect(startView(done)).toMatchObject({ mode: 'ok', show: false, head: 'The desk is up', needs: [] });
  });

  it('says why it cannot start', () => {
    const v = startView({ ...never, can_start: false, blocked: { error: 'scheduler_down', message: 'The scheduler is off.' } });
    expect(v).toMatchObject({ canStart: false, blocked: 'The scheduler is off.' });
    expect(startRefusal({ status: 503, body: { error: 'scheduler_down', message: 'The scheduler is off.' } })).toBe('The scheduler is off.');
    expect(startRefusal({ status: 409, body: { error: 'running' } })).toBeNull();
    expect(startRefusal({ status: 404, message: 'Not Found' })).toMatch(/next desk update/);
  });

  it('words each step and how long it took', () => {
    const [accounts, prices, , market] = running.steps;
    expect(stepWord(accounts)).toEqual({ t: 'Done', tone: 'ok' });
    expect(stepTook(accounts)).toBe('17 s');
    expect(stepWord(prices).t).toBe('Skipped');
    expect(stepTook(prices)).toBeNull();
    expect(stepWord(market).t).toBe('Working');
    expect(stepTook(loose.steps.find((s) => s.id === 'plan_keeper'))).toBe('2 min 33 s');
    expect(needsYou(prices)).toBe(false);
    expect(needsYou(loose.steps.find((s) => s.id === 'debrief'))).toBe(true);
    expect(needsYou(loose.steps.find((s) => s.id === 'discounts'))).toBe(true);
  });
});

describe('readiness', () => {
  it('finds the gap for a section and nothing for a ready one', () => {
    const map = readinessMap(gaps);
    expect(Object.keys(map)).toHaveLength(19);
    expect(gapOf(map, 'results.day')).toMatchObject({ state: 'empty', action: { kind: 'job', job: 'engine-review' } });
    expect(gapOf(map, 'decisions.journal')).toBeNull();
    expect(gapOf(readinessMap(ready), 'results.day')).toBeNull();
    expect(gapOf({}, 'results.day')).toBeNull();
    expect(gapOf(readinessMap(null), 'results.day')).toBeNull();
  });

  it('uses the desk’s words and falls back to the page’s own', () => {
    const map = readinessMap(gaps);
    expect(gapWords(gapOf(map, 'results.day'), { why: 'Page words.' })).toEqual({ state: 'empty', why: 'No results yet: the review hasn’t run.', action: { kind: 'job', job: 'engine-review', label: 'Write it now' }, auto: 'Fills by itself today at 5:35 PM.' });
    expect(gapWords(null, { why: 'Page words.', action: { kind: 'link', to: '/x', label: 'Go' } })).toEqual({ state: 'unknown', why: 'Page words.', action: { kind: 'link', to: '/x', label: 'Go' }, auto: null });
    expect(gapWords({ state: 'empty', why: 'x', action: { kind: 'mystery' } }).action).toBeNull();
  });

  it('counts setup steps left for the top bar', () => {
    const score = firstRunScore([{ state: 'done' }, { state: 'todo' }, { state: 'todo' }, { state: 'soon' }]);
    expect(setupChip(score)).toMatchObject({ text: 'Setup · 2 left', short: '2 left' });
    expect(setupChip(firstRunScore([{ state: 'done' }]))).toBeNull();
    expect(setupChip(null)).toBeNull();
  });
});

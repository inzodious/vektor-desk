import { describe, expect, it } from 'vitest';
import { checkWord, healthAlert, healthChecks, healthNeeds, kindOf } from './health.js';
import fail from '../fixtures/engine.health.fail.json';
import fresh from '../fixtures/engine.health.fresh.json';
import healing from '../fixtures/engine.health.healing.json';
import calm from '../fixtures/engine.health.json';

const old = [
  { check_name: 'closes', status: 'ok', detail: 'fine' },
  { check_name: 'shares', status: 'warn', detail: 'No lot export yet.' },
  { check_name: 'value', status: 'fail', detail: 'Desk value is off the broker.' },
];

describe('health alert', () => {
  it('stays away unless something blocks', () => {
    expect(healthAlert(calm)).toBeNull();
    expect(healthAlert(fresh)).toBeNull();
    expect(healthAlert(healing)).toBeNull();
    expect(healthAlert(null)).toBeNull();
  });

  it('prints the blocking sentence on its own', () => {
    expect(healthAlert(fail)).toEqual({ head: 'Look, don’t act yet.', fix: 'Your broker’s positions and account totals for Friday do not add up, so values cannot be trusted yet. The desk is reading your accounts again.' });
  });

  it('keeps the check name in front on a desk that sends no kinds', () => {
    expect(healthAlert({ status: 'fail', checks: old }).fix).toBe('Values against the broker: Desk value is off the broker.');
    expect(kindOf(old[1])).toBe('needs_you');
    expect(kindOf(old[0])).toBeNull();
  });

  it('says so when the engine has never run', () => {
    expect(healthAlert({ as_of: null, status: 'fail', checks: [] }).fix).toMatch(/not finished a run/);
  });
});

describe('what needs him', () => {
  it('lists only the checks he has to act on, as the desk words them', () => {
    expect(healthNeeds(fresh).map((n) => n.key)).toEqual(['marginal_rate', 'shares']);
    expect(healthNeeds(fresh)[1].text).toBe('No tax lots yet, so tax and wash-sale checks are off. Upload your Fidelity history or a lot export in Settings, Data, Inbox.');
    expect(healthNeeds(healing)).toEqual([]);
    expect(healthNeeds(null)).toEqual([]);
  });
});

describe('checks for Settings', () => {
  it('groups by kind, blocking first, with the long text folded', () => {
    const v = healthChecks(fail);
    expect(v).toMatchObject({ chip: '1 blocking', tone: 'act', fine: '4 other checks are fine.' });
    expect(v.groups.map((g) => [g.title, g.rows.length])).toEqual([
      ['Blocking', 1],
      ['Needs you', 2],
    ]);
    expect(v.groups[0].rows[0]).toMatchObject({ name: 'Values against the broker', tried: 'The desk has asked once.' });
    expect(v.groups[0].rows[0].more).toMatch(/4\.1% off the broker/);
  });

  it('reads a desk that is only fixing itself as quiet', () => {
    expect(healthChecks(healing)).toMatchObject({ chip: 'Fixing itself', tone: '' });
    expect(healthChecks(healing).groups.map((g) => g.title)).toEqual(['Fixing itself']);
    expect(healthChecks(fresh)).toMatchObject({ chip: '2 for you', tone: 'watch' });
    expect(healthChecks(calm)).toMatchObject({ chip: 'All clear', tone: 'ok', groups: [] });
    expect(healthChecks(null)).toBeNull();
  });

  it('words check names', () => {
    expect(checkWord('marginal_rate')).toBe('Tax rate');
    expect(checkWord('freshness')).toBe('Account read');
    expect(checkWord('new_thing')).toBe('new thing');
  });
});

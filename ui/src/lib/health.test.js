import { describe, expect, it } from 'vitest';
import { checkWord, healthAlert, healthChecks } from './health.js';

const checks = [
  { check_name: 'closes', status: 'ok', detail: 'fine' },
  { check_name: 'shares', status: 'warn', detail: 'No lot export yet.' },
  { check_name: 'value', status: 'fail', detail: 'Desk value is off the broker.' },
];

describe('health alert', () => {
  it('stays away while the engine is healthy or only has notes', () => {
    expect(healthAlert({ status: 'ok', checks })).toBeNull();
    expect(healthAlert({ status: 'warn', checks: checks.slice(0, 2) })).toBeNull();
    expect(healthAlert(null)).toBeNull();
  });

  it('leads a fail with the failing check and nothing else', () => {
    expect(healthAlert({ as_of: '2026-11-06', status: 'fail', checks })).toEqual({ head: 'Look, don’t act yet.', fix: 'Values against the broker: Desk value is off the broker.' });
  });

  it('says so when the engine has never run', () => {
    expect(healthAlert({ as_of: null, status: 'fail', checks: [] }).fix).toMatch(/not finished a run/);
  });

  it('lists every check that is not fine for Settings', () => {
    expect(healthChecks({ status: 'fail', checks })).toEqual({
      chip: '1 failing',
      tone: 'act',
      rows: [
        { key: 'value', name: 'Values against the broker', status: 'fail', detail: 'Desk value is off the broker.' },
        { key: 'shares', name: 'Share counts and lots', status: 'warn', detail: 'No lot export yet.' },
      ],
      fine: '1 other check is fine.',
    });
    expect(healthChecks({ status: 'warn', checks: checks.slice(0, 2) })).toMatchObject({ chip: '1 to read', tone: 'watch' });
    expect(healthChecks({ status: 'ok', checks: checks.slice(0, 1) })).toEqual({ chip: 'All clear', tone: 'ok', rows: [], fine: '1 other check is fine.' });
    expect(healthChecks(null)).toBeNull();
  });

  it('words check names', () => {
    expect(checkWord('marginal_rate')).toBe('Tax rate');
    expect(checkWord('new_thing')).toBe('new thing');
  });
});

import { describe, expect, it } from 'vitest';
import { checkWord, healthBanner } from './health.js';

const checks = [
  { check_name: 'closes', status: 'ok', detail: 'fine' },
  { check_name: 'shares', status: 'warn', detail: 'No lot export yet.' },
  { check_name: 'value', status: 'fail', detail: 'Desk value is off the broker.' },
];

describe('health banner', () => {
  it('stays away while the engine is healthy', () => {
    expect(healthBanner({ status: 'ok', checks })).toBeNull();
    expect(healthBanner(null)).toBeNull();
  });

  it('leads a fail with the failing check and lists the rest', () => {
    const b = healthBanner({ as_of: '2026-11-06', status: 'fail', checks });
    expect(b.level).toBe('fail');
    expect(b.head).toMatch(/don’t act yet/);
    expect(b.fix).toBe('Values against the broker: Desk value is off the broker.');
    expect(b.others).toEqual([{ name: 'Share counts and lots', status: 'warn', detail: 'No lot export yet.' }]);
    expect(b.key).toBe('2026-11-06|value:fail,shares:warn');
  });

  it('says so when the engine has never run', () => {
    expect(healthBanner({ as_of: null, status: 'fail', checks: [] }).fix).toMatch(/not finished a run/);
  });

  it('words check names', () => {
    expect(checkWord('marginal_rate')).toBe('Tax rate');
    expect(checkWord('new_thing')).toBe('new thing');
  });
});

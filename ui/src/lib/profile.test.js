import { describe, expect, it } from 'vitest';
import { defaultsText, keyWord, profileSource } from './profile.js';

describe('desk profile', () => {
  it('words dotted keys', () => {
    expect(keyWord('tax.harvest_threshold_usd')).toBe('Harvest threshold');
    expect(keyWord('alerts.quiet_hours')).toBe('Quiet hours');
  });

  it('names the source', () => {
    expect(profileSource({ exists: false, source: 'defaults' })).toBe('Built-in defaults');
    expect(profileSource({ exists: true, source: '/data/desk.yaml' })).toBe('desk.yaml');
    expect(profileSource(null)).toBeNull();
  });

  it('sums up all-default and all-set profiles, and lists a mix', () => {
    expect(defaultsText({ set: [], defaults: ['rules'] })).toBe('Every setting is still the default.');
    expect(defaultsText({ set: ['rules'], defaults: [] })).toBe('Everything is set in desk.yaml.');
    expect(defaultsText({ set: ['rules'], defaults: ['tax.lot_method'] })).toBeNull();
  });
});

import { describe, expect, it } from 'vitest';
import { INIT_LABEL, INIT_PATH, defaultsText, keyWord, marginWords, profileInit, profileSource } from './profile.js';

describe('desk profile', () => {
  it('words dotted keys', () => {
    expect(keyWord('tax.harvest_threshold_usd')).toBe('Harvest threshold');
    expect(keyWord('alerts.quiet_hours')).toBe('Quiet hours');
  });

  it('says whose margin rate it is', () => {
    expect(keyWord('margin.rate_pct')).toBe('Margin rate');
    expect(marginWords({ rate_pct: 12, source: 'default' })).toEqual({ rate: '12%', yours: false, line: 'A typical rate until you set your own' });
    expect(marginWords({ rate_pct: 12.075, source: 'profile' })).toEqual({ rate: '12.075%', yours: true, line: 'Your rate, a year' });
    expect(marginWords({ rate_pct: null })).toBeNull();
    expect(marginWords(undefined)).toBeNull();
  });

  it('names the source', () => {
    expect(profileSource({ exists: false, source: 'defaults' })).toBe('Built-in defaults');
    expect(profileSource({ exists: true, source: '/data/desk.yaml' })).toBe('Your profile');
    expect(profileSource(null)).toBeNull();
  });

  it('offers the set-up route only while there is no profile', () => {
    expect(profileInit({ exists: false, init: { method: 'POST', path: '/api/decisions/profile/init', label: 'Set up my profile from my data' } })).toEqual({ path: INIT_PATH, label: INIT_LABEL });
    expect(profileInit({ exists: false, init: { path: '/api/decisions/profile/start', label: ' Start my profile ' } })).toEqual({ path: '/api/decisions/profile/start', label: 'Start my profile' });
    expect(profileInit({ exists: false, init: { path: 'https://elsewhere.example/x' } })).toEqual({ path: INIT_PATH, label: INIT_LABEL });
    expect(profileInit({ exists: false, starter: 'a command' })).toEqual({ path: INIT_PATH, label: INIT_LABEL });
    expect(profileInit({ exists: false })).toBeNull();
    expect(profileInit({ exists: true, init: null })).toBeNull();
    expect(profileInit(null)).toBeNull();
  });

  it('sums up all-default and all-set profiles, and lists a mix', () => {
    expect(defaultsText({ set: [], defaults: ['rules'] })).toBe('Every setting is still the default.');
    expect(defaultsText({ set: ['rules'], defaults: [] })).toBe('Everything is set in your profile.');
    expect(defaultsText({ set: ['rules'], defaults: ['tax.lot_method'] })).toBeNull();
  });
});

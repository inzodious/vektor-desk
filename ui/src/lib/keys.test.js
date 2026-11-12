import { describe, expect, it } from 'vitest';
import { fileWord, keyCheck, keyCount, keyRefusal, keyState, keyWord } from './keys.js';
import { composeView } from './box.js';

const NOW = new Date('2026-11-09T16:42:00Z');

describe('keys', () => {
  it('words each key state', () => {
    expect(keyState({ set: false }, NOW).state).toBe('unset');
    expect(keyState({ set: true, pending: true }, NOW).state).toBe('pending');
    expect(keyState({ set: true, last: { result: 'saved', at: '2026-11-09T14:00:00Z' } }, NOW).line).toBe('Saved 9:00 AM');
    expect(keyState({ set: false, last: { result: 'refused', message: 'live key', at: '2026-11-09T14:00:00Z' } }, NOW).line).toBe('The box turned it down 9:00 AM: live key');
    expect(keyCount({ keys: [{ set: true }, { set: false, pending: true }] })).toEqual({ set: 1, total: 2, pending: 1 });
    expect(fileWord('caddy.env')).toBe('Certificates');
  });

  it('leads with a plain name for each key, and makes one for a key it has not met', () => {
    expect(keyWord({ name: 'CLAUDE_CODE_OAUTH_TOKEN' })).toBe('Claude token');
    expect(keyWord({ name: 'ALPACA_API_KEY_ID' })).toBe('Alpaca paper key ID');
    expect(keyWord({ name: 'TS_AUTHKEY' })).toBe('Tailscale sign-in key');
    expect(keyWord({ name: 'DESK_NTFY_TOPIC' })).toBe('Ntfy topic');
    expect(keyWord({ name: 'POLYGON_API_KEY' })).toBe('Polygon API key');
    expect(keyWord(null)).toBe('');
  });

  it('checks a value before it leaves the browser', () => {
    expect(keyCheck('TIINGO_API_KEY', '  ')).toBe('Paste a value first.');
    expect(keyCheck('TIINGO_API_KEY', 'a\nb')).toMatch(/one line/);
    expect(keyCheck('TIINGO_API_KEY', "a'b")).toMatch(/single quote/);
    expect(keyCheck('TIINGO_API_KEY', 'x'.repeat(1025))).toMatch(/1,024/);
    expect(keyCheck('ALPACA_API_KEY_ID', 'AK123')).toMatch(/start with PK/);
    expect(keyCheck('ALPACA_API_KEY_ID', 'PK123')).toBeNull();
    expect(keyCheck('DESK_CLAUDE_TOKEN_EXPIRES', 'next year')).toMatch(/2027-11-03/);
  });

  it('words refusals', () => {
    expect(keyRefusal({ body: { error: 'host_down' } })).toMatch(/checked in/);
    expect(keyRefusal({ body: { error: 'refused', message: 'Live keys never.' } })).toBe('Live keys never.');
  });
});

describe('compose', () => {
  it('offers Apply only for a safe drift', () => {
    expect(composeView(null)).toBeNull();
    expect(composeView({ state: 'current' })).toBeNull();
    expect(composeView({ state: 'drift', can_apply: true, drift: ['api: environment'] }).state).toBe('apply');
    const eyes = composeView({ state: 'drift', can_apply: false, drift: ['cron: cap_add'], escalations: ['cron: new cap_add SYS_ADMIN'], missing_files: ['/mnt/x.json'], copy_available: true });
    expect(eyes).toMatchObject({ state: 'eyes', needs: ['cron: new cap_add SYS_ADMIN', 'needs /mnt/x.json'], copy: true });
    expect(composeView({ state: 'unknown' }).state).toBe('unknown');
  });
});

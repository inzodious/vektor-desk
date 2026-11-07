import { describe, expect, it } from 'vitest';
import { marketState } from './clock.js';

const at = (iso) => marketState(new Date(iso));

describe('market clock', () => {
  it('is open during the regular session', () => {
    expect(at('2026-11-09T16:42:00Z').state).toBe('open');
    expect(at('2026-11-09T14:30:00Z').state).toBe('open');
  });

  it('knows pre-market and after hours', () => {
    expect(at('2026-11-09T14:29:00Z').state).toBe('pre');
    expect(at('2026-11-09T21:00:00Z').state).toBe('after');
    expect(at('2026-11-10T02:00:00Z').state).toBe('closed');
  });

  it('closes on weekends and holidays', () => {
    const sat = at('2026-11-07T16:00:00Z');
    expect(sat.state).toBe('closed');
    expect(sat.hint).toBe('Opens Mon 9:30 AM ET');
    const thanks = at('2026-11-26T16:00:00Z');
    expect(thanks.label).toBe('Market holiday');
    expect(thanks.hint).toBe('Opens tomorrow 9:30 AM ET');
  });

  it('handles early closes', () => {
    expect(at('2026-11-27T17:30:00Z').state).toBe('open');
    expect(at('2026-11-27T18:30:00Z').state).toBe('after');
  });

  it('follows daylight saving time', () => {
    expect(at('2026-07-08T13:45:00Z').state).toBe('open');
    expect(at('2026-07-08T13:15:00Z').state).toBe('pre');
  });
});

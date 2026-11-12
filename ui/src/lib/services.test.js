import { describe, expect, it } from 'vitest';
import { servicesView } from './services.js';
import ok from '../fixtures/status.json';
import trouble from '../fixtures/status.trouble.json';

const now = new Date('2026-11-09T16:42:00Z');

describe('services card', () => {
  it('draws nothing when the desk sends no services', () => {
    expect(servicesView(undefined)).toBeNull();
    expect(servicesView({})).toBeNull();
  });

  it('lists every service as up with the desk sentence', () => {
    const v = servicesView(ok.containers, now);
    expect(v).toMatchObject({ chip: 'All running', tone: 'ok', note: 'All 5 desk services are running.' });
    expect(v.rows.map((r) => r.title)).toEqual(['The app', 'The scheduler', 'The web server', 'Phone alerts', 'The Tailscale link']);
    expect(v.rows.every((r) => r.t === 'Up' && r.dot === 'ok')).toBe(true);
    expect(v.rows[0].words).toBe('The app has been running for 3 hours.');
    expect(v.link).toBeNull();
    expect(v.checked).toMatch(/^Checked .* ET$/);
  });

  it('flags the service that is down and says the Tailscale sentence once', () => {
    const v = servicesView(trouble.containers, now);
    expect(v).toMatchObject({ chip: 'Needs a look', tone: 'watch' });
    expect(v.rows.at(-1)).toMatchObject({ title: 'The Tailscale link', t: 'Restarting', tone: 'watch' });
    expect(v.note).toContain('The box is signed out of your tailnet.');
    expect(v.link).toBeNull();
    const other = servicesView({ ...trouble.containers, note: 'Phone alerts stopped with an error.' }, now);
    expect(other.link).toBe('The box is signed out of your tailnet. Add a new auth key in Settings, then Redeploy.');
    expect(JSON.stringify(v)).not.toContain('login-state');
    expect(JSON.stringify(v)).not.toContain('vektor-desk-');
  });

  it('reads a box that has not reported and unknown states plainly', () => {
    const v = servicesView({ state: 'unknown', note: 'The box hasn’t reported its services yet.', services: [{ name: 'lab', title: 'the lab', state: 'paused', words: '{"raw": 1}' }], tailnet: { state: 'unknown', words: 'x' } }, now);
    expect(v).toMatchObject({ chip: 'Not reported', tone: '', checked: null, link: null });
    expect(v.rows[0]).toMatchObject({ title: 'The lab', t: 'Unknown', words: null });
  });
});

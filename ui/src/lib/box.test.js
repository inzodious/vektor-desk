import { describe, expect, it } from 'vitest';
import { boxBusy, boxRefusal, boxState, lastLine, scriptView, splitBox } from './box.js';

const NOW = new Date('2026-11-09T16:42:00Z');
const run = (o) => ({ action: 'backup', request_id: 'x', started: '2026-11-09T12:00:00Z', finished: '2026-11-09T12:04:00Z', result: 'ok', exit_code: 0, output: 'one\ntwo\n', ...o });

describe('box helpers', () => {
  it('keeps Update box script out of the main list', () => {
    const { list, update } = splitBox([{ name: 'redeploy' }, { name: 'update-script' }]);
    expect(list.map((a) => a.name)).toEqual(['redeploy']);
    expect(update.name).toBe('update-script');
  });

  it('words each state', () => {
    expect(boxState({ name: 'backup', last_run: null }, NOW).state).toBe('never');
    expect(boxState({ name: 'backup', queued: true }, NOW).line).toMatch(/^Queued, runs within 5 min/);
    expect(boxState({ name: 'backup', running: true, last_run: run({ finished: null }) }, NOW).state).toBe('running');
    expect(boxState({ name: 'backup', last_run: run() }, NOW)).toEqual({ state: 'ok', line: 'Ran 7:04 AM' });
    expect(boxState({ name: 'update-script', last_run: run({ result: 'updated' }) }, NOW).state).toBe('ok');
    expect(boxState({ name: 'backup', last_run: run({ result: 'failed', exit_code: 2 }) }, NOW).line).toBe('Didn’t finish 7:04 AM (exit 2)');
    expect(boxState({ name: 'update-script', last_run: run({ result: 'skipped' }) }, NOW).line).toMatch(/catching up/);
    expect(boxState({ name: 'backup', last_run: run({ started: '2026-11-09T10:00:00Z', finished: null, result: null }) }, NOW).state).toBe('failed');
  });

  it('reads the script copy', () => {
    expect(scriptView(null)).toBeNull();
    expect(scriptView({ current: true }).state).toBe('current');
    expect(scriptView({ current: false, behind: 1, from: 'abcdef123', to: '987654fed' })).toEqual({ state: 'behind', line: 'The box script is 1 commit behind main.', range: 'abcdef1 → 987654f' });
    expect(scriptView({ current: false, behind: null }).line).toMatch(/doesn’t match/);
    expect(scriptView({ current: false, off: true }).state).toBe('off');
  });

  it('turns refusals into plain words', () => {
    expect(boxRefusal({ body: { error: 'cooldown', cooldown_until: '2026-11-09T17:10:00Z' } }, NOW)).toBe('Ran a moment ago. Try again at 12:10 PM.');
    expect(boxRefusal({ body: { error: 'queued' } })).toBe('Already queued. Runs within 5 min.');
    expect(boxRefusal({ body: { error: 'host_down' } })).toMatch(/one-time step/);
    expect(boxRefusal({ message: 'nope', body: {} })).toBe('nope');
  });

  it('knows when to poll fast and reads the last line', () => {
    expect(boxBusy({ actions: [{ queued: true }] })).toBe(true);
    expect(boxBusy({ actions: [{ last_run: run() }] })).toBe(false);
    expect(lastLine(run({ output: 'Box script updated from abc1234 to def5678\n' }))).toBe('Box script updated from abc1234 to def5678');
    expect(lastLine(run({ output: null }))).toBeNull();
  });
});

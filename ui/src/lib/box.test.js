import { describe, expect, it } from 'vitest';
import { BUILDER_START, boxBusy, boxRefusal, boxState, buildView, lastLine, scriptView, settleLine, shortKey, splitBox } from './box.js';

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

describe('builds', () => {
  const PRINT = `3d63e0705ff21e2b${'0123456789abcdef'.repeat(3)}`;
  const block = (o) => ({ state: 'none', words: 'The box builds its own images, one stage at a time. The last image (716e203) came from this box.', builders: [], asking: [], listed: [], want: null, last: null, wait_seconds: 1200, settle_seconds: 600, host_seen: true, ...o });
  const action = { name: 'approve-builder', running: false, queued: false, last_run: null };

  it('keeps Approve builder out of the main list', () => {
    const { list, approve } = splitBox([{ name: 'redeploy' }, { name: 'approve-builder' }]);
    expect(list.map((a) => a.name)).toEqual(['redeploy']);
    expect(approve.name).toBe('approve-builder');
    expect(splitBox([{ name: 'redeploy' }]).approve).toBeNull();
  });

  it('shows nothing without a block or before the box has its new script', () => {
    expect(buildView(null, action)).toBeNull();
    expect(buildView({ state: 'later' }, action)).toBeNull();
    expect(buildView(block({ host_seen: false }), action)).toBeNull();
  });

  it('splits the desk’s words into a head and the rest', () => {
    const v = buildView(block(), action);
    expect(v).toMatchObject({ state: 'none', tone: 'calm', head: 'The box builds its own images, one stage at a time.', rest: 'The last image (716e203) came from this box.', approve: false, start: true, script: null, stale: null });
    expect(buildView(block({ words: 'One sentence only.' }), action)).toMatchObject({ head: 'One sentence only.', rest: null });
    expect(BUILDER_START.split('\n')).toEqual(['git pull --ff-only', 'DESK_BUILD=$(git rev-parse HEAD) docker compose -f deploy/worker/compose.yaml --profile builder up -d --build']);
  });

  it('gives the line for main when a machine asks', () => {
    const v = buildView(block({ state: 'asking', asking: [{ fingerprint: PRINT, name: 'Horizon', asked_at: '2026-11-09T16:40:00Z' }, { fingerprint: 'short', name: 'Bad' }] }), action);
    expect(v.tone).toBe('ask');
    expect(v.asking).toEqual([{ print: PRINT, name: 'Horizon', key: '3d63 e070 5ff2 1e2b', line: `${PRINT} Horizon` }]);
    expect(v.approve).toBe(false);
    expect(v.start).toBe(false);
    expect(shortKey(PRINT)).toBe('3d63 e070 5ff2 1e2b');
    expect(buildView(block({ state: 'asking', host_seen: false, asking: [{ fingerprint: PRINT, name: 'Horizon' }] }), action).script).toMatch(/Update box script comes first/);
  });

  it('offers Approve builder when main lists a builder, and never repeats its line', () => {
    const v = buildView(block({ state: 'approve', asking: [{ fingerprint: PRINT, name: 'Horizon' }], listed: [{ fingerprint: PRINT, name: 'Horizon', approved: false }] }), action);
    expect(v).toMatchObject({ tone: 'tap', approve: true, asking: [] });
    expect(buildView(block({ state: 'approve' }), null).approve).toBe(false);
  });

  it('keeps the button away once a builder is approved, unless it is running or main dropped the builder', () => {
    const online = block({ state: 'online', builders: [{ fingerprint: PRINT, name: 'Horizon', online: true }], listed: [{ fingerprint: PRINT, name: 'Horizon', approved: true }] });
    expect(buildView(online, action)).toMatchObject({ tone: 'calm', approve: false, stale: null });
    expect(buildView(online, { ...action, queued: true }).approve).toBe(true);
    const dropped = buildView({ ...online, listed: [] }, action);
    expect(dropped).toMatchObject({ tone: 'tap', approve: true });
    expect(dropped.stale).toBe('Horizon is no longer listed in main. Approve builder stops the box taking its images.');
  });

  it('says how long a deploy waits', () => {
    expect(settleLine(block())).toBe('A new version goes in by itself once main has been quiet for 10 minutes; Deploy now skips the wait.');
    expect(settleLine(block({ settle_seconds: 60 }))).toMatch(/quiet for 1 minute;/);
    expect(settleLine(block({ settle_seconds: 0 }))).toBeNull();
    expect(settleLine(block({ settle_seconds: null }))).toBeNull();
    expect(settleLine(undefined)).toBeNull();
  });
});

import { etDate, etTime } from './format.js';

export const HAND_COPY = 'install -m 700 /mnt/Manifest/apps/vektor-desk-src/deploy/deploy.sh /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh';
export const QUEUED_TEXT = 'Queued, runs within 5 min';
const STALE_MS = 2 * 60 * 60 * 1000;

// ---------- time ----------
export function when(iso, now = new Date()) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return etDate(now) === etDate(d) ? etTime(d) : `${etDate(d)}, ${etTime(d)}`;
}

const short = (sha) => (sha ? String(sha).slice(0, 7) : null);

// ---------- actions ----------
export function splitBox(actions = []) {
  const list = (actions || []).filter((a) => a.name !== 'update-script');
  const update = (actions || []).find((a) => a.name === 'update-script') || null;
  return { list, update };
}

export function lastLine(run) {
  const out = typeof run?.output === 'string' ? run.output : Array.isArray(run?.output) ? run.output.join('\n') : '';
  const lines = out.split('\n').map((l) => l.trim()).filter(Boolean);
  return lines.length ? lines[lines.length - 1] : null;
}

export function boxState(a, now = new Date()) {
  if (!a) return { state: 'unknown', line: '' };
  const last = a.last_run;
  if (a.running) return { state: 'running', line: `Running since ${when(last?.started, now) || 'just now'}` };
  if (a.queued) return { state: 'queued', line: `${QUEUED_TEXT}${a.queued_at ? ` · asked ${when(a.queued_at, now)}` : ''}` };
  if (!last) return { state: 'never', line: 'Not run from here yet' };
  const at = when(last.finished || last.started, now);
  if (!last.finished) {
    const old = last.started && now - new Date(last.started) > STALE_MS;
    return old ? { state: 'failed', line: `Started ${at} and never reported back` } : { state: 'running', line: `Running since ${at}` };
  }
  if (last.result === 'ok' || last.result === 'updated') return { state: 'ok', line: `Ran ${at}` };
  if (last.result === 'skipped') return { state: 'skipped', line: a.name === 'update-script' ? `Skipped ${at}: the box checkout is still catching up to main` : `Skipped ${at}: the box was busy` };
  return { state: 'failed', line: `Didn’t finish ${at}${last.exit_code != null ? ` (exit ${last.exit_code})` : ''}` };
}

export function cooldownText(a, now = new Date()) {
  return a?.cooldown_until ? `Again at ${when(a.cooldown_until, now)}` : null;
}

export function boxBusy(d) {
  return (d?.actions || []).some((a) => a.running || a.queued || (a.last_run && !a.last_run.finished));
}

// ---------- script ----------
export function scriptView(script) {
  if (!script) return null;
  const range = script.from && script.to ? `${short(script.from)} → ${short(script.to)}` : null;
  if (script.current) return { state: 'current', line: 'The box script matches main.', range: null };
  if (script.off) return { state: 'off', line: 'Self-update is off on this box, so the script waits for a hand copy.', range };
  const lag = script.behind == null ? 'The box script doesn’t match a commit on main.' : `The box script is ${script.behind} ${script.behind === 1 ? 'commit' : 'commits'} behind main.`;
  return { state: 'behind', line: lag, range };
}

// ---------- refusals ----------
export function boxRefusal(err, now = new Date()) {
  const b = err?.body || {};
  if (b.error === 'cooldown') return `Ran a moment ago. ${b.cooldown_until ? `Try again at ${when(b.cooldown_until, now)}.` : 'Try again in a few minutes.'}`;
  if (b.error === 'queued') return `Already queued. ${QUEUED_TEXT.replace('Queued, r', 'R')}.`;
  if (b.error === 'running') return 'Already running. The result shows here when it’s done.';
  if (b.error === 'host_down') return 'The box hasn’t checked in, so nothing would pick this up yet. See the one-time step above.';
  if (b.error === 'unknown_action') return 'The desk doesn’t know that action any more. Refresh the page.';
  return err?.message || 'The desk didn’t take that. Try again in a moment.';
}

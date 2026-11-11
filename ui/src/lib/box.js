import { etDate, etTime } from './format.js';

export const HAND_COPY = 'install -m 700 /mnt/Manifest/apps/vektor-desk-src/deploy/deploy.sh /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh';
export const QUEUED_TEXT = 'Queued, runs within 5 min';
export const BUILDER_START = ['git pull --ff-only', 'DESK_BUILD=$(git rev-parse HEAD) docker compose -f deploy/worker/compose.yaml --profile builder up -d --build'].join('\n');
const STALE_MS = 2 * 60 * 60 * 1000;
const OWN_PLACE = ['update-script', 'apply-compose', 'approve-builder'];
const BUILD_STATES = ['none', 'asking', 'approve', 'online', 'asleep'];
const PRINT = /^[0-9a-f]{64}$/;

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
  const list = (actions || []).filter((a) => !OWN_PLACE.includes(a.name));
  const update = (actions || []).find((a) => a.name === 'update-script') || null;
  const compose = (actions || []).find((a) => a.name === 'apply-compose') || null;
  const approve = (actions || []).find((a) => a.name === 'approve-builder') || null;
  return { list, update, compose, approve };
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

// ---------- compose ----------
export function composeView(c) {
  if (!c || c.state === 'current') return null;
  if (c.state === 'unknown') return { state: 'unknown', line: 'The box couldn’t compare its compose file with main. Box → Status shows why.', drift: [], needs: [] };
  const needs = [...(c.escalations || []), ...(c.missing_files || []).map((f) => `needs ${f}`)];
  return {
    state: c.can_apply ? 'apply' : 'eyes',
    line: c.can_apply ? 'The compose file changed on main. Apply it and TrueNAS picks it up after a backup.' : 'The compose file changed on main, and the change needs your eyes before it goes in.',
    drift: c.drift || [],
    needs,
    copy: !!c.copy_available,
  };
}

// ---------- builds ----------
export function shortKey(print) {
  const p = String(print || '').slice(0, 16);
  return p.match(/.{1,4}/g)?.join(' ') || '';
}

function sentences(words) {
  const text = String(words || '').trim();
  const cut = text.indexOf('. ');
  return cut < 0 ? [text, null] : [text.slice(0, cut + 1), text.slice(cut + 2).trim() || null];
}

function names(list) {
  return list.length > 1 ? `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}` : list[0];
}

export function buildView(build, action) {
  if (!build || typeof build !== 'object' || !BUILD_STATES.includes(build.state)) return null;
  const state = build.state;
  if (state === 'none' && !build.host_seen) return null;
  const listed = (build.listed || []).filter((l) => l && PRINT.test(l.fingerprint));
  const isListed = (print) => listed.some((l) => l.fingerprint === print);
  const asking = (build.asking || []).filter((a) => a && PRINT.test(a.fingerprint) && !isListed(a.fingerprint)).map((a) => ({ print: a.fingerprint, name: a.name || 'A machine', key: shortKey(a.fingerprint), line: `${a.fingerprint} ${a.name || 'builder'}` }));
  const gone = (build.builders || []).filter((b) => b && !isListed(b.fingerprint)).map((b) => b.name || 'A builder');
  const stale = gone.length ? `${names(gone)} ${gone.length > 1 ? 'are' : 'is'} no longer listed in main. Approve builder stops the box taking ${gone.length > 1 ? 'their' : 'its'} images.` : null;
  const live = !!action && (action.running || action.queued || (!!action.last_run && !action.last_run.finished));
  const tap = state === 'approve' || !!stale || listed.some((l) => !l.approved);
  const [head, rest] = sentences(build.words);
  return {
    state,
    tone: tap ? 'tap' : state === 'asking' ? 'ask' : 'calm',
    head: head || 'Who builds the desk’s images',
    rest,
    asking,
    stale,
    approve: !!action && (tap || live),
    script: build.host_seen ? null : 'The box needs its new script before it can list or approve a builder. Update box script comes first.',
    start: state === 'none',
  };
}

export function settleLine(build) {
  const m = Math.round(Number(build?.settle_seconds) / 60);
  if (!Number.isFinite(m) || m <= 0) return null;
  return `A new version goes in by itself once main has been quiet for ${m} ${m === 1 ? 'minute' : 'minutes'}; Deploy now skips the wait.`;
}

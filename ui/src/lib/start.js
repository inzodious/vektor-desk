const ENDED = ['ok', 'failed', 'skipped'];
const STEP_WORD = {
  waiting: { t: 'Waiting', tone: '' },
  running: { t: 'Working', tone: 'ok' },
  ok: { t: 'Done', tone: 'ok' },
  failed: { t: 'Didn’t finish', tone: 'watch' },
  skipped: { t: 'Skipped', tone: '' },
};
const NEVER_LINE = 'One press pulls your accounts, runs today’s numbers and writes your first results. It takes a few minutes, and you can leave the page.';

// ---------- steps ----------
const TURN = /^Waiting for its turn/;
export const inTurn = (step) => step?.state === 'running' && (step.waiting === true || TURN.test(step.detail || ''));
export const stepWord = (step) => (inTurn(step) ? { t: 'Waiting its turn', tone: '' } : STEP_WORD[step?.state] || STEP_WORD.waiting);
export const needsYou = (step) => step?.state === 'failed' || (step?.state === 'skipped' && Boolean(step.fix));

export function stepTook(step) {
  if (step?.state !== 'ok' || !step.started_at || !step.finished_at) return null;
  const s = Math.round((new Date(step.finished_at) - new Date(step.started_at)) / 1000);
  if (!Number.isFinite(s) || s < 0) return null;
  if (s < 60) return `${Math.max(1, s)} s`;
  return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`;
}

// ---------- the chain ----------
export function startView(data) {
  const steps = Array.isArray(data?.steps) ? data.steps : [];
  if (!data || !steps.length) return { mode: 'none', show: false, steps: [], total: 0, ended: 0, share: 0, needs: [], canStart: false, head: null, line: null, button: null, blocked: null, blockedFix: null };
  const total = steps.length;
  const ended = steps.filter((s) => ENDED.includes(s.state)).length;
  const at = steps.findIndex((s) => s.state === 'running');
  const needs = steps.filter(needsYou);
  const mode = data.state === 'running' ? 'running' : data.needs_start === false ? 'ok' : data.state === 'idle' ? 'never' : 'partial';
  const blocked = mode !== 'running' && data.can_start === false ? data.blocked?.message || 'The desk can’t start right now.' : null;
  const blockedFix = blocked && data.blocked?.error === 'scheduler_down' ? { to: '/settings/box', label: 'Open Box' } : null;
  const base = { mode, blockedFix, steps, total, ended, share: total ? ended / total : 0, needs, canStart: data.can_start !== false && mode !== 'running', blocked, finishedAt: data.finished_at || null };
  if (mode === 'running') {
    const now = at >= 0 ? `Step ${at + 1} of ${total}: ${steps[at].title}` : data.summary || `${ended} of ${total} steps done`;
    return { ...base, show: true, head: 'Starting the desk', line: `${now}. You can leave and come back.`, short: now, button: null };
  }
  if (mode === 'never') return { ...base, show: true, head: 'The desk hasn’t run yet', line: NEVER_LINE, short: 'Nothing has run, so every page is waiting.', button: 'Start the desk' };
  if (mode === 'partial') {
    const line = data.summary || `${ended - needs.length} of ${total} steps done. ${needs.length} need you.`;
    return { ...base, show: true, head: 'The desk ran, with a few loose ends', line, short: line, button: 'Start again' };
  }
  return { ...base, show: false, head: 'The desk is up', line: 'Every page fills in from here, and the schedule keeps it fresh.', short: 'Every page fills in from here.', button: null };
}

export function startRefusal(err) {
  const body = err?.body || {};
  if (body.error === 'running') return null;
  if (typeof body.message === 'string' && body.message) return body.message;
  if (body.error === 'scheduler_down') return 'The scheduler is off, so nothing would pick this up. Settings → Box can restart it.';
  if (err?.status === 404) return 'This button switches on with the next desk update.';
  return err?.message || 'The desk didn’t take that. Try again in a moment.';
}

// ---------- readiness ----------
export function readinessMap(data) {
  return Object.fromEntries((data?.sections || []).filter((s) => s?.key).map((s) => [s.key, s]));
}

export function gapOf(map, key) {
  const s = map?.[key];
  return s && s.state && s.state !== 'ready' ? s : null;
}

export function gapWords(gap, { why, action } = {}) {
  const act = gap?.action || action || null;
  return {
    state: gap?.state || 'unknown',
    why: gap?.why || why || null,
    action: act && ['start', 'job', 'link'].includes(act.kind) ? act : null,
    auto: gap?.next_auto_text ? `Fills by itself ${gap.next_auto_text}.` : null,
  };
}

export function setupChip(score) {
  if (!score || !score.total || score.left <= 0) return null;
  return { text: `Setup · ${score.left} left`, short: `${score.left} left`, label: `Setup: ${score.left} of ${score.total} steps left. Open the first-run checklist.` };
}

export const FIRST_RUN = { kind: 'link', to: '/settings/first-run', label: 'Open the checklist' };

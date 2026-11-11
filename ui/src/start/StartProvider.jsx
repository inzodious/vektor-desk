import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { postJson, useApi } from '../lib/api.js';
import { firstRunScore, firstRunSteps } from '../lib/firstrun.js';
import { readinessMap, startRefusal, startView } from '../lib/start.js';
import { StartContext } from './context.js';

const HIDE_KEY = 'desk.start.hidden';
const RUNNING_MS = 3000;
const IDLE_MS = 60000;

function readHidden() {
  try {
    return window.localStorage.getItem(HIDE_KEY);
  } catch {
    return null;
  }
}

function useSetup() {
  const status = useApi('/api/status');
  const jobs = useApi('/api/jobs');
  const health = useApi('/api/engine/health');
  const profile = useApi('/api/decisions/profile/status');
  const agents = useApi('/api/agents/status');
  const board = useApi('/api/engine/lab/leaderboard');
  const risk = useApi('/api/decisions/risk');
  const steps = firstRunSteps({ status, jobs, health, profile, agents, board, risk });
  const loading = steps.some((s) => s.state === 'loading');
  const score = loading ? null : firstRunScore(steps);
  const [a, b, c, d, e, f, g] = [status.reload, jobs.reload, health.reload, profile.reload, agents.reload, board.reload, risk.reload];
  const reload = useCallback(() => [a, b, c, d, e, f, g].forEach((r) => r()), [a, b, c, d, e, f, g]);
  return { score, reload };
}

export function StartProvider({ children }) {
  const [posted, setPosted] = useState(null);
  const api = useApi('/api/start', { every: (d) => ((posted || d)?.state === 'running' ? RUNNING_MS : IDLE_MS) });
  const ready = useApi('/api/readiness', { every: IDLE_MS * 2 });
  const setup = useSetup();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [justDone, setJustDone] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [hiddenAt, setHiddenAt] = useState(readHidden);
  const raw = posted && api.data?.state !== 'running' && api.data?.started_at !== posted.started_at ? posted : api.data || posted;
  const view = useMemo(() => startView(raw), [raw]);
  const readiness = useMemo(() => readinessMap(ready.data), [ready.data]);
  const memory = raw?.memory || ready.data?.memory || null;
  const was = useRef(null);
  const reloadStart = api.reload;
  const reloadReady = ready.reload;
  const reloadSetup = setup.reload;

  const refresh = useCallback(() => {
    reloadReady();
    reloadSetup();
    setEpoch((n) => n + 1);
  }, [reloadReady, reloadSetup]);

  useEffect(() => {
    if (was.current === 'running' && view.mode !== 'running' && view.mode !== 'none') {
      setJustDone(true);
      setPosted(null);
      refresh();
    }
    was.current = view.mode;
  }, [view.mode, refresh]);

  useEffect(() => {
    if (view.mode === 'running') reloadReady();
  }, [view.mode, view.ended, reloadReady]);

  const begin = useCallback(async () => {
    setBusy(true);
    setError(null);
    setJustDone(false);
    try {
      const body = await postJson('/api/start');
      if (body && Array.isArray(body.steps)) setPosted(body);
    } catch (e) {
      setError(startRefusal(e));
    }
    reloadStart();
    setBusy(false);
  }, [reloadStart]);

  const dismiss = useCallback(() => setJustDone(false), []);
  const finishedAt = view.finishedAt;
  const hide = useCallback(() => {
    setHiddenAt(finishedAt);
    try {
      window.localStorage.setItem(HIDE_KEY, finishedAt || '');
    } catch {
      return;
    }
  }, [finishedAt]);
  const hidden = view.mode === 'partial' && Boolean(finishedAt) && hiddenAt === finishedAt;

  const value = useMemo(
    () => ({ view, readiness, known: Boolean(ready.data || ready.error), begin, busy, error, justDone, dismiss, hide, hidden, refresh, reloadSetup, setup: setup.score, epoch, memory, recheck: reloadStart }),
    [view, readiness, ready.data, ready.error, begin, busy, error, justDone, dismiss, hide, hidden, refresh, reloadSetup, setup.score, epoch, memory, reloadStart],
  );
  return <StartContext.Provider value={value}>{children}</StartContext.Provider>;
}

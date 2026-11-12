import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon.jsx';
import { useApi } from '../lib/api.js';
import { healthAlert } from '../lib/health.js';
import { autoPlan, jobWord, runAndWait } from '../lib/jobs.js';

const KEY = 'desk.refresh.auto';

function readStamps() {
  try {
    const raw = JSON.parse(window.localStorage.getItem(KEY) || '{}');
    return raw && typeof raw === 'object' ? raw : {};
  } catch {
    return {};
  }
}

function stamp(name) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...readStamps(), [name]: Date.now() }));
  } catch {
    return;
  }
}

export function HealthWatch() {
  const api = useApi('/api/engine/health', { every: 600000 });
  const stale = api.data?.status === 'warn' || api.data?.status === 'fail';
  const jobs = useApi(stale ? '/api/jobs' : null);
  const [running, setRunning] = useState(null);
  const busy = useRef(false);
  const ctl = useRef(null);
  useEffect(() => {
    ctl.current = new AbortController();
    return () => ctl.current.abort();
  }, []);

  // ---------- refresh by itself ----------
  const health = api.data;
  const board = jobs.data;
  const reloadHealth = api.reload;
  const reloadJobs = jobs.reload;
  useEffect(() => {
    if (!stale || busy.current || !board?.scheduler_alive) return;
    const due = autoPlan(health, board.jobs, readStamps(), Date.now());
    if (!due.length) return;
    busy.current = true;
    (async () => {
      try {
        for (const name of due) {
          stamp(name);
          setRunning(jobWord({ name }).title.toLowerCase());
          const last = await runAndWait(name, { signal: ctl.current.signal });
          if (last?.result === 'failed') break;
        }
      } catch {
        busy.current = false;
        setRunning(null);
        return;
      }
      busy.current = false;
      setRunning(null);
      reloadHealth();
      reloadJobs();
    })();
  }, [stale, health, board, reloadHealth, reloadJobs]);

  const b = healthAlert(health);
  if (!b) return null;
  return (
    <section className="health-banner fail" role="alert" data-testid="health-banner" data-level="fail">
      <Icon name="info" />
      <div className="hb-body">
        <p>
          <b>{b.head}</b> <span>{b.fix}</span>
        </p>
      </div>
      {running ? (
        <span className="chip ok" role="status" data-testid="refresh-status">
          <i className="pulse" style={{ width: 6, height: 6 }} />
          Refreshing {running}…
        </span>
      ) : null}
    </section>
  );
}

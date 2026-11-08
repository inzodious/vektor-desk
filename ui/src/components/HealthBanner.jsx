import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon.jsx';
import { useApi } from '../lib/api.js';
import { healthBanner } from '../lib/health.js';
import { jobWord, refreshPlan, refusalText, runAndWait } from '../lib/jobs.js';

const KEY = 'desk.health.dismissed';

function readDismissed() {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function HealthBanner() {
  const api = useApi('/api/engine/health', { every: 600000 });
  const [dismissed, setDismissed] = useState(readDismissed);
  const b = healthBanner(api.data);
  const jobs = useApi(b ? '/api/jobs' : null);
  const [run, setRun] = useState({ phase: 'idle', text: null });
  const ctl = useRef(null);
  useEffect(() => {
    ctl.current = new AbortController();
    return () => ctl.current.abort();
  }, []);
  if (!b || (b.level === 'warn' && dismissed === b.key)) return null;
  const plan = jobs.data?.scheduler_alive ? refreshPlan(api.data, jobs.data.jobs) : [];
  const title = (name) => jobWord({ name }).title;
  const refresh = async () => {
    try {
      for (const name of plan) {
        setRun({ phase: 'running', text: `Refreshing ${title(name).toLowerCase()}…` });
        const last = await runAndWait(name, { signal: ctl.current.signal });
        if (last?.result === 'failed') {
          setRun({ phase: 'failed', text: `${title(name)} didn’t finish${last.detail ? `: ${last.detail}` : '.'} Settings › Jobs has the rest.` });
          return;
        }
      }
      setRun({ phase: 'done', text: 'Fresh data is in.' });
      api.reload();
      jobs.reload();
    } catch (e) {
      if (e.name !== 'AbortError') setRun({ phase: 'refused', text: refusalText(e) });
    }
  };
  const hide = () => {
    setDismissed(b.key);
    try {
      window.localStorage.setItem(KEY, b.key);
    } catch {
      return;
    }
  };
  return (
    <section className={`health-banner ${b.level}`} role={b.level === 'fail' ? 'alert' : 'status'} data-testid="health-banner" data-level={b.level}>
      <Icon name="info" />
      <div className="hb-body">
        <p>
          <b>{b.head}</b> <span>{b.fix}</span>
        </p>
        {b.others.length ? (
          <details>
            <summary>{b.others.length === 1 ? '1 more check' : `${b.others.length} more checks`}</summary>
            <ul>
              {b.others.map((o) => (
                <li key={o.name} data-status={o.status}>
                  <b>{o.name}:</b> {o.detail}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
      <div className="hb-acts">
        {plan.length ? (
          run.phase === 'running' ? (
            <span className="chip ok" role="status" data-testid="refresh-status">
              <i className="pulse" style={{ width: 6, height: 6 }} />
              {run.text}
            </span>
          ) : (
            <button className="btn sm" type="button" data-testid="refresh-data" title={`Runs ${plan.map((n) => title(n).toLowerCase()).join(', then ')}`} onClick={refresh}>
              <Icon name="swap" />
              Refresh data
            </button>
          )
        ) : null}
        {run.phase !== 'idle' && run.phase !== 'running' ? (
          <small className={`hb-note ${run.phase}`} role="status" data-testid="refresh-status">
            {run.text}
          </small>
        ) : null}
        {b.level === 'warn' ? (
          <button className="link" type="button" onClick={hide}>
            Hide until the next run
          </button>
        ) : null}
      </div>
    </section>
  );
}

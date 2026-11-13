import { useEffect, useRef, useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { useApi } from '../lib/api.js';
import { cooldownText, jobState, jobWord, refusalText, runAndWait, scheduleWords, splitJobs } from '../lib/jobs.js';
import { plural } from '../lib/format.js';
import { About } from '../components/About.jsx';

const busy = (d) => (d?.jobs || []).some((j) => j.running || j.queued || j.waiting);

function JobRow({ job, alive, mine, onRun }) {
  const word = jobWord(job);
  const st = jobState(job);
  const turn = st.state === 'waiting';
  const live = st.state === 'running' || st.state === 'queued' || turn || mine?.phase === 'waiting';
  const cool = cooldownText(job);
  const shown = turn ? 'waiting' : mine?.phase === 'done' ? 'ok' : mine?.phase === 'failed' ? 'failed' : live ? 'running' : st.state;
  return (
    <div className="job-row" data-job={job.name} data-state={shown}>
      <span className={`job-dot ${shown}`} aria-hidden="true" />
      <span className="job-text">
        <b>{word.title}</b>
        <small>{st.line}</small>
        {st.did ? (
          <small className="job-did" data-testid="job-did">
            {st.did}
          </small>
        ) : null}
        <small className="job-when">{scheduleWords(job)}</small>
        {mine?.text ? (
          <small className={`job-note ${mine.phase}`} role="status">
            {mine.text}
          </small>
        ) : null}
      </span>
      <span className="job-act">
        {turn ? (
          <span className="chip">Waiting</span>
        ) : live ? (
          <span className="chip ok">
            <i className="pulse" style={{ width: 6, height: 6 }} />
            {st.state === 'queued' || (mine?.phase === 'waiting' && !job.running) ? 'Starting' : 'Running'}
          </span>
        ) : (
          <button className="btn ghost sm" type="button" disabled={!alive || !job.can_run} title={cool || (alive ? `Run ${word.title} now` : 'The scheduler is off')} aria-label={`Run ${word.title} now`} onClick={() => onRun(job)}>
            <Icon name="play" />
            {cool && alive ? cool : 'Run now'}
          </button>
        )}
      </span>
    </div>
  );
}

export function Jobs() {
  const api = useApi('/api/jobs', { every: (d) => (busy(d) ? 3000 : 30000) });
  const [mine, setMine] = useState({});
  const ctl = useRef(null);
  useEffect(() => {
    ctl.current = new AbortController();
    return () => ctl.current.abort();
  }, []);
  const d = api.data;
  const card = useRef(null);
  const ready = Boolean(d);
  useEffect(() => {
    if (ready && window.location.hash === '#jobs') card.current?.scrollIntoView({ block: 'start' });
  }, [ready]);
  const alive = !!d?.scheduler_alive;
  const split = splitJobs(d?.jobs);
  const main = [...split.main, ...split.rest.filter((j) => j.waiting)];
  const rest = split.rest.filter((j) => !j.waiting);
  const running = (d?.jobs || []).filter((j) => j.running || j.queued).length;
  const turns = (d?.jobs || []).filter((j) => j.waiting && !j.running).length;
  const low = d?.low_memory?.on ? d.low_memory : null;

  const set = (name, v) => setMine((m) => ({ ...m, [name]: v }));
  const run = async (job) => {
    const title = jobWord(job).title;
    set(job.name, { phase: 'waiting', text: null });
    try {
      const last = await runAndWait(job.name, { signal: ctl.current.signal, onState: () => api.reload() });
      if (last?.result === 'failed') set(job.name, { phase: 'failed', text: `${title} didn’t finish${last.detail ? `: ${last.detail}` : '.'}` });
      else if (last?.result === 'skipped') set(job.name, { phase: 'skipped', text: `${title} skipped${last.detail ? `: ${last.detail}` : '.'}` });
      else set(job.name, { phase: 'done', text: `${title} done. Fresh numbers are in.` });
    } catch (e) {
      if (e.name === 'AbortError') return;
      set(job.name, { phase: 'refused', text: refusalText(e) });
    }
    api.reload();
  };

  const rows = (list) => list.map((j) => <JobRow key={j.name} job={j} alive={alive} mine={mine[j.name]} onRun={run} />);

  return (
    <div className="card c12" id="jobs" ref={card} style={{ '--i': 3 }} data-testid="jobs" data-alive={d ? String(alive) : undefined}>
      <div className="card-head">
        <span className="tag mint">Jobs</span>
        <span className="acts">
          {running ? <span className="chip ok">{plural(running, 'job')} running</span> : null}
          {turns ? (
            <span className="chip" data-testid="jobs-turns">
              {turns} waiting for a turn
            </span>
          ) : null}
          {d ? <span className={`chip ${alive ? '' : 'watch'}`}>{alive ? 'Scheduler on' : 'Scheduler off'}</span> : null}
        </span>
      </div>
      {api.loading && !d ? (
        <p className="empty-hint">Reading the job list…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">The desk API didn&apos;t answer. The jobs come back as soon as it does.</p>
      ) : (
        <>
          {!alive ? (
            <p className="empty-hint" data-testid="scheduler-off">
              The scheduler is taking a break, so Run now is off. Jobs pick up again once the cron service runs.
            </p>
          ) : (
            <About label="How jobs run" testid="jobs-about">
              <p>Everything runs on its own schedule. Run now when you want fresh numbers sooner.</p>
            </About>
          )}
          {low ? (
            <p className="note job-low" data-testid="jobs-low">
              <Icon name="info" />
              <span>Low-memory mode is on, so heavy jobs run one at a time and the rest wait for their turn. {low.why || ''}</span>
            </p>
          ) : null}
          <div className="job-list">{rows(main)}</div>
          {rest.length ? (
            <details className="job-more">
              <summary>Agents and housekeeping ({rest.length})</summary>
              <div className="job-list">{rows(rest)}</div>
            </details>
          ) : null}
        </>
      )}
    </div>
  );
}

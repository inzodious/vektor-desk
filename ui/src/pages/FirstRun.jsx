import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { SETTINGS_TABS } from '../lib/areas.js';
import { Icon } from '../components/Icon.jsx';
import { postJson, useApi } from '../lib/api.js';
import { countdown, firstRunScore, firstRunSteps } from '../lib/firstrun.js';
import { jobWord, refusalText, runAndWait } from '../lib/jobs.js';

function Step({ s, n, run, onRun, onPost, alive }) {
  const r = run[s.id];
  const busy = r?.phase === 'waiting';
  const state = r?.phase === 'done' ? 'done' : s.state;
  const a = s.action;
  return (
    <li className={`fr-step ${state}`} data-step={s.id} data-state={state}>
      <span className="fr-num" aria-hidden="true">
        {state === 'done' ? <Icon name="check" /> : n}
      </span>
      <span className="fr-text">
        <b>{s.title}</b>
        <small>{s.line}</small>
        {s.note && state !== 'done' ? <small className="fr-note">{s.note}</small> : null}
        {r?.text ? (
          <small className={`fr-msg ${r.phase}`} role="status">
            {r.text}
          </small>
        ) : null}
      </span>
      <span className="fr-act">
        {state === 'soon' ? (
          <span className="chip lilac">Coming soon</span>
        ) : state === 'loading' ? (
          <span className="chip">Checking…</span>
        ) : busy ? (
          <span className="chip ok">
            <i className="pulse" style={{ width: 6, height: 6 }} />
            Working
          </span>
        ) : a?.kind === 'job' ? (
          <button className={`btn sm${state === 'done' ? ' ghost' : ''}`} type="button" disabled={!alive} title={alive ? undefined : 'The scheduler is off'} onClick={() => onRun(s, a.job)}>
            <Icon name="play" />
            {state === 'done' ? 'Run again' : a.label}
          </button>
        ) : a?.kind === 'post' ? (
          <button className="btn sm" type="button" onClick={() => onPost(s, a.path)}>
            <Icon name="check" />
            {a.label}
          </button>
        ) : a?.kind === 'link' ? (
          <Link className={`btn sm${state === 'done' ? ' ghost' : ''}`} to={a.to}>
            {a.label}
            <Icon name="right" />
          </Link>
        ) : null}
      </span>
    </li>
  );
}

export default function FirstRun() {
  const status = useApi('/api/status');
  const jobs = useApi('/api/jobs');
  const health = useApi('/api/engine/health');
  const profile = useApi('/api/decisions/profile/status');
  const agents = useApi('/api/agents/status');
  const board = useApi('/api/engine/lab/leaderboard');
  const risk = useApi('/api/decisions/risk');
  const [run, setRun] = useState({});
  const ctl = useRef(null);
  useEffect(() => {
    ctl.current = new AbortController();
    return () => ctl.current.abort();
  }, []);

  const steps = firstRunSteps({ status, jobs, health, profile, agents, board, risk });
  const score = firstRunScore(steps);
  const alive = !!jobs.data?.scheduler_alive;

  const onRun = async (step, job) => {
    const title = jobWord({ name: job }).title;
    setRun((m) => ({ ...m, [step.id]: { phase: 'waiting', text: null } }));
    try {
      const last = await runAndWait(job, { signal: ctl.current.signal });
      const ok = last?.result !== 'failed';
      setRun((m) => ({ ...m, [step.id]: { phase: ok ? 'done' : 'failed', text: ok ? `${title} done.` : `${title} didn’t finish${last?.detail ? `: ${last.detail}` : '.'}` } }));
      [status, jobs, health, board].forEach((x) => x.reload());
    } catch (e) {
      if (e.name !== 'AbortError') setRun((m) => ({ ...m, [step.id]: { phase: 'refused', text: refusalText(e) } }));
    }
  };

  const onPost = async (step, path) => {
    setRun((m) => ({ ...m, [step.id]: { phase: 'waiting', text: null } }));
    try {
      const r = await postJson(path);
      setRun((m) => ({ ...m, [step.id]: { phase: 'done', text: r?.message || 'Done.' } }));
      profile.reload();
    } catch (e) {
      const text = e.status === 404 ? 'This button switches on with the next desk update.' : e.status === 409 ? 'You already have one. Open Settings → Desk to see it.' : e.message;
      setRun((m) => ({ ...m, [step.id]: { phase: 'refused', text } }));
    }
  };

  return (
    <>
      <Hero
        kicker="Settings · First run"
        title="First run"
        art="settings"
        big={
          <>
            <b>
              {score.done} of {score.total}
            </b>
            <span className="muted">{countdown(score.left)}</span>
          </>
        }
        foot={
          <>
            <Subtabs label="Settings views" tabs={SETTINGS_TABS} />
            {score.next ? <span className="chip watch">Next: {score.next.title}</span> : <span className="chip ok">All set</span>}
            {jobs.data && !alive ? <span className="chip watch">Scheduler off</span> : null}
          </>
        }
      />
      <section className="card fr" data-testid="first-run" data-done={score.done} data-total={score.total}>
        <div className="card-head">
          <span className="tag mint">Launch sequence</span>
          <span className="chip">Everything runs from here; no terminal needed</span>
        </div>
        <span className="lb-track fr-track" role="img" aria-label={`${score.done} of ${score.total} steps done`}>
          <i style={{ width: `${score.share * 100}%` }} />
          <b style={{ left: `${score.share * 100}%` }} aria-hidden="true">
            <Icon name={score.left ? 'send' : 'flag'} />
          </b>
        </span>
        <ol className="fr-steps">
          {steps.map((s, i) => (
            <Step key={s.id} s={s} n={i + 1} run={run} onRun={onRun} onPost={onPost} alive={alive} />
          ))}
        </ol>
      </section>
    </>
  );
}

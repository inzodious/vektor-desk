import { Link, useLocation } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { needsYou, stepTook, stepWord } from '../lib/start.js';
import { useStart } from './context.js';

const FULL_PATHS = ['/'];
const OWN_PATHS = ['/settings/first-run', '/start'];

// ---------- one step ----------
function Step({ step, n }) {
  const word = stepWord(step);
  const took = stepTook(step);
  return (
    <li className="sd-step" data-step={step.id} data-state={step.state}>
      <span className="sd-dot" aria-hidden="true">
        {step.state === 'ok' ? <Icon name="check" /> : step.state === 'running' ? <i className="pulse" /> : n}
      </span>
      <span className="sd-text">
        <b>{step.title}</b>
        {step.detail ? <small>{step.detail}</small> : null}
      </span>
      <span className="sd-side">
        {step.fix && needsYou(step) ? (
          <Link className="btn sm" to={step.fix.to} data-testid="start-fix">
            {step.fix.label}
            <Icon name="right" />
          </Link>
        ) : (
          <span className={`chip ${word.tone}`}>
            {word.t}
            {took ? ` · ${took}` : ''}
          </span>
        )}
      </span>
    </li>
  );
}

export function StartSteps({ steps, only }) {
  const rows = only ? steps.filter(only) : steps;
  if (!rows.length) return null;
  return (
    <ol className="sd-steps" data-testid="start-steps">
      {rows.map((s) => (
        <Step key={s.id} step={s} n={steps.indexOf(s) + 1} />
      ))}
    </ol>
  );
}

// ---------- the button ----------
export function StartButton({ label, small = false, ghost = false }) {
  const { view, begin, busy } = useStart();
  if (view.mode === 'running' || view.mode === 'none') return null;
  const off = busy || !view.canStart;
  return (
    <button className={`btn${small ? ' sm' : ''}${ghost ? ' ghost' : ''} sd-go`} type="button" disabled={off} title={view.blocked || undefined} onClick={begin} data-testid="start-desk">
      <Icon name="send" />
      {busy ? 'Starting…' : label || view.button || 'Start the desk'}
    </button>
  );
}

function Track({ view }) {
  return (
    <span className="lb-track sd-track" role="img" aria-label={`${view.ended} of ${view.total} steps finished`}>
      <i style={{ width: `${view.share * 100}%` }} />
    </span>
  );
}

// ---------- full panel ----------
export function StartPanel({ always = false }) {
  const { view, error, justDone, dismiss, hide, hidden } = useStart();
  if (view.mode === 'none') return null;
  const done = view.mode === 'ok';
  if (done && !always && !justDone) return null;
  if (hidden && !always) return null;
  const live = view.mode === 'running';
  return (
    <section className={`card sd${done ? ' ok' : ''}`} data-testid="start-panel" data-mode={view.mode} aria-live="polite">
      <div className="sd-head">
        <span className="sd-badge" aria-hidden="true">
          <Icon name={done ? 'check' : live ? 'send' : 'play'} />
        </span>
        <div className="sd-copy">
          <h2>{view.head}</h2>
          <p>{view.line}</p>
          {view.blocked ? <small className="sd-warn">{view.blocked}</small> : null}
          {error ? (
            <small className="sd-warn" role="alert" data-testid="start-error">
              {error}
            </small>
          ) : null}
        </div>
        <div className="sd-acts">
          {done && always ? <StartButton label="Run it all again" ghost small /> : <StartButton />}
          {done && !always ? (
            <button className="link" type="button" onClick={dismiss}>
              Got it
            </button>
          ) : null}
          {view.mode === 'partial' && !always ? (
            <button className="link" type="button" onClick={hide} data-testid="start-hide">
              Hide for now
            </button>
          ) : null}
        </div>
      </div>
      {live ? <Track view={view} /> : null}
      {live || (always && view.mode !== 'never') ? <StartSteps steps={view.steps} /> : view.mode === 'partial' ? <StartSteps steps={view.steps} only={needsYou} /> : null}
      {view.mode === 'never' ? (
        <ul className="sd-plan" aria-label="What Start the desk does">
          {view.steps.map((s) => (
            <li key={s.id}>{s.title}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

// ---------- slim strip ----------
export function StartStrip() {
  const { view, error, justDone, dismiss, hidden } = useStart();
  if (view.mode === 'none' || hidden) return null;
  const done = view.mode === 'ok';
  if (done && !justDone) return null;
  const live = view.mode === 'running';
  return (
    <section className={`sd-strip${done ? ' ok' : ''}`} data-testid="start-strip" data-mode={view.mode} aria-live="polite">
      <span className="sd-badge sm" aria-hidden="true">
        <Icon name={done ? 'check' : live ? 'send' : 'play'} />
      </span>
      <div className="sd-copy">
        <p>
          <b>{view.head}.</b> <span>{view.short}</span>
        </p>
        {live ? <Track view={view} /> : null}
        {error ? (
          <small className="sd-warn" role="alert" data-testid="start-error">
            {error}
          </small>
        ) : null}
      </div>
      <div className="sd-acts">
        {live || view.mode === 'partial' ? (
          <Link className="link" to="/settings/first-run" data-testid="start-watch">
            {live ? 'Watch the steps' : 'See what’s left'}
          </Link>
        ) : null}
        <StartButton small />
        {done ? (
          <button className="link" type="button" onClick={dismiss}>
            Got it
          </button>
        ) : null}
      </div>
    </section>
  );
}

// ---------- shell slot ----------
export function StartBanner() {
  const { pathname } = useLocation();
  if (OWN_PATHS.includes(pathname)) return null;
  return FULL_PATHS.includes(pathname) ? <StartPanel /> : <StartStrip />;
}

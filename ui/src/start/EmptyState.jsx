import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { refusalText, runAndWait } from '../lib/jobs.js';
import { gapWords } from '../lib/start.js';
import { StartButton } from './StartDesk.jsx';
import { useGap, useStart } from './context.js';

// ---------- the one action ----------
function Action({ action, slim, onFilled }) {
  const { view, refresh } = useStart();
  const [run, setRun] = useState({ phase: 'idle', text: null });
  const ctl = useRef(null);
  useEffect(() => {
    ctl.current = new AbortController();
    return () => ctl.current.abort();
  }, []);
  if (!action) return null;
  const starting = view.mode === 'running';

  if (action.kind === 'link') {
    return (
      <Link className={`btn${slim ? ' sm' : ''}`} to={action.to} data-testid="empty-act">
        {action.label}
        <Icon name="right" />
      </Link>
    );
  }
  if (starting) {
    return (
      <span className="chip ok" role="status" data-testid="empty-filling">
        <i className="pulse" style={{ width: 6, height: 6 }} />
        The desk is starting. This fills in on its own.
      </span>
    );
  }
  if (action.kind === 'start') return view.mode === 'none' ? null : <StartButton label={action.label} small={slim} />;

  const go = async () => {
    setRun({ phase: 'running', text: null });
    try {
      const last = await runAndWait(action.job, { signal: ctl.current.signal });
      const why = last?.error || last?.detail;
      if (last?.result === 'failed') {
        setRun({ phase: 'failed', text: `That didn’t finish${why ? `: ${why}` : '.'} Settings → Box has the rest.` });
        return;
      }
      const skipped = last?.note || (last?.result === 'skipped' ? last.detail || 'Nothing to do right now.' : null);
      if (skipped) {
        setRun({ phase: 'refused', text: `It skipped this time: ${skipped}` });
        return;
      }
      setRun({ phase: 'done', text: 'Done. Filling in now.' });
      onFilled?.();
      refresh();
    } catch (e) {
      if (e.name !== 'AbortError') setRun({ phase: 'refused', text: refusalText(e) });
    }
  };
  return (
    <>
      {run.phase === 'running' ? (
        <span className="chip ok" role="status" data-testid="empty-working">
          <i className="pulse" style={{ width: 6, height: 6 }} />
          Working on it. You can leave the page.
        </span>
      ) : (
        <button className={`btn${slim ? ' sm' : ''}`} type="button" onClick={go} data-testid="empty-act">
          <Icon name="play" />
          {action.label}
        </button>
      )}
      {run.text ? (
        <small className={`es-msg ${run.phase}`} role="status" data-testid="empty-msg">
          {run.text}
        </small>
      ) : null}
    </>
  );
}

// ---------- why it is empty, and the one thing that fills it ----------
export function EmptyState({ k, title, why, action, icon = 'compass', slim = false, card = false, span = '', onFilled, children }) {
  const gap = useGap(k);
  const w = gapWords(gap, { why, action });
  const body = (
    <div className={`es${slim ? ' slim' : ''}`} data-testid="empty-state" data-key={k} data-state={w.state}>
      <span className="es-art" aria-hidden="true">
        <Icon name={icon} />
      </span>
      <div className="es-text">
        {title ? <b>{title}</b> : null}
        {w.why ? <p>{w.why}</p> : null}
        {w.auto ? <small>{w.auto}</small> : null}
        {children}
      </div>
      <div className="es-act">
        <Action action={w.action} slim={slim} onFilled={onFilled} />
      </div>
    </div>
  );
  return card ? <section className={`card${span ? ` ${span}` : ''} es-card`}>{body}</section> : body;
}

// ---------- a section with data that is stale or waiting on him ----------
export function GapNote({ k }) {
  const gap = useGap(k);
  if (!gap) return null;
  return <EmptyState k={k} slim icon="info" />;
}

// ---------- a whole page body behind one readiness key ----------
export function GapGate({ k, title, icon, hasData, children }) {
  const gap = useGap(k);
  const { known } = useStart();
  if (!known && !hasData) return null;
  if (!gap) return children;
  if (hasData) {
    return (
      <>
        <GapNote k={k} />
        {children}
      </>
    );
  }
  return <EmptyState k={k} card title={title} icon={icon} />;
}

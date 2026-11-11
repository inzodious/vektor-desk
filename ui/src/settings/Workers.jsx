import { useEffect, useRef, useState } from 'react';
import { Copy } from '../components/Copy.jsx';
import { Icon } from '../components/Icon.jsx';
import { postJson, useApi } from '../lib/api.js';
import { WORKERS_EVENT, nameProblem, startCommand, workerRefusal, workersBusy, workersView } from '../lib/workers.js';

const tell = () => window.dispatchEvent(new Event(WORKERS_EVENT));

// ---------- the key, once ----------
function KeyOnce({ made, onDone }) {
  const command = startCommand(made);
  return (
    <div className="box-script wk-key" data-testid="worker-key" role="status">
      <span>
        <b>{made.name} has a key. Copy it now; it isn’t shown again.</b>
        <small>Lost it? Remove the worker and add it again.</small>
      </span>
      <code className="wk-code" data-testid="worker-key-value">
        {made.key}
      </code>
      <Copy text={made.key} label="Copy the key" testid="worker-key-copy" />
      <small>Then start it, once, in a terminal on that machine, from its vektor-desk folder. It checks in here within a minute.</small>
      <pre className="wk-code" data-testid="worker-cmd">
        {command}
      </pre>
      <span className="key-acts">
        <Copy text={command} label="Copy the commands" testid="worker-cmd-copy" />
        <button className="btn sm ghost" type="button" onClick={onDone} data-testid="worker-key-done">
          Done, hide the key
        </button>
      </span>
    </div>
  );
}

// ---------- add ----------
function AddForm({ taken, onAdd, onCancel }) {
  const [name, setName] = useState(taken.length ? '' : 'Horizon');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const input = useRef(null);
  useEffect(() => {
    input.current?.focus();
  }, []);
  const submit = async (e) => {
    e.preventDefault();
    const bad = nameProblem(name, taken);
    if (bad) {
      setErr(bad);
      return;
    }
    setBusy(true);
    setErr(null);
    const refused = await onAdd(name.trim());
    setBusy(false);
    if (refused) setErr(refused);
  };
  return (
    <form className="key-form wk-form" onSubmit={submit} autoComplete="off" data-testid="worker-form">
      <label htmlFor="worker-name">What should the desk call it?</label>
      <input id="worker-name" ref={input} type="text" value={name} maxLength={40} autoComplete="off" spellCheck={false} onChange={(e) => setName(e.target.value)} data-testid="worker-name" />
      <span className="key-acts">
        <button className="btn sm" type="submit" disabled={busy}>
          <Icon name="plus" />
          {busy ? 'Making its key…' : 'Make its key'}
        </button>
        <button className="btn sm ghost" type="button" onClick={onCancel}>
          Cancel
        </button>
      </span>
      {err ? (
        <small className="job-note refused" role="alert" data-testid="worker-form-error">
          {err}
        </small>
      ) : null}
    </form>
  );
}

// ---------- one worker ----------
function WorkerRow({ w, asking, busy, onAsk, onKeep, onRemove }) {
  return (
    <div className="job-row" data-worker={w.id} data-state={w.state}>
      <span className={`job-dot ${w.state === 'online' ? 'ok' : w.state === 'asleep' ? 'skipped' : 'never'}`} aria-hidden="true" />
      <span className="job-text">
        <b>{w.name}</b>
        {w.words ? <small>{w.words}</small> : null}
        {w.meta ? <small className="job-when">{w.meta}</small> : null}
        {asking ? (
          <small className="job-note refused" role="alert">
            Remove {w.name}? Its key stops working at once.
          </small>
        ) : null}
      </span>
      <span className="job-act wk-act">
        {asking ? (
          <>
            <button className="btn sm" type="button" disabled={busy} onClick={() => onRemove(w)} data-testid="worker-remove-yes">
              {busy ? 'Removing…' : 'Remove'}
            </button>
            <button className="btn sm ghost" type="button" onClick={onKeep}>
              Keep
            </button>
          </>
        ) : (
          <>
            <span className={`chip ${w.chip.tone}`}>{w.chip.t}</span>
            <button className="btn ghost sm" type="button" aria-label={`Remove ${w.name}`} onClick={() => onAsk(w.id)} data-testid="worker-remove">
              Remove
            </button>
          </>
        )}
      </span>
    </div>
  );
}

// ---------- one job ----------
function JobRow({ j }) {
  return (
    <div className="job-row" data-wjob={j.id} data-state={j.state}>
      <span className={`job-dot ${j.state === 'done' ? 'ok' : j.state === 'failed' ? 'failed' : j.chip.live ? 'running' : 'never'}`} aria-hidden="true" />
      <span className="job-text">
        <b>{j.title}</b>
        {j.why ? <small>{j.why}</small> : null}
        {j.meta ? <small className="job-when">{j.meta}</small> : null}
      </span>
      <span className="job-act">
        <span className={`chip ${j.chip.tone}`}>
          {j.chip.live ? <i className="pulse" style={{ width: 6, height: 6 }} /> : null}
          {j.chip.t}
        </span>
      </span>
    </div>
  );
}

const FIRST = 4;

export function Workers() {
  const [posted, setPosted] = useState(null);
  const [fast, setFast] = useState(false);
  const api = useApi('/api/workers', { every: (d) => (fast || workersBusy(d) ? 5000 : 30000) });
  const [adding, setAdding] = useState(false);
  const [made, setMade] = useState(null);
  const [asking, setAsking] = useState(null);
  const [removing, setRemoving] = useState(false);
  const [note, setNote] = useState(null);
  const card = useRef(null);
  const block = posted && posted.base === api.data ? posted.body : api.data;
  const view = workersView(block);
  const ready = Boolean(view);
  useEffect(() => {
    if (ready && window.location.hash === '#workers') card.current?.scrollIntoView({ block: 'start' });
  }, [ready]);
  useEffect(() => {
    if (!fast) return undefined;
    const id = setTimeout(() => setFast(false), 180000);
    return () => clearTimeout(id);
  }, [fast]);
  if (!view) return null;

  const took = (body) => {
    if (body?.summary) setPosted({ body, base: api.data });
    api.reload();
    tell();
  };

  const add = async (name) => {
    try {
      const body = await postJson('/api/workers', { name });
      setMade({ key: body.key, name: body.name || name, desk_url: body.desk_url || null });
      setAdding(false);
      setNote(null);
      setFast(true);
      took(body);
      return null;
    } catch (e) {
      return workerRefusal(e);
    }
  };

  const remove = async (w) => {
    setRemoving(true);
    try {
      const body = await postJson(`/api/workers/${encodeURIComponent(w.id)}`, {}, { method: 'DELETE' });
      setNote({ phase: 'done', text: `${w.name} is removed. Its key no longer works.` });
      took(body);
    } catch (e) {
      setNote({ phase: 'refused', text: workerRefusal(e) });
      api.reload();
    }
    setRemoving(false);
    setAsking(null);
  };

  const test = async () => {
    setNote({ phase: 'saving', text: null });
    try {
      const body = await postJson('/api/worker/check');
      setNote({ phase: 'done', text: 'Asked. A small test job is in line below; it comes back within a minute when the worker is awake.' });
      setFast(true);
      took(body);
    } catch (e) {
      setNote({ phase: 'refused', text: workerRefusal(e) });
    }
  };

  const top = view.jobs.slice(0, Math.max(FIRST, view.open));
  const rest = view.jobs.slice(top.length);

  return (
    <div className="card c12 wk" id="workers" ref={card} style={{ '--i': 3 }} data-testid="workers" data-state={view.state}>
      <div className="card-head">
        <span className="tag lilac">Workers</span>
        <span className="acts">
          {view.waiting ? (
            <span className="chip" data-testid="workers-waiting">
              {view.waiting} waiting
            </span>
          ) : null}
          <span className={`chip ${view.chip.tone}`} data-testid="workers-chip">
            {view.chip.t}
          </span>
        </span>
      </div>
      <p className="muted job-lede" data-testid="workers-lead">
        {view.lead} {view.state === 'none' ? 'A second machine at home can take the heavy jobs: add it here, start it once, and it picks up work whenever it is awake.' : null}
      </p>
      {made ? <KeyOnce made={made} onDone={() => setMade(null)} /> : null}
      {view.workers.length ? (
        <div className="job-list wk-list">
          {view.workers.map((w) => (
            <WorkerRow key={w.id} w={w} asking={asking === w.id} busy={removing} onAsk={setAsking} onKeep={() => setAsking(null)} onRemove={remove} />
          ))}
        </div>
      ) : null}
      {adding ? (
        <AddForm taken={view.workers.map((w) => w.name)} onAdd={add} onCancel={() => setAdding(false)} />
      ) : (
        <div className="key-acts wk-acts">
          <button className="btn sm" type="button" disabled={!view.canAdd} title={view.canAdd ? undefined : 'Four workers is the most the desk takes'} onClick={() => setAdding(true)} data-testid="worker-add">
            <Icon name="plus" />
            Add a worker
          </button>
          {view.canTest ? (
            <button className="btn sm ghost" type="button" disabled={note?.phase === 'saving'} onClick={test} data-testid="worker-test">
              <Icon name="play" />
              Test the worker
            </button>
          ) : null}
          {note?.text ? (
            <small className={`job-note ${note.phase}`} role="status" data-testid="workers-note">
              {note.text}
            </small>
          ) : null}
        </div>
      )}
      {view.jobs.length ? (
        <div className="wk-jobs" data-testid="worker-jobs">
          <b className="wk-sub">Work sent to a worker</b>
          <div className="job-list">
            {top.map((j) => (
              <JobRow key={j.id} j={j} />
            ))}
          </div>
          {rest.length ? (
            <details className="job-more">
              <summary>Earlier ({rest.length})</summary>
              <div className="job-list">
                {rest.map((j) => (
                  <JobRow key={j.id} j={j} />
                ))}
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

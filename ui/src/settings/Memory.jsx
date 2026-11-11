import { useEffect, useRef, useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { postJson, useApi } from '../lib/api.js';
import { memoryView, modeRefusal } from '../lib/memory.js';
import { plural } from '../lib/format.js';
import { useStart } from '../start/context.js';

// ---------- the three-way choice ----------
function Mode({ view, busy, onPick }) {
  return (
    <fieldset className="mem-mode" data-testid="memory-mode" data-mode={view.low.mode} disabled={busy}>
      <legend>Low-memory mode</legend>
      <div className="mem-opts">
        {view.choices.map((c) => {
          const on = view.low.mode === c.mode;
          return (
            <label key={c.mode} className={`rq-opt mem-opt${on ? ' on' : ''}`} data-choice={c.mode}>
              <input type="radio" name="low-memory" value={c.mode} checked={on} onChange={() => onPick(c.mode)} />
              <span className="rq-dot" aria-hidden="true" />
              <span>
                <b>{c.title}</b>
                <small>{c.blurb}</small>
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export function Memory() {
  const api = useApi('/api/memory', { every: 30000 });
  const { recheck } = useStart();
  const [posted, setPosted] = useState(null);
  const [save, setSave] = useState({ phase: 'idle', text: null });
  const card = useRef(null);
  const block = posted && posted.base === api.data ? posted.body : api.data;
  const view = memoryView(block);
  const ready = Boolean(view);
  useEffect(() => {
    if (ready && window.location.hash === '#memory') card.current?.scrollIntoView({ block: 'start' });
  }, [ready]);
  if (!view) return null;

  const pick = async (mode) => {
    if (mode === view.low.mode) return;
    setSave({ phase: 'saving', text: null });
    try {
      const body = await postJson('/api/memory/low', { mode }, { method: 'PUT' });
      if (body?.low_memory) setPosted({ body, base: api.data });
      setSave({ phase: 'done', text: 'Saved. The scheduler follows within 30 seconds.' });
      recheck();
    } catch (e) {
      setSave({ phase: 'refused', text: modeRefusal(e) });
    }
    api.reload();
  };

  return (
    <div className="card c12 mem" id="memory" ref={card} style={{ '--i': 2 }} data-testid="memory" data-state={view.state} data-low={String(view.low.on)}>
      <div className="card-head">
        <span className="tag sky">Memory</span>
        <span className="acts">
          {view.low.on ? (
            <span className="chip info" data-testid="memory-low-chip">
              Low-memory mode on
            </span>
          ) : null}
          <span className={`chip ${view.chip.tone}`} data-testid="memory-chip">
            {view.chip.t}
          </span>
        </span>
      </div>
      <div className="mem-grid">
        <div className="mem-now">
          <b className="mem-head" data-testid="memory-head">
            {view.head}
          </b>
          {view.used != null ? (
            <span className={`lb-track mem-track${view.state === 'tight' ? ' tight' : ''}`} role="img" aria-label={`${Math.round(view.used * 100)} percent of the box’s memory is in use`}>
              <i style={{ width: `${view.used * 100}%` }} />
            </span>
          ) : null}
          {view.facts.length ? (
            <dl className="mem-facts">
              {view.facts.map((f) => (
                <div key={f.k} title={f.hint || undefined}>
                  <dt>{f.k}</dt>
                  <dd className="num">{f.v}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
        <div className="mem-switch">
          <Mode view={view} busy={save.phase === 'saving'} onPick={pick} />
          <p className="mem-line" data-testid="memory-line">
            {view.line}
          </p>
          {view.paused ? (
            <p className="mem-line" data-testid="memory-paused">
              {view.paused}
            </p>
          ) : null}
          {save.text ? (
            <small className={`job-note ${save.phase}`} role="status" data-testid="memory-saved">
              {save.text}
            </small>
          ) : null}
        </div>
      </div>
      {view.waiting.length ? (
        <div className="mem-list" data-testid="memory-waiting">
          <b>
            <Icon name="clock" />
            Waiting for a turn
          </b>
          <ul>
            {view.waiting.map((w) => (
              <li key={w.job}>
                {w.title}
                {w.since ? <small> since {w.since}</small> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {view.killed.length ? (
        <div className="mem-list watch" data-testid="memory-killed">
          <b>
            <Icon name="info" />
            Stopped for memory in the last two days ({plural(view.killed.length, 'time')})
          </b>
          <ul>
            {view.killed.map((k) => (
              <li key={`${k.at}-${k.words}`}>
                {k.words}
                {k.when ? <small> {k.when}</small> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {!view.hostSeen ? (
        <p className="mem-foot" data-testid="memory-host">
          The box itself hasn’t reported in yet, so only stopped jobs are listed. Update box script, below, switches that on.
        </p>
      ) : null}
    </div>
  );
}

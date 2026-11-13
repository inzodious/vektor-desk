import { useState } from 'react';
import { Link } from 'react-router-dom';
import { nextSteps, undoStep } from '../lib/nextsteps.js';

// ---------- one step ----------
function Step({ s, busy, onUndo }) {
  return (
    <details className={`ns-row${s.stamp ? '' : ' undated'}${s.mine ? ' mine' : ''}`} data-step={s.id}>
      <summary>
        {s.stamp ? <span className="stamp-day ns-stamp">{s.stamp}</span> : null}
        <span className="ns-main">
          <b>{s.text}</b>
          {s.meta ? <small className="ns-meta">{s.meta}</small> : null}
        </span>
        {s.chip ? (
          <span className={`chip ${s.chip.tone}`} data-testid="ns-backed" title={s.chip.words}>
            {s.chip.text}
          </span>
        ) : null}
      </summary>
      <dl className="ns-more">
        {s.detail ? (
          <div>
            <dt>How</dt>
            <dd>{s.detail}</dd>
          </div>
        ) : null}
        {s.read ? (
          <div data-testid="ns-read">
            <dt>Your date</dt>
            <dd>{`${s.read[0].toUpperCase()}${s.read.slice(1)}.`}</dd>
          </div>
        ) : null}
        {s.why ? (
          <div>
            <dt>Why</dt>
            <dd>{s.why}</dd>
          </div>
        ) : null}
        {s.basis ? (
          <div>
            <dt>Comes from</dt>
            <dd>{s.basis}</dd>
          </div>
        ) : null}
        {s.changes ? (
          <div>
            <dt>What would change it</dt>
            <dd>{s.changes}</dd>
          </div>
        ) : null}
        {s.tests.map((t) => (
          <div key={t.key} data-testid="ns-test">
            <dt>Lab test</dt>
            <dd>
              {t.title ? <b>{t.title}. </b> : null}
              {t.sentence}
              {s.chip?.words ? ` ${s.chip.words}` : ''}
              {t.row ? (
                <>
                  {' '}
                  <Link className="link" to={`/strategies/${encodeURIComponent(t.row)}`}>
                    See the test
                  </Link>
                </>
              ) : null}
            </dd>
          </div>
        ))}
        {s.queue ? (
          <div>
            <dt>Yours to decide</dt>
            <dd>
              <Link className="link" to={s.queue}>
                Open it in the queue
              </Link>
            </dd>
          </div>
        ) : null}
        {s.undo ? (
          <div>
            <dt>Not what you meant?</dt>
            <dd>
              <button className="btn sm ghost" type="button" disabled={busy} data-testid="ns-undo" onClick={() => onUndo(s)}>
                Take it off the list
              </button>{' '}
              <small className="muted">It does not come back.</small>
            </dd>
          </div>
        ) : null}
      </dl>
    </details>
  );
}

// ---------- the list ----------
export function NextSteps({ api }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  if (!api.data) return null;
  const view = nextSteps(api.data);
  if (view.empty && !msg) return null;
  const undo = async (s) => {
    setBusy(true);
    setMsg(null);
    try {
      setMsg({ ok: true, text: await undoStep(s.undo) });
      api.reload();
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card ns" data-testid="next-steps">
      <div className="card-head">
        <span className="tag mint">Next steps</span>
        <span className="chip">{view.items.length ? `${view.items.length} dated` : 'Nothing dated'}</span>
      </div>
      {msg ? (
        <p className={msg.ok ? 'act-note' : 'act-err'} role={msg.ok ? 'status' : 'alert'} data-testid="ns-msg">
          {msg.text}
        </p>
      ) : null}
      {view.items.length ? (
        <div className="ns-list" data-testid="ns-dated">
          {view.items.map((s) => (
            <Step s={s} key={s.id} busy={busy} onUndo={undo} />
          ))}
        </div>
      ) : (
        <p className="empty-hint">Nothing with a date in the next {view.days} days.</p>
      )}
      {view.standing.length ? (
        <details className="ns-standing" data-testid="ns-standing">
          <summary>
            <b>Standing</b>
            <span className="chip">{view.standing.length}</span>
          </summary>
          <div className="ns-list">
            {view.standing.map((s) => (
              <Step s={s} key={s.id} busy={busy} onUndo={undo} />
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}

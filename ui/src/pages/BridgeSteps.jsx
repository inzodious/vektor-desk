import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { DESK_ICO } from '../components/icons.js';
import { postJson } from '../lib/api.js';
import { DESK_KEY, lampSummary, lampsOf, needsReason, originName } from '../lib/decisions.js';
import { dueHead, dueRows } from '../lib/bridge.js';
import { bridgeSteps } from '../lib/stockPlans.js';

export function StepsDue({ queue, steps, i = 7, span = 'c7' }) {
  const nav = useNavigate();
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState(null);
  const [err, setErr] = useState(null);
  const q = queue.data;
  const items = q?.items || [];
  const { rows, noBuy, count } = bridgeSteps(steps.data);
  const due = dueRows(items, rows);
  const waiting = q?.count ?? items.length;
  const total = waiting + count;

  const approve = async (d) => {
    setBusy(d.id);
    setErr(null);
    try {
      await postJson(`/api/decisions/${d.id}/approve`, { reason: null });
      setNote(`Approved: ${d.title}.`);
      queue.reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={`card ${span} due`} style={{ '--i': i }} data-testid="steps-due" data-queue={waiting} data-steps={count}>
      <div className="card-head">
        <span className="tag coral">Steps due</span>
        <span className="acts">
          {q || steps.data ? <span className={`chip${waiting ? ' act' : ''}`}>{dueHead(waiting, count)}</span> : null}
          <Link className="link" to="/decisions" data-testid="due-queue">
            Queue
          </Link>
          <Link className="link" to="/portfolio/stocks" data-testid="due-plans">
            Stock plans
          </Link>
        </span>
      </div>
      {note ? (
        <p className="act-note" role="status">
          <Icon name="check" />
          {note}
        </p>
      ) : null}
      {!q && !steps.data ? (
        <p className="empty-hint">{queue.error && steps.error ? "The queue didn't answer. It comes back with the desk API." : 'Reading the queue…'}</p>
      ) : total ? (
        <ul className="sp-steps due-list">
          {due.queue.map((d) => {
            const key = DESK_KEY[d.origin] || 'plan';
            const sum = lampSummary(lampsOf(d));
            const reason = needsReason(d);
            return (
              <li className="sp-step" key={d.id} data-due="decision" data-prop={d.id}>
                <span className={`desk-ico sm ${key}`} aria-hidden="true">
                  <Icon name={DESK_ICO[key] || 'compass'} />
                </span>
                <span className="sp-step-main">
                  <b>{d.title}</b>
                  <small>
                    {originName(d.origin)}
                    {sum ? (
                      <>
                        {' · '}
                        <span className={`tone-${sum.tone}`}>{sum.text}</span>
                      </>
                    ) : null}
                    {d.funding === 'margin' ? ' · on margin' : ''}
                  </small>
                </span>
                <span className="sp-step-side">
                  {reason ? (
                    <button className="btn sm" type="button" onClick={() => nav(`/decisions?d=${d.id}`)}>
                      Review
                    </button>
                  ) : (
                    <>
                      <button className="btn sm" type="button" disabled={busy === d.id} onClick={() => approve(d)}>
                        Approve
                      </button>
                      <button className="icon-btn sm" type="button" title="Look closer" aria-label={`Open ${d.title}`} onClick={() => nav(`/decisions?d=${d.id}`)}>
                        <Icon name="right" />
                      </button>
                    </>
                  )}
                </span>
              </li>
            );
          })}
          {due.plan.map((r) => (
            <li className="sp-step" key={r.key} data-due="step" data-step={r.id}>
              {r.stamp ? (
                <span className="disc-stamp" aria-hidden="true">
                  <b>{r.stamp.day}</b>
                  <small>{r.stamp.mon}</small>
                </span>
              ) : (
                <span className="sp-nodate" aria-hidden="true">
                  <Icon name="clock" />
                </span>
              )}
              <span className="sp-step-main">
                <b>
                  {r.text}{' '}
                  <button type="button" className="sym sym-btn" data-sym={r.symbol}>
                    {r.symbol}
                  </button>
                </b>
                <small>
                  {r.when} · <span className={r.status.tone ? `tone-${r.status.tone}` : undefined}>{r.status.t}</span>
                </small>
              </span>
              <span className="sp-step-side">
                <Link className="btn sm ghost" to={`/portfolio/stocks?symbol=${encodeURIComponent(r.symbol)}`}>
                  Open
                </Link>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="queue-clear" data-testid="due-clear">
          <Icon name="check" />
          <span>
            <b>Nothing needs you</b>
            <small>The queue is clear{q?.to_place ? `, but ${q.to_place} approved ${q.to_place === 1 ? 'trade is' : 'trades are'} waiting to be placed` : ' and no plan step is due in the next two weeks'}.</small>
          </span>
        </div>
      )}
      {noBuy.map((n) => (
        <p className="note sp-warn due-warn" key={n.symbol} data-testid="no-buy" data-symbol={n.symbol} title={n.reason ? `${n.reason}. Buying it in any account inside the window would void the loss.` : 'Buying it in any account inside the window would void the loss.'}>
          <Icon name="shield" />
          <span>
            <b>{n.text}.</b> A buy in any account would void the loss.
          </span>
        </p>
      ))}
      {err ? (
        <p className="act-err" role="alert">
          {err}
        </p>
      ) : null}
    </div>
  );
}

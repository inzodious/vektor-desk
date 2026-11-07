import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { ProposalCard } from './ProposalCard.jsx';
import { postJson } from '../lib/api.js';
import { needsReason } from '../lib/decisions.js';

const TOP = 3;

export function QueueCard({ queue, i = 7, span = 'c12' }) {
  const nav = useNavigate();
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState(null);
  const [err, setErr] = useState(null);
  const q = queue.data;
  const items = q?.items || [];
  const reasons = items.filter(needsReason).length;

  const run = async (d, path, body, word) => {
    setBusy(d.id);
    setErr(null);
    try {
      await postJson(`/api/decisions/${d.id}/${path}`, body);
      setNote(`${word}: ${d.title}.`);
      queue.reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };

  const actions = {
    approve: (d) => run(d, 'approve', { reason: null }, 'Approved'),
    snooze: (d) => run(d, 'snooze', { days: 1 }, 'Snoozed a day'),
    dismiss: (d) => run(d, 'dismiss', { reason: null }, 'Dismissed'),
    review: (d) => nav(`/decisions?d=${d.id}`),
  };

  return (
    <div className={`card ${span}`} style={{ '--i': i }} data-testid="bridge-queue">
      <div className="card-head">
        <span className="tag coral">Queue</span>
        <span className="acts">
          {q ? <span className="chip">{q.count ? `${q.count} waiting${reasons ? ` · ${reasons} need a reason` : ''}` : 'Clear'}</span> : null}
          <Link className="btn sm ghost" to="/decisions">
            Open the queue
            <Icon name="right" />
          </Link>
        </span>
      </div>
      {note ? (
        <p className="act-note" role="status">
          <Icon name="check" />
          {note}
        </p>
      ) : null}
      {!q ? (
        <p className="empty-hint">{queue.error ? "The queue didn't answer. It comes back with the desk API." : 'Reading the queue…'}</p>
      ) : items.length ? (
        <div className="prop-list">
          {items.slice(0, TOP).map((d) => (
            <ProposalCard key={d.id} d={d} onPick={actions.review} actions={actions} busy={busy === d.id} />
          ))}
          {items.length > TOP ? (
            <Link className="muted more-link" to="/decisions">
              {items.length - TOP} more in the queue
            </Link>
          ) : null}
        </div>
      ) : (
        <div className="queue-clear">
          <Icon name="check" />
          <span>
            <b>Queue is clear</b>
            <small>Nothing waiting on you{q.to_place ? `, but ${q.to_place} approved ${q.to_place === 1 ? 'trade is' : 'trades are'} waiting to be placed` : ''}.</small>
          </span>
        </div>
      )}
      {err ? (
        <p className="act-err" role="alert">
          {err}
        </p>
      ) : null}
    </div>
  );
}

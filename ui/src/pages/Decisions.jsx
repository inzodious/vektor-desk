import { useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Combo } from '../components/Combo.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { ProposalCard } from '../decisions/ProposalCard.jsx';
import { Detail } from '../decisions/Detail.jsx';
import { accountLabel } from '../live/context.js';
import { postJson, useApi } from '../lib/api.js';
import { dayWords } from '../lib/charts.js';
import { DECISION_TABS, kindName, needsReason, oneLine, originName } from '../lib/decisions.js';
import { usd } from '../lib/format.js';
import { EmptyState } from '../start/EmptyState.jsx';
import { useGap } from '../start/context.js';


// ---------- heads-up notes ----------
function Notes() {
  const api = useApi('/api/decisions/notes?days=7', { every: 300000 });
  const items = Array.isArray(api.data?.items) ? api.data.items : [];
  if (!items.length) return null;
  return (
    <div className="card" style={{ '--i': 3 }} data-testid="notes">
      <div className="card-head">
        <span className="tag sky">Heads-up notes</span>
        <span className="chip">Nothing to decide</span>
      </div>
      <div className="rows">
        {items.map((d) => (
          <div className="row still note-row" key={d.id} data-note={d.id}>
            <span className="l">
              <span style={{ minWidth: 0 }}>
                <b>{d.title}</b>
                {d.thesis ? <small className="wrap">{oneLine(d.thesis)}</small> : null}
                <small>
                  {originName(d.origin)}
                  {dayWords(d.as_of || d.created_at) ? ` · as of ${dayWords(d.as_of || d.created_at)}` : ''}
                </small>
              </span>
            </span>
          </div>
        ))}
      </div>
      <p className="empty-hint">The latest note from each desk, for the last {api.data.days || 7} days. Older ones are in the Journal.</p>
    </div>
  );
}

// ---------- to place ----------
function ToPlace({ items, onPlaced }) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  if (!items.length) return null;
  const place = async (d) => {
    setBusy(d.id);
    setErr(null);
    try {
      await postJson(`/api/decisions/${d.id}/placed`, {});
      onPlaced(d);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="card" style={{ marginTop: 12 }} data-testid="to-place">
      <div className="card-head">
        <span className="tag mint">To place</span>
        <span className="chip watch">{items.length}</span>
      </div>
      <div className="rows">
        {items.map((d) => (
          <div className="row still" key={d.id}>
            <span className="l">
              <span className="sym">
                <i style={{ '--c': 'var(--s1)' }} />
                {d.symbol || kindName(d.kind)}
              </span>
              <small>
                {d.title}
                {d.account ? ` · ${accountLabel(d.account)}` : ''}
              </small>
            </span>
            <button className="btn sm ghost" type="button" disabled={busy === d.id} onClick={() => place(d)}>
              <Icon name="check" />
              Mark placed
            </button>
          </div>
        ))}
      </div>
      {err ? (
        <p className="act-err" role="alert">
          {err}
        </p>
      ) : null}
    </div>
  );
}

// ---------- page ----------
export default function Decisions() {
  const [params, setParams] = useSearchParams();
  const queue = useApi('/api/decisions/queue', { every: 60000 });
  const placing = useApi('/api/decisions/journal?status=approved&limit=20');
  const [desk, setDesk] = useState('all');
  const [note, setNote] = useState(null);
  const detailRef = useRef(null);
  const all = useMemo(() => queue.data?.items || [], [queue.data]);
  const gap = useGap('decisions.queue');
  const desks = useMemo(() => [{ v: 'all', t: 'All desks' }, ...[...new Set(all.map((d) => d.origin))].map((o) => ({ v: o, t: originName(o) }))], [all]);
  const items = desk === 'all' ? all : all.filter((d) => d.origin === desk);
  const want = params.get('d');
  const cur = items.find((d) => d.id === want)?.id || (want && !queue.data ? want : items[0]?.id) || null;
  const toPlace = (placing.data?.days || []).flatMap((g) => g.items).filter((d) => d.status === 'approved');
  const reasons = all.filter(needsReason).length;

  const pick = (d) => {
    setParams((p) => {
      const n = new URLSearchParams(p);
      n.set('d', d.id);
      return n;
    }, { replace: true });
    setNote(null);
    if (window.matchMedia?.('(max-width: 860px)').matches) requestAnimationFrame(() => detailRef.current?.scrollIntoView({ block: 'start' }));
  };

  const done = (out, word) => {
    const left = items.filter((d) => d.id !== out.id);
    setNote(`${word}: ${out.title}.${out.status === 'approved' ? ' It is on the To place list.' : ''}`);
    setParams((p) => {
      const n = new URLSearchParams(p);
      if (left[0]) n.set('d', left[0].id);
      else n.delete('d');
      return n;
    }, { replace: true });
    queue.reload();
    placing.reload();
  };

  const tabs = <Subtabs label="Decisions views" tabs={DECISION_TABS} />;

  if (queue.loading) return <Hero kicker="Decisions · Queue" title="Decisions" art="decisions" big={<b>Checking…</b>} foot={tabs} />;

  if (queue.error && !queue.data) {
    return (
      <>
        <Hero kicker="Decisions · Queue" title="Decisions" art="decisions" big={<b>No answer</b>} foot={tabs} />
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button className="btn sm" type="button" onClick={queue.reload}>
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">The queue comes back as soon as it does.</p>
        </section>
      </>
    );
  }

  const q = queue.data;
  return (
    <>
      <Hero
        kicker="Decisions · Queue"
        title="Decisions"
        art="decisions"
        big={
          <>
            <b>{q.count}</b>
            <span className="muted">
              waiting{reasons ? ` · ${reasons} need${reasons === 1 ? 's' : ''} a reason to go ahead` : q.count ? ' · all clear to approve' : ''}
            </span>
          </>
        }
        foot={
          <>
            {tabs}
            {q.snoozed ? <span className="chip">{q.snoozed} snoozed</span> : null}
            {q.to_place ? <span className="chip watch">{q.to_place} to place</span> : null}
          </>
        }
      />
      <section className="grid">
        <div className="c5">
          <div className="card" style={{ '--i': 1 }}>
            <div className="card-head">
              <span className="tag coral">Queue</span>
              <span className="acts">{all.length > 1 ? <Combo label="Desk" options={desks} value={desk} onChange={setDesk} /> : <span className="chip">Sorted by expiry</span>}</span>
            </div>
            {note ? (
              <p className="act-note" role="status">
                <Icon name="check" />
                {note}
              </p>
            ) : null}
            {items.length ? (
              <div className="prop-list">
                {items.map((d) => (
                  <ProposalCard key={d.id} d={d} on={d.id === cur} onPick={pick} />
                ))}
              </div>
            ) : gap && !all.length ? (
              <EmptyState k="decisions.queue" icon="decisions" title="Nothing to decide yet" />
            ) : (
              <div className="queue-clear">
                <Icon name="check" />
                <span>
                  <b>Queue is clear</b>
                  <small>{all.length ? 'Nothing from this desk. Pick All desks to see the rest.' : 'Nothing waiting on you. The desks write new proposals after each run.'}</small>
                </span>
              </div>
            )}
          </div>
          <ToPlace items={toPlace} onPlaced={(d) => { setNote(`Marked placed: ${d.title}. The next mirror confirms the fill.`); placing.reload(); queue.reload(); }} />
          <Notes />
        </div>
        <div className="c7 detail" ref={detailRef}>
          {cur ? (
            <Detail key={cur} id={cur} onDone={done} />
          ) : (
            <div className="card">
              <p className="empty-hint">Pick a proposal to see its Preflight lamps and order ticket.</p>
              {toPlace.length ? <p className="muted">{usd(toPlace.reduce((a, d) => a + (d.amount_usd || 0), 0))} approved and waiting to be placed.</p> : null}
            </div>
          )}
        </div>
      </section>
    </>
  );
}

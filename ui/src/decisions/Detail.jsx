import { useRef, useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { DESK_ICO } from '../components/icons.js';
import { Annunciator, LampNotes } from './Annunciator.jsx';
import { Conf, Lights } from './Lights.jsx';
import { Ticket } from './Ticket.jsx';
import { accountLabel } from '../live/context.js';
import { postJson, useApi } from '../lib/api.js';
import { DESK_KEY, FUNDING, PREFLIGHT_WORD, kindName, lampsOf, needsReason, originName, preflightMetric } from '../lib/decisions.js';
import { etStamp, plural, usd } from '../lib/format.js';
import { dayLabel } from '../lib/charts.js';

const EVENT = {
  proposed: 'Proposed',
  preflight: 'Preflight ran',
  skeptic: 'Skeptic read it',
  approved: 'Approved',
  approved_unchecked: 'Approved before Preflight ran',
  override: 'Approved over Preflight',
  dismissed: 'Dismissed',
  snoozed: 'Snoozed',
  passed: 'Passed and logged',
  placed: 'Marked placed',
  filled: 'Fill confirmed',
  expired: 'Expired',
  rejected: 'Rejected',
  note: 'Note',
  logged_after: 'Logged after the trade',
};

function amountOf(d) {
  if (d.amount_usd != null) return usd(d.amount_usd);
  if (d.shares != null) return `${d.shares} shares`;
  return '—';
}

function isWeb(s) {
  return /^https?:/.test(s.url || '');
}

// ---------- override box ----------
function Override({ d, lamps, reason, setReason, inputRef, onPass, busy }) {
  const act = lamps ? lamps.filter((l) => l.status === 'act') : [];
  const cost = d.funding === 'margin' ? preflightMetric(d, 'margin.cost_month')?.after : null;
  const head = act.length ? `${act.length === 1 ? 'One light needs' : `${act.length} lights need`} a reason.` : 'Preflight has a heads up.';
  return (
    <div className="override" data-testid="override">
      <span>
        <b>{head}</b> {d.funding === 'margin' ? (cost != null ? `This costs about ${usd(cost)} a month in interest. ` : 'Part of this goes on margin. ') : ''}
        Going ahead logs an override with your reason and scores it like any other call.
      </span>
      <div className="override-row">
        <div className="field" style={{ flex: 1, minWidth: 180 }}>
          <input ref={inputRef} aria-label="One-line reason" placeholder="One line on why" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />
        </div>
        <button className="btn" type="button" disabled={busy} onClick={onPass}>
          <Icon name="x" />
          Pass and log it
        </button>
      </div>
    </div>
  );
}

// ---------- detail ----------
export function Detail({ id, onDone }) {
  const rec = useApi(`/api/decisions/${id}`);
  const tk = useApi(`/api/decisions/${id}/ticket`);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const inputRef = useRef(null);
  const d = rec.data;

  if (!d) {
    return (
      <div className="card">
        {rec.error ? (
          <p className="muted" role="alert">
            {rec.error.status === 404 ? 'That decision is gone. Pick another from the queue.' : "The desk API didn't answer for this one."}
          </p>
        ) : (
          <p className="empty-hint">Opening the proposal…</p>
        )}
      </div>
    );
  }

  const lamps = lampsOf(d);
  const ask = needsReason(d);
  const open = d.status === 'proposed' || d.status === 'snoozed';
  const key = DESK_KEY[d.origin] || 'plan';
  const ticket = tk.data && tk.data.fields?.length ? tk.data : null;
  const sources = d.sources || [];

  const run = async (path, body, word) => {
    setBusy(true);
    setErr(null);
    try {
      const out = await postJson(`/api/decisions/${id}/${path}`, body);
      onDone?.(out, word);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const approve = () => {
    if (ask && !reason.trim()) {
      setErr('Add a one-line reason above first. Approve stays available, it just needs the why.');
      inputRef.current?.focus();
      return;
    }
    run('approve', { reason: reason.trim() || null }, d.kind === 'hold_off' || d.kind === 'memo' || d.kind === 'alert' ? 'Noted' : 'Approved');
  };
  const pass = () => {
    if (!reason.trim()) {
      setErr('A pass needs a one-line reason so it can be scored later.');
      inputRef.current?.focus();
      return;
    }
    run('pass', { reason: reason.trim() }, 'Passed and logged');
  };

  return (
    <>
      <div className="card" data-testid="detail">
        <div className="card-head">
          <span style={{ display: 'flex', gap: 10, alignItems: 'center', minWidth: 0 }}>
            <span className={`desk-ico ${key}`}>
              <Icon name={DESK_ICO[key] || 'compass'} />
            </span>
            <span style={{ minWidth: 0 }}>
              <span className="kicker">
                {originName(d.origin)} · {kindName(d.kind)}
                {d.profile_version != null ? ` · profile v${d.profile_version}` : ''}
              </span>
              <h2>{d.title}</h2>
            </span>
          </span>
          <Conf value={d.confidence} />
        </div>
        <div className="kv">
          <div>
            <small>Symbol</small>
            <b>
              {d.symbol ? (
                <button type="button" className="sym sym-btn" data-sym={d.symbol}>
                  <i style={{ '--c': 'var(--s1)' }} />
                  {d.symbol}
                </button>
              ) : (
                '—'
              )}
            </b>
          </div>
          <div>
            <small>Amount</small>
            <b>{amountOf(d)}</b>
          </div>
          <div>
            <small>Funding</small>
            <b>{d.funding ? FUNDING[d.funding] || d.funding : '—'}</b>
          </div>
          <div>
            <small>Judge at</small>
            <b>{d.horizon || '30 days'}</b>
          </div>
        </div>
        <div className="split" style={{ marginTop: 12 }}>
          <div className="bb">
            <div className="bull">
              <b>Thesis</b>
              {d.thesis || 'No thesis written.'}
            </div>
            <div className="bear">
              <b>Bear case</b>
              {d.bear_case || (d.kind === 'deposit_route' || d.kind === 'hold_off' ? 'None needed for a plan move.' : 'None written yet. Add one before approving.')}
            </div>
          </div>
          <div className="bb">
            {d.skeptic ? (
              <div className="skeptic">
                <b>Skeptic · {d.skeptic.verdict === 'flag' ? 'flag' : 'pass'}</b>
                {d.skeptic.counter_case} It saw only the engine numbers, no web pages.
              </div>
            ) : null}
            <div className="plain">
              <b>Invalidation</b>
              {d.invalidation || 'None written.'}
            </div>
            {!d.skeptic ? (
              <div className="plain">
                <b>Rule served</b>
                {d.rule_served || 'None named.'}
              </div>
            ) : null}
          </div>
        </div>
        {d.account ? (
          <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
            Account: {accountLabel(d.account)}
            {d.expires_at ? ` · expires ${etStamp(d.expires_at)}` : ''}
          </p>
        ) : null}
      </div>

      <div className="card">
        <div className="card-head">
          <span className="tag mustard">Preflight</span>
          <span className="acts">
            {lamps ? <Lights lamps={lamps} big /> : null}
            <span className="muted" style={{ fontSize: 12 }}>
              Warns, never blocks
            </span>
          </span>
        </div>
        {lamps ? (
          <>
            <Annunciator lamps={lamps} />
            <LampNotes lamps={lamps} />
          </>
        ) : (
          <p className="empty-hint">{PREFLIGHT_WORD[d.preflight_status] || 'Not checked'}.</p>
        )}
        {open && ask ? <Override d={d} lamps={lamps} reason={reason} setReason={setReason} inputRef={inputRef} onPass={pass} busy={busy} /> : null}
      </div>

      <div className="card">
        <div className="card-head">
          <span className="tag mint">Order ticket</span>
          <span className="acts">{ticket ? <span className="chip">Copy into Fidelity</span> : null}</span>
        </div>
        {ticket ? <Ticket ticket={ticket} /> : <p className="empty-hint">Advice only, so there is nothing to place.</p>}
        {open ? (
          <div className="tk-acts">
            <button className="btn" type="button" disabled={busy} onClick={approve}>
              <Icon name="check" />
              {ask ? 'Approve with reason' : 'Approve'}
            </button>
            <button className="btn ghost" type="button" disabled={busy} onClick={() => run('snooze', { days: 1 }, 'Snoozed a day')}>
              <Icon name="snooze" />
              Snooze a day
            </button>
            <button className="btn ghost" type="button" disabled={busy} onClick={() => run('dismiss', { reason: reason.trim() || null }, 'Dismissed')}>
              <Icon name="x" />
              Dismiss
            </button>
            <span className="muted" style={{ fontSize: 12 }}>
              You place the trade at Fidelity. Marked placed stays pending until the next mirror confirms the fill.
            </span>
          </div>
        ) : null}
        {err ? (
          <p className="act-err" role="alert">
            {err}
          </p>
        ) : null}
      </div>

      <div className="card">
        <div className="card-head">
          <span className="tag lilac">Sources</span>
          <span className="chip">{sources.length ? (sources.some((s) => !isWeb(s)) ? `${sources.length} · ${sources.filter((s) => !isWeb(s)).length} primary` : plural(sources.length, 'web source')) : 'Engine only'}</span>
        </div>
        {sources.length ? (
          sources.map((s) => (
            <div className="src" key={s.url || s.title}>
              <span className={`chip${isWeb(s) ? '' : ' ok'}`}>{isWeb(s) ? 'Web' : 'Primary'}</span>
              {isWeb(s) ? (
                <a href={s.url} target="_blank" rel="noreferrer noopener">
                  {s.title || s.url}
                </a>
              ) : (
                <span>{s.title}</span>
              )}
              <span className="muted src-date">{s.date ? dayLabel(s.date.slice(0, 10), true) : ''}</span>
            </div>
          ))
        ) : (
          <p className="empty-hint">
            Built from the engine{d.numbers_used?.length ? `: ${[...new Set(d.numbers_used.map((n) => n.metric_id))].join(', ')}` : ''}. No web pages read.
          </p>
        )}
        {d.events?.length ? (
          <>
            <span className="kicker" style={{ marginTop: 10 }}>
              History
            </span>
            <div className="rows">
              {d.events.map((e, i) => (
                <div className="row still" key={`${e.at}-${e.event}-${i}`}>
                  <span className="l">
                    <b>{EVENT[e.event] || e.event}</b>
                    {e.reason ? <small>“{e.reason}”</small> : e.detail?.status ? <small>{PREFLIGHT_WORD[e.detail.status] || e.detail.status}</small> : e.detail?.verdict ? <small>Verdict: {e.detail.verdict}</small> : null}
                  </span>
                  <span className="v">
                    <small>{etStamp(e.at)}</small>
                  </span>
                </div>
              ))}
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}

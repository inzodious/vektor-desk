import { useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { DESK_ICO } from '../components/icons.js';
import { postJson } from '../lib/api.js';
import { DESK_KEY } from '../lib/decisions.js';
import { RUN_STATUS, TRIGGER, usageShare, whenLabel } from '../lib/agents.js';
import { count } from '../lib/format.js';
import { useNow } from '../lib/useNow.js';

const NEXT_NONE = { skeptic: 'After each buy or sell', strategy: 'When you start a test' };

function useToggle(reload) {
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const flip = async (desk, enabled) => {
    setBusy(desk);
    setErr(null);
    try {
      await postJson(`/api/agents/${encodeURIComponent(desk)}/enabled`, { enabled }, { method: 'PUT' });
      reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };
  return { busy, err, flip };
}

// ---------- crew tiles ----------
function Tile({ d, allOn, busy, onFlip, now }) {
  const key = DESK_KEY[d.desk] || 'plan';
  const run = d.last_run;
  const st = run ? RUN_STATUS[run.status] || { t: run.status, tone: '' } : null;
  const over = d.week.cap && d.week.runs > d.week.cap;
  const on = d.enabled && allOn;
  const next = !d.live ? 'Not live yet' : !on ? 'Off' : d.next_run ? (Date.parse(d.next_run) <= now.getTime() ? 'Due now' : whenLabel(d.next_run, now)) : NEXT_NONE[d.desk] || 'On demand';
  return (
    <div className={`crew-tile${on ? '' : ' off'}`} data-desk={d.desk}>
      <span className="crew-top">
        <span className={`desk-ico ${key}`}>
          <Icon name={DESK_ICO[key] || 'compass'} />
        </span>
        <button
          type="button"
          className="switch"
          role="switch"
          aria-checked={d.enabled}
          aria-label={`${d.title} on`}
          disabled={busy || !d.live}
          onClick={() => onFlip(d.desk, !d.enabled)}
        />
      </span>
      <b>{d.title}</b>
      <small>
        {d.model} · {d.effort}
        {!d.live ? ' · not live' : ''}
      </small>
      <small className="crew-runs">
        <span>
          Last: {run ? whenLabel(run.started_at, now) : 'Never'}
          {run ? <span className={`chip ${st.tone}`}>{st.t}</span> : null}
        </span>
        {run?.note ? <span className="crew-note">{run.note}</span> : null}
        <span>Next: {next}</span>
      </small>
      <div className="meter" role="img" aria-label={`${d.week.runs} of ${d.week.cap} runs this week`}>
        <i style={{ width: `${usageShare(d.week) * 100}%`, background: over ? 'var(--mustard)' : undefined }} />
      </div>
      <small>
        {d.week.runs} of {d.week.cap} runs this week{over ? ' · over, next run waits' : ''}
      </small>
    </div>
  );
}

export function Crew({ status, reload }) {
  const now = useNow(60000);
  const { busy, err, flip } = useToggle(reload);
  const data = Array.isArray(status.data?.desks) ? status.data : null;
  if (!data) {
    return (
      <div className="card c12" style={{ '--i': 5 }}>
        <div className="card-head">
          <span className="tag mint">Crew</span>
        </div>
        <p className="empty-hint">{status.error ? "The crew didn't answer. The desks may not be set up on this NAS yet." : 'Reading the crew…'}</p>
      </div>
    );
  }
  return (
    <div className="card c12" style={{ '--i': 5 }} data-testid="crew">
      <div className="card-head">
        <span className="tag mint">Crew</span>
        <span className="acts">
          {data.busy ? <span className="chip info">A desk is running</span> : null}
          <span className="kill">
            <span className="muted">All desks</span>
            <button type="button" className="switch" role="switch" aria-checked={data.enabled} aria-label="All desks on" disabled={busy === '*'} onClick={() => flip('*', !data.enabled)} />
          </span>
        </span>
      </div>
      {!data.enabled ? (
        <p className="act-err" role="status">
          All desks are paused. Nothing runs, and the Console waits, until you switch them back on.
        </p>
      ) : null}
      <div className="crew">
        {data.desks.map((d) => (
          <Tile key={d.desk} d={d} allOn={data.enabled} busy={busy === d.desk || busy === '*'} onFlip={flip} now={now} />
        ))}
      </div>
      {err ? (
        <p className="act-err" role="alert">
          {err}
        </p>
      ) : null}
      <p className="empty-hint" style={{ marginTop: 8 }}>
        Desks advise only. Each run goes through the Claude Code CLI on your subscription, so the weekly caps keep usage in check.
      </p>
    </div>
  );
}

// ---------- usage ----------
export function Usage({ status, runs }) {
  const data = Array.isArray(status.data?.desks) ? status.data : null;
  if (!data) return null;
  const desks = data.desks.filter((d) => d.live);
  const max = Math.max(1, ...desks.map((d) => Math.max(d.week.runs, d.week.cap)));
  const tokens = desks.reduce((a, d) => a + (d.week.tokens || 0), 0);
  const recent = (Array.isArray(runs.data) ? runs.data : []).slice(0, 8);
  return (
    <>
      <div className="card c6" style={{ '--i': 6 }} data-testid="usage">
        <div className="card-head">
          <span className="tag sky">Weekly usage</span>
          <span className="chip">{count(tokens)} tokens in 7 days</span>
        </div>
        <div className="use-rows" role="table" aria-label="Runs this week against each desk's cap">
          {desks.map((d) => {
            const over = d.week.runs > d.week.cap;
            return (
              <div className="use-row" role="row" key={d.desk}>
                <span role="rowheader">{d.title}</span>
                <span className="use-track" role="cell" aria-label={`${d.week.runs} runs, cap ${d.week.cap}`}>
                  <i style={{ width: `${(d.week.runs / max) * 100}%`, background: over ? 'var(--s4)' : 'var(--s1)' }} />
                  <em style={{ left: `${(d.week.cap / max) * 100}%` }} aria-hidden="true" />
                </span>
                <span className="use-num" role="cell">
                  {d.week.runs}/{d.week.cap}
                  <small>{count(d.week.turns)} turns</small>
                </span>
              </div>
            );
          })}
        </div>
        <div className="legend" style={{ marginTop: 8 }}>
          <span>
            <i style={{ '--c': 'var(--s1)' }} />
            Runs this week
          </span>
          <span>
            <i className="cap" />
            Weekly cap
          </span>
        </div>
      </div>
      <div className="card c6" style={{ '--i': 7 }} data-testid="run-log">
        <div className="card-head">
          <span className="tag lilac">Run log</span>
          <span className="chip">Latest {recent.length}</span>
        </div>
        {recent.length ? (
          <div className="rows">
            {recent.map((r) => {
              const st = RUN_STATUS[r.status] || { t: r.status, tone: '' };
              const title = data.desks.find((d) => d.desk === r.desk)?.title || r.desk;
              return (
                <div className="row still" key={r.id}>
                  <span className="l">
                    <span style={{ minWidth: 0 }}>
                      <b>{title}</b>
                      <small>
                        {whenLabel(r.started_at)} · {TRIGGER[r.trigger] || r.trigger}
                        {r.note ? ` · ${r.note}` : ''}
                      </small>
                    </span>
                  </span>
                  <span className="v">
                    <span className={`chip ${st.tone}`}>{st.t}</span>
                    <small>{r.turns ? `${r.turns} turns · ${Math.round((r.duration_ms || 0) / 1000)} s` : '—'}</small>
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="empty-hint">No runs yet. The plan keeper runs first, in the evening.</p>
        )}
      </div>
    </>
  );
}

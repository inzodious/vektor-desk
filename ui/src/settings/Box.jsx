import { useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { getText, postJson, useApi } from '../lib/api.js';
import { HAND_COPY, QUEUED_TEXT, boxBusy, boxRefusal, boxState, composeView, cooldownText, lastLine, scriptView, splitBox } from '../lib/box.js';

function HandCopy({ lede }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(HAND_COPY);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="note box-hand" data-testid="box-hand">
      <Icon name="info" />
      <span>
        {lede}
        <code>{HAND_COPY}</code>
        <button className="btn ghost sm" type="button" onClick={copy}>
          <Icon name={copied ? 'check' : 'copy'} />
          {copied ? 'Copied' : 'Copy the line'}
        </button>
      </span>
    </div>
  );
}

function CopyCompose() {
  const [state, setState] = useState(null);
  const copy = async () => {
    try {
      const text = await getText('/api/box/compose.yaml');
      await navigator.clipboard.writeText(text);
      setState('copied');
    } catch (e) {
      setState(e?.status === 404 ? 'same' : 'failed');
    }
  };
  return (
    <span className="key-acts">
      <button className="btn sm" type="button" onClick={copy} data-testid="compose-copy">
        <Icon name={state === 'copied' ? 'check' : 'copy'} />
        {state === 'copied' ? 'Copied' : 'Copy compose.yaml'}
      </button>
      {state === 'same' ? <small className="job-note done">Already matches main; nothing to paste.</small> : null}
      {state === 'failed' ? <small className="job-note refused">Couldn’t copy. Try again in a moment.</small> : null}
    </span>
  );
}

function Compose({ cv, action, alive, mine, onRun }) {
  return (
    <div className={`box-script${cv.state === 'apply' ? '' : ' eyes'}`} data-testid="box-compose" data-state={cv.state}>
      <span>
        <b>{cv.line}</b>
        {cv.drift.length ? <small>What changed: {cv.drift.join('; ')}</small> : null}
      </span>
      {cv.state === 'apply' && action ? <ActionRow a={action} alive={alive} mine={mine} onRun={onRun} /> : null}
      {cv.state === 'eyes' ? (
        <>
          {cv.needs.length ? (
            <ul className="box-needs" data-testid="compose-needs">
              {cv.needs.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
          <small>Read it, then paste it into TrueNAS → Apps → vektor-desk → Edit.</small>
          {cv.copy ? <CopyCompose /> : null}
        </>
      ) : null}
    </div>
  );
}

function Output({ run }) {
  const out = typeof run?.output === 'string' ? run.output : Array.isArray(run?.output) ? run.output.join('\n') : '';
  if (!out.trim()) return null;
  return (
    <details className="box-out">
      <summary>Last output</summary>
      <pre>{out}</pre>
    </details>
  );
}

function ActionRow({ a, alive, mine, onRun }) {
  const st = boxState(a);
  const landed = mine?.phase === 'queued' && !!mine.id && a.last_run?.request_id === mine.id && !!a.last_run.finished;
  const waiting = mine?.phase === 'queued' && !landed;
  const ok = a.last_run?.result === 'ok' || a.last_run?.result === 'updated';
  const doneText = landed ? (ok ? `${a.title} done.` : a.last_run.result === 'skipped' ? `${a.title} skipped this time.` : `${a.title} didn’t finish. The output below says why.`) : null;
  const live = st.state === 'running' || st.state === 'queued' || waiting;
  const shown = live ? (st.state === 'running' ? 'running' : 'queued') : st.state;
  const cool = cooldownText(a);
  const summary = a.name === 'update-script' && a.last_run?.finished ? lastLine(a.last_run) : null;
  return (
    <div className="job-row box-row" data-box={a.name} data-state={shown}>
      <span className={`job-dot ${shown}`} aria-hidden="true" />
      <span className="job-text">
        <b>{a.title}</b>
        <small>{a.what}</small>
        <small className="job-when">{waiting && st.state !== 'running' ? QUEUED_TEXT : st.line}</small>
        {summary ? <small className="job-when">{summary}</small> : null}
        {doneText ? (
          <small className={`job-note ${ok ? 'done' : 'failed'}`} role="status">
            {doneText}
          </small>
        ) : null}
        {mine?.phase === 'refused' ? (
          <small className="job-note refused" role="status">
            {mine.text}
          </small>
        ) : null}
        <Output run={a.last_run} />
      </span>
      <span className="job-act">
        {live ? (
          <span className="chip ok">
            <i className="pulse" style={{ width: 6, height: 6 }} />
            {shown === 'running' ? 'Running' : 'Queued'}
          </span>
        ) : (
          <button className="btn ghost sm" type="button" disabled={!alive || !a.can_run} title={cool || (alive ? `${a.title} now` : 'The box hasn’t checked in yet')} aria-label={`${a.title} now`} onClick={() => onRun(a)}>
            <Icon name="play" />
            {cool && alive ? cool : 'Run'}
          </button>
        )}
      </span>
    </div>
  );
}

export function Box() {
  const [mine, setMine] = useState({});
  const pending = Object.values(mine).some((m) => m.phase === 'queued');
  const api = useApi('/api/box', { every: (d) => (boxBusy(d) || pending ? 5000 : 60000) });
  const d = api.data;
  const alive = !!d?.host_alive;
  const { list, update, compose } = splitBox(d?.actions);
  const sv = scriptView(d?.script);
  const cv = composeView(d?.compose);

  const run = async (a) => {
    setMine((m) => ({ ...m, [a.name]: { phase: 'queued', id: null } }));
    try {
      const r = await postJson(`/api/box/${encodeURIComponent(a.name)}/run`);
      setMine((m) => ({ ...m, [a.name]: { phase: 'queued', id: r?.request_id || null } }));
    } catch (e) {
      setMine((m) => ({ ...m, [a.name]: { phase: 'refused', text: boxRefusal(e) } }));
    }
    api.reload();
  };

  return (
    <div className="card c12" style={{ '--i': 4 }} data-testid="box" data-alive={d ? String(alive) : undefined}>
      <div className="card-head">
        <span className="tag coral">Box</span>
        <span className="acts">
          {sv ? (
            <span className={`chip ${sv.state === 'current' ? '' : 'watch'}`} data-testid="box-script-chip">
              {sv.state === 'current' ? 'Script current' : 'Script behind'}
            </span>
          ) : null}
          {d ? <span className={`chip ${alive ? 'ok' : 'watch'}`}>{alive ? 'Box checking in' : 'Box not checking in'}</span> : null}
        </span>
      </div>
      {api.loading && !d ? (
        <p className="empty-hint">Asking the box what it can do…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">{api.error.status === 404 ? 'Box buttons switch on with the next desk update.' : 'The desk API didn’t answer. The box buttons come back as soon as it does.'}</p>
      ) : (
        <>
          {!alive ? (
            <HandCopy lede="One hand step left, then never again: the box hasn’t checked in, so these buttons wait. Copy deploy.sh for the cron jobs once, from a TrueNAS shell:" />
          ) : (
            <p className="muted job-lede">Chores for the NAS itself. The box picks each one up within 5 minutes and the result lands here.</p>
          )}
          {sv && sv.state !== 'current' ? (
            <div className="box-script" data-testid="box-script" data-state={sv.state}>
              <span>
                <b>{sv.line}</b>
                {sv.range ? <small className="num">{sv.range}</small> : null}
              </span>
              {sv.state === 'off' ? <HandCopy lede="Copy it by hand from a TrueNAS shell:" /> : update ? <ActionRow a={update} alive={alive} mine={mine[update.name]} onRun={run} /> : null}
            </div>
          ) : null}
          {cv ? <Compose cv={cv} action={compose} alive={alive} mine={compose ? mine[compose.name] : null} onRun={run} /> : null}
          <div className="job-list">
            {list.map((a) => (
              <ActionRow key={a.name} a={a} alive={alive} mine={mine[a.name]} onRun={run} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

import { useEffect, useRef, useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { putFile, useApi } from '../lib/api.js';
import { BROKER, fileLine, inboxFiles, inboxRefusal, limitText, precheck, savedText } from '../lib/inbox.js';
import { jobWord, refusalText, runAndWait } from '../lib/jobs.js';
import { plural } from '../lib/format.js';

export function Inbox() {
  const api = useApi('/api/inbox');
  const [msg, setMsg] = useState(null);
  const [read, setRead] = useState(null);
  const [over, setOver] = useState(false);
  const input = useRef(null);
  const card = useRef(null);
  const ctl = useRef(null);
  const d = api.data;
  const files = inboxFiles(d);
  const job = d?.brokers?.[BROKER]?.import_job || 'engine-lots';

  useEffect(() => {
    ctl.current = new AbortController();
    return () => ctl.current.abort();
  }, []);
  useEffect(() => {
    if (d && window.location.hash === '#inbox') card.current?.scrollIntoView({ block: 'start' });
  }, [d]);

  const send = async (file) => {
    setRead(null);
    const bad = precheck(file, d);
    if (bad) {
      setMsg({ phase: 'refused', text: bad });
      return;
    }
    setMsg({ phase: 'waiting', text: `Uploading ${file.name}…` });
    try {
      const r = await putFile(`/api/inbox/${BROKER}/${encodeURIComponent(file.name)}`, file);
      setMsg({ phase: 'done', text: savedText(r), job: r?.import_job || job });
      api.reload();
    } catch (e) {
      setMsg({ phase: 'refused', text: inboxRefusal(e) });
    }
  };

  const readNow = async () => {
    const title = jobWord({ name: job }).title;
    setRead({ phase: 'waiting', text: null });
    try {
      const last = await runAndWait(job, { signal: ctl.current.signal });
      const ok = last?.result !== 'failed';
      setRead({ phase: ok ? 'done' : 'failed', text: ok ? `${title} done. Your tax lots are in.` : `${title} didn’t finish${last?.detail ? `: ${last.detail}` : '.'}` });
    } catch (e) {
      if (e.name !== 'AbortError') setRead({ phase: 'refused', text: refusalText(e) });
    }
  };

  const pick = (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (f) send(f);
  };
  const drop = (e) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) send(f);
  };

  return (
    <div className="card c12" id="inbox" ref={card} style={{ '--i': 4 }} data-testid="inbox">
      <div className="card-head">
        <span className="tag sky">Inbox</span>
        <span className="acts">{d ? <span className="chip">{files.length ? `${plural(files.length, 'file')} waiting` : 'Empty'}</span> : null}</span>
      </div>
      {api.loading && !d ? (
        <p className="empty-hint">Looking in the inbox…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">{api.error.status === 404 ? 'Upload switches on with the next desk update.' : 'The desk API didn’t answer. The inbox comes back as soon as it does.'}</p>
      ) : (
        <div className="inbox-grid">
          <label
            className={`inbox-drop${over ? ' over' : ''}`}
            data-testid="inbox-drop"
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={drop}
          >
            <input ref={input} type="file" accept={(d?.suffixes || ['.csv', '.json']).join(',')} onChange={pick} data-testid="inbox-file" />
            <Icon name="layers" />
            <b>Drop a Fidelity lot export here</b>
            <small>
              or <u>choose a file</u> · {limitText(d)}
            </small>
          </label>
          <div className="inbox-side">
            {msg ? (
              <p className={`inbox-msg ${msg.phase}`} role="status" data-testid="inbox-msg" data-phase={msg.phase}>
                {msg.text}
              </p>
            ) : (
              <p className="muted inbox-msg">Lots reads the newest export each night. Read it now when you want the tax checks sooner.</p>
            )}
            {msg?.phase === 'done' || files.length ? (
              <div className="inbox-read">
                {read?.phase === 'waiting' ? (
                  <span className="chip ok">
                    <i className="pulse" style={{ width: 6, height: 6 }} />
                    Reading
                  </span>
                ) : (
                  <button className={`btn sm${msg?.phase === 'done' ? '' : ' ghost'}`} type="button" onClick={readNow} data-testid="inbox-read">
                    <Icon name="play" />
                    Read it now
                  </button>
                )}
                {read?.text ? (
                  <small className={`job-note ${read.phase}`} role="status">
                    {read.text}
                  </small>
                ) : null}
              </div>
            ) : null}
            {files.length ? (
              <ul className="inbox-files" data-testid="inbox-files">
                {files.map((f) => (
                  <li key={f.name}>
                    <b>{f.name}</b>
                    <small>{fileLine(f)}</small>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-hint" style={{ margin: 0 }}>
                Nothing in the inbox yet.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

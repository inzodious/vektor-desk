import { useEffect, useRef, useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { postJson, useApi } from '../lib/api.js';
import { fileWord, keyCheck, keyCount, keyRefusal, keyState, keyWord } from '../lib/keys.js';
import { About } from '../components/About.jsx';

function KeyRow({ k, ready, open, note, onOpen, onClose, onSave }) {
  const st = keyState(k);
  const word = keyWord(k);
  const input = useRef(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  const submit = async (e) => {
    e.preventDefault();
    const el = input.current;
    const bad = keyCheck(k.name, el?.value);
    if (bad) {
      setErr(bad);
      return;
    }
    setBusy(true);
    setErr(null);
    const value = el.value.trim();
    el.value = '';
    const msg = await onSave(k, value);
    setBusy(false);
    if (msg) setErr(msg);
  };

  return (
    <div className="job-row key-row" data-key={k.name} data-state={st.state}>
      <span className={`job-dot ${st.state === 'set' ? 'ok' : st.state === 'pending' ? 'queued' : st.state === 'unset' ? 'never' : 'failed'}`} aria-hidden="true" />
      <span className="job-text">
        <span className="key-head">
          <b data-testid="key-word">{word}</b>
          <code className="key-name">{k.name}</code>
        </span>
        <small>
          {k.what} · {fileWord(k.file)}
        </small>
        <small className="job-when">{st.line}</small>
        {note ? (
          <small className="job-note done" role="status">
            {note}
          </small>
        ) : null}
        {open ? (
          <form className="key-form" onSubmit={submit} autoComplete="off">
            <label className="sr-only" htmlFor={`key-${k.name}`}>
              New value for {word}
            </label>
            <input
              id={`key-${k.name}`}
              ref={input}
              type={k.secret ? 'password' : 'text'}
              autoComplete="off"
              spellCheck={false}
              autoCapitalize="off"
              placeholder={k.secret ? 'Paste it here; it’s never shown again' : 'Type the value'}
              data-testid="key-input"
            />
            <span className="key-acts">
              <button className="btn sm" type="submit" disabled={busy}>
                <Icon name="shield" />
                {busy ? 'Sealing…' : 'Seal and send'}
              </button>
              <button className="btn sm ghost" type="button" onClick={onClose}>
                Cancel
              </button>
            </span>
            {err ? (
              <small className="job-note refused" role="alert">
                {err}
              </small>
            ) : null}
          </form>
        ) : null}
      </span>
      <span className="job-act">
        {st.state === 'pending' ? (
          <span className="chip ok">
            <i className="pulse" style={{ width: 6, height: 6 }} />
            Saving
          </span>
        ) : open ? null : (
          <button className="btn ghost sm" type="button" disabled={!ready} title={ready ? undefined : 'The box hasn’t checked in with its lock yet'} aria-label={`${k.set ? 'Replace' : 'Set'} ${word}`} onClick={() => onOpen(k.name)}>
            <Icon name={k.set ? 'swap' : 'plus'} />
            {k.set ? 'Replace' : 'Set'}
          </button>
        )}
      </span>
    </div>
  );
}

export function Keys() {
  const [open, setOpen] = useState(null);
  const [notes, setNotes] = useState({});
  const api = useApi('/api/box/keys', { every: (d) => ((d?.keys || []).some((k) => k.pending) ? 10000 : 0) });
  const card = useRef(null);
  const d = api.data;
  const ready = !!d?.ready;
  const n = keyCount(d);

  useEffect(() => {
    if (d && window.location.hash === '#keys') card.current?.scrollIntoView({ block: 'start' });
  }, [d]);

  const save = async (k, value) => {
    try {
      await postJson(`/api/box/keys/${encodeURIComponent(k.name)}`, { value }, { method: 'PUT' });
      setOpen(null);
      setNotes((m) => ({ ...m, [k.name]: 'Sealed and sent. The box saves it within 5 min.' }));
      api.reload();
      return null;
    } catch (e) {
      return keyRefusal(e);
    }
  };

  return (
    <div className="card c12" id="keys" ref={card} style={{ '--i': 5 }} data-testid="keys" data-ready={d ? String(ready) : undefined}>
      <div className="card-head">
        <span className="tag mint">Keys</span>
        <span className="acts">
          {d ? (
            <span className="chip">
              {n.set} of {n.total} set
            </span>
          ) : null}
          {n.pending ? <span className="chip ok">{n.pending} on the way</span> : null}
        </span>
      </div>
      {api.loading && !d ? (
        <p className="empty-hint">Asking the box which keys it has…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">{api.error.status === 404 ? 'Keys switch on with the next desk update.' : 'The desk API didn’t answer. Keys come back as soon as it does.'}</p>
      ) : (
        <>
          {!ready ? (
            <div className="note" data-testid="keys-wait">
              <Icon name="info" />
              <span>The box hasn’t shared its lock yet, so keys wait here. It does on its next check-in once the box script is current (Box → Update box script).</span>
            </div>
          ) : (
            <About label="How keys are kept" testid="keys-about">
              <p>Write-only. The desk seals each value to the box’s own lock, the box saves it within 5 minutes, and nothing ever shows it again. Saving a key redeploys the desk.</p>
            </About>
          )}
          <div className="job-list">
            {(d?.keys || []).map((k) => (
              <KeyRow
                key={k.name}
                k={k}
                ready={ready}
                open={open === k.name}
                note={notes[k.name] && !open ? notes[k.name] : null}
                onOpen={(name) => {
                  setNotes((m) => ({ ...m, [name]: null }));
                  setOpen(name);
                }}
                onClose={() => setOpen(null)}
                onSave={save}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

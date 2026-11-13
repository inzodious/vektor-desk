import { useEffect, useRef, useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { postJson, useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { bandBody, bandCheck, bandText, droppedText, editRefusal, meter, nudgeLine, pct, savedText, startForm, statusWord, suggestLine, weightLine } from '../lib/convictions.js';
import { About } from '../components/About.jsx';

// ---------- meter ----------
function Meter({ item }) {
  const m = meter(item);
  const label = `${item.symbol}: band ${bandText(item)}${item.weight_pct != null ? `, weight ${pct(item.weight_pct)}` : ''}`;
  return (
    <span className="cv-meter" role="img" aria-label={label}>
      <span className="cv-track">
        <i className="cv-band" style={{ left: `${m.from}%`, width: `${Math.max(1, m.to - m.from)}%` }} />
        {m.mark != null ? <i className={`cv-mark ${item.status || ''}`} style={{ left: `${m.mark}%` }} /> : null}
      </span>
      <span className="cv-scale" aria-hidden="true">
        <small>0%</small>
        <small>{pct(m.max)}</small>
      </span>
    </span>
  );
}

// ---------- form ----------
function BandForm({ item, suggested, taken, onDone, onCancel }) {
  const [form, setForm] = useState(() => startForm(item, suggested));
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [confirm, setConfirm] = useState(false);
  const editing = Boolean(item);
  const first = useRef(null);
  useEffect(() => {
    first.current?.focus();
  }, []);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const id = (k) => `cv-${item?.symbol || 'new'}-${k}`;

  const save = async (e) => {
    e.preventDefault();
    const bad = bandCheck(form, { taken, editing });
    if (bad) {
      setErr(bad);
      return;
    }
    const symbol = form.symbol.trim().toUpperCase();
    setBusy('save');
    setErr(null);
    try {
      const r = await postJson(`/api/decisions/convictions/${encodeURIComponent(symbol)}`, bandBody(form), { method: 'PUT' });
      onDone(savedText(r, symbol));
    } catch (x) {
      setErr(editRefusal(x));
      setBusy(null);
    }
  };

  const drop = async () => {
    if (!confirm) {
      setConfirm(true);
      return;
    }
    setBusy('drop');
    setErr(null);
    try {
      const r = await postJson(`/api/decisions/convictions/${encodeURIComponent(item.symbol)}`, {}, { method: 'DELETE' });
      onDone(droppedText(r, item.symbol));
    } catch (x) {
      setErr(editRefusal(x));
      setBusy(null);
      setConfirm(false);
    }
  };

  return (
    <form className="cv-form" onSubmit={save} noValidate data-testid="cv-form">
      {!editing ? (
        <div className="field cv-sym">
          <label htmlFor={id('sym')}>Ticker</label>
          <input id={id('sym')} value={form.symbol} onChange={set('symbol')} autoCapitalize="characters" spellCheck={false} autoComplete="off" placeholder="ACME" ref={first} data-testid="cv-symbol" />
        </div>
      ) : null}
      <div className="field">
        <label htmlFor={id('min')}>Floor %</label>
        <input id={id('min')} value={form.min} onChange={set('min')} inputMode="decimal" placeholder="0" data-testid="cv-min" />
      </div>
      <div className="field">
        <label htmlFor={id('max')}>Ceiling %</label>
        <input id={id('max')} ref={editing ? first : undefined} value={form.max} onChange={set('max')} inputMode="decimal" placeholder={suggested ? String(suggested.band_max_pct) : '10'} data-testid="cv-max" />
      </div>
      <div className="field cv-note">
        <label htmlFor={id('note')}>Why you hold it</label>
        <input id={id('note')} value={form.note} onChange={set('note')} maxLength={200} placeholder="Optional, for future you" data-testid="cv-note-input" />
      </div>
      <span className="cv-acts">
        <button className="btn sm" type="submit" disabled={Boolean(busy)} data-testid="cv-save">
          <Icon name="check" />
          {busy === 'save' ? 'Saving…' : editing ? 'Save band' : 'Add hold'}
        </button>
        <button className="btn sm ghost" type="button" onClick={onCancel} disabled={Boolean(busy)}>
          Cancel
        </button>
        {editing ? (
          <button className={`btn sm ghost cv-drop${confirm ? ' armed' : ''}`} type="button" onClick={drop} disabled={Boolean(busy)} data-testid="cv-drop">
            {busy === 'drop' ? 'Removing…' : confirm ? `Yes, remove ${item.symbol}` : 'Remove hold'}
          </button>
        ) : null}
      </span>
      {err ? (
        <small className="job-note refused cv-err" role="alert" data-testid="cv-err">
          {err}
        </small>
      ) : null}
    </form>
  );
}

// ---------- rows ----------
function Row({ item, open, suggested, taken, onOpen, onDone, onCancel }) {
  const st = statusWord(item);
  const nudge = nudgeLine(item);
  return (
    <li className="cv-row" data-cv={item.symbol} data-status={item.enabled === false ? 'paused' : item.status || 'none'}>
      <span className="cv-top">
        <button type="button" className="sym sym-btn" data-sym={item.symbol}>
          {item.symbol}
        </button>
        <span className="cv-band-text">
          <b>{bandText(item)}</b>
          <small className="muted">{weightLine(item, dayLabel)}</small>
        </span>
        <span className={`chip ${st.tone}`} data-testid="cv-status">
          {st.t}
        </span>
        {!open ? (
          <button className="btn ghost sm" type="button" onClick={onOpen} aria-label={`Edit ${item.symbol}’s band`} data-testid="cv-edit">
            Edit
          </button>
        ) : null}
      </span>
      <Meter item={item} />
      {item.note ? <small className="cv-why">“{item.note}”</small> : null}
      {nudge ? <small className="muted cv-nudge">{nudge}</small> : null}
      {open ? <BandForm item={item} suggested={suggested} taken={taken} onDone={onDone} onCancel={onCancel} /> : null}
    </li>
  );
}

// ---------- card ----------
export function Convictions({ i = 2 }) {
  const api = useApi('/api/decisions/convictions');
  const [open, setOpen] = useState(null);
  const [msg, setMsg] = useState(null);
  const d = api.data;
  if (api.error?.status === 404) return null;
  const items = d?.items || [];
  const suggested = d?.suggested || null;
  const taken = items.map((c) => c.symbol);
  const done = (text) => {
    setMsg(text);
    setOpen(null);
    api.reload();
  };
  const show = (key) => {
    setMsg(null);
    setOpen(key);
  };
  return (
    <div className="card c12 cv" style={{ '--i': i }} data-testid="convictions" data-count={items.length}>
      <div className="card-head">
        <span className="tag lilac">Conviction holds</span>
        <span className="acts">
          {suggested ? <span className="chip">{`Band ${suggested.from_band} ceiling ${pct(suggested.band_max_pct)}`}</span> : null}
          {d && open !== 'new' ? (
            <button className="btn sm" type="button" onClick={() => show('new')} data-testid="cv-add">
              <Icon name="plus" />
              Add a hold
            </button>
          ) : null}
        </span>
      </div>
      {api.loading && !d ? (
        <p className="empty-hint">Reading your holds…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">The desk API didn’t answer. Your holds come back as soon as it does.</p>
      ) : (
        <>
          <About label="How a conviction hold works" testid="cv-about">
            <p>A stock you mean to keep long gets its own band instead of the single-stock cap. Above the ceiling, the desk nudges a trim once a week. It never trades.</p>
          </About>
          {msg ? (
            <p className="job-note done" role="status" data-testid="cv-msg">
              {msg}
            </p>
          ) : null}
          {open === 'new' ? (
            <div className="cv-new" data-testid="cv-new">
              <small className="muted">{suggestLine(suggested)}</small>
              <BandForm suggested={suggested} taken={taken} onDone={done} onCancel={() => setOpen(null)} />
            </div>
          ) : null}
          {items.length ? (
            <ul className="cv-rows">
              {items.map((c) => (
                <Row key={c.rule_id || c.symbol} item={c} open={open === c.symbol} suggested={suggested} taken={taken} onOpen={() => show(c.symbol)} onDone={done} onCancel={() => setOpen(null)} />
              ))}
            </ul>
          ) : open !== 'new' ? (
            <p className="empty-hint" data-testid="cv-empty">
              No conviction holds yet. Every single stock sits under the single-stock cap. {suggestLine(suggested)}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

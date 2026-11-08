import { useState } from 'react';
import { Combo } from '../components/Combo.jsx';
import { Icon } from '../components/Icon.jsx';
import { Panel } from '../components/Panel.jsx';
import { postJson, useApi } from '../lib/api.js';
import { editRefusal } from '../lib/convictions.js';
import { GROUPS, changeCount, changesFrom, formFrom, lockedGroups, pendingLine, savedLine } from '../lib/profileEdit.js';

// ---------- fields ----------
function Field({ f, value, error, onChange }) {
  const id = `pe-${f.key.replace('.', '-')}`;
  if (f.kind === 'pick') {
    return (
      <div className="pe-pick" data-field={f.key}>
        <Combo label={f.label} options={f.options} value={value} onChange={onChange} />
      </div>
    );
  }
  const wide = f.kind === 'themes' || f.kind === 'list';
  return (
    <div className={`field${wide ? ' pe-wide' : ''}${error ? ' bad' : ''}`} data-field={f.key}>
      <label htmlFor={id}>{f.label}</label>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode={f.kind === 'num' || f.kind === 'pct' ? 'decimal' : undefined}
        placeholder={f.placeholder}
        spellCheck={false}
        autoComplete="off"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-err` : undefined}
      />
      {error ? (
        <small className="pe-err" id={`${id}-err`}>
          {error}
        </small>
      ) : null}
    </div>
  );
}

// ---------- form ----------
function Form({ data, msg, setMsg, onSaved }) {
  const profile = data.profile || {};
  const [base] = useState(() => formFrom(profile));
  const [form, setForm] = useState(base);
  const [busy, setBusy] = useState(false);
  const [tried, setTried] = useState(false);
  const editable = Array.isArray(data.editable) ? data.editable : null;
  const locked = lockedGroups(editable);
  const { changes, errors } = changesFrom(profile, form, editable);
  const n = changeCount(changes);
  const bad = Object.keys(errors).length;

  const save = async (e) => {
    e.preventDefault();
    setTried(true);
    if (bad || !n) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await postJson('/api/decisions/profile', { changes }, { method: 'PATCH' });
      setMsg({ ok: true, text: savedLine(r) });
      setBusy(false);
      onSaved(r);
    } catch (x) {
      setMsg({ ok: false, text: editRefusal(x) });
      setBusy(false);
    }
  };

  const dirty = (key) => form[key] !== base[key];
  return (
    <form className="pe" onSubmit={save} noValidate data-testid="profile-form" data-changes={n}>
      {GROUPS.filter((g) => !locked.includes(g.id)).map((g) => (
        <fieldset className="pe-group" key={g.id} data-group={g.id}>
          <legend>{g.title}</legend>
          <p className="muted pe-sub">{g.sub}</p>
          <div className="pe-fields">
            {g.fields.map((f) => (
              <Field key={f.key} f={f} value={form[f.key]} error={(tried || dirty(f.key)) && errors[f.key]} onChange={(v) => setForm((s) => ({ ...s, [f.key]: v }))} />
            ))}
          </div>
        </fieldset>
      ))}
      <p className="muted pe-note">Your band comes from the risk check, desks switch on under Desks, and conviction bands live on the risk check page. Deposits are read from your activity.</p>
      <div className="pe-bar">
        <span className={`pe-count${n ? ' on' : ''}`} data-testid="profile-pending">
          {bad ? `${bad === 1 ? '1 field needs' : `${bad} fields need`} a fix` : pendingLine(n)}
        </span>
        <button
          className="btn sm ghost"
          type="button"
          disabled={busy || !n}
          onClick={() => {
            setForm(base);
            setTried(false);
          }}
        >
          Undo
        </button>
        <button className="btn sm" type="submit" disabled={busy || !n || Boolean(bad)} data-testid="profile-save">
          <Icon name="check" />
          {busy ? 'Saving…' : 'Save to desk.yaml'}
        </button>
      </div>
      {msg ? (
        <p className={`job-note ${msg.ok ? 'done' : 'refused'}`} role={msg.ok ? 'status' : 'alert'} data-testid="profile-msg">
          {msg.text}
        </p>
      ) : null}
    </form>
  );
}

// ---------- panel ----------
export function ProfileEditor({ open, onClose, onSaved }) {
  const api = useApi(open ? '/api/decisions/profile' : null);
  const [msg, setMsg] = useState(null);
  const d = api.data;
  const close = () => {
    setMsg(null);
    onClose();
  };
  return (
    <Panel open={open} onClose={close} title="Edit the profile" sub="Writes only the sections you change, and keeps desk.yaml.bak first." crumbs={[{ label: 'Settings', go: close }]}>
      {api.loading && !d ? (
        <p className="empty-hint">Reading desk.yaml…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">{editRefusal(api.error)}</p>
      ) : d ? (
        <Form
          key={d.version}
          data={d}
          msg={msg}
          setMsg={setMsg}
          onSaved={(r) => {
            api.reload();
            onSaved?.(r);
          }}
        />
      ) : null}
    </Panel>
  );
}

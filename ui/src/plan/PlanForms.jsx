import { useEffect, useRef, useState } from 'react';
import { Combo } from '../components/Combo.jsx';
import { Icon } from '../components/Icon.jsx';
import { postJson } from '../lib/api.js';
import { accountLabel } from '../live/context.js';
import { ROLE, STEP_KIND, approvesOnSave, planCheck, planFromForm, refusal, savedText, startPlan, startStep, stepCheck, stepFromForm, stepShape, withStep } from '../lib/stockPlans.js';

const ROLE_OPTIONS = Object.entries(ROLE).map(([v, r]) => ({ v, t: r.t }));
const FUNDING = [
  { v: 'deposits', t: 'New deposits only' },
  { v: 'any', t: 'Deposits or cash' },
];

function Field({ id, label, wide, children }) {
  return (
    <div className={`field${wide ? ' sp-wide' : ''}`}>
      <label htmlFor={id}>{label}</label>
      {children}
    </div>
  );
}

function Err({ text }) {
  if (!text) return null;
  return (
    <small className="job-note refused sp-err" role="alert" data-testid="plan-err">
      {text}
    </small>
  );
}

async function put(symbol, plan, approve) {
  return postJson(`/api/decisions/plans/${encodeURIComponent(symbol)}`, approve ? { plan, approve: true } : { plan }, { method: 'PUT' });
}

// ---------- plan form ----------
export function PlanForm({ symbol, plan, fact, onDone, onCancel }) {
  const [form, setForm] = useState(() => startPlan(plan, fact));
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const first = useRef(null);
  useEffect(() => {
    first.current?.focus();
  }, []);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const id = (k) => `sp-${symbol}-${k}`;
  const input = (k, label, more = {}) => (
    <Field id={id(k)} label={label}>
      <input id={id(k)} value={form[k]} onChange={set(k)} inputMode="decimal" autoComplete="off" data-testid={`pf-${k}`} {...more} />
    </Field>
  );

  const save = async (approve) => {
    const bad = planCheck(form);
    if (bad) {
      setErr(bad);
      return;
    }
    setBusy(approve ? 'approve' : 'draft');
    setErr(null);
    try {
      const r = await put(symbol, planFromForm(form, plan), approve);
      onDone(savedText(r, symbol, approve));
    } catch (x) {
      setErr(refusal(x));
      setBusy(null);
    }
  };

  return (
    <form
      className="sp-form"
      noValidate
      data-testid="plan-form"
      onSubmit={(e) => {
        e.preventDefault();
        save(false);
      }}
    >
      <div className="sp-form-head">
        <b>{plan ? `Edit the ${symbol} plan` : `Write a plan for ${symbol}`}</b>
        {!plan && fact?.zones ? <small className="muted">Zones start from its monthly swing. Change anything.</small> : null}
      </div>
      <div className="sp-fields">
        <Combo label="Role" options={ROLE_OPTIONS} value={form.role} onChange={(v) => setForm((f) => ({ ...f, role: v }))} />
        {input('min', 'Band floor %', { placeholder: '0' })}
        {input('max', 'Band ceiling %', { placeholder: '10' })}
        <Field id={id('review')} label="Next review">
          <input id={id('review')} type="date" value={form.review} onChange={set('review')} data-testid="pf-review" />
        </Field>
        <Field id={id('thesis')} label="Why you hold it" wide>
          <textarea id={id('thesis')} ref={first} rows={3} maxLength={2000} value={form.thesis} onChange={set('thesis')} placeholder="One or two lines, for future you" data-testid="pf-thesis" />
        </Field>
      </div>
      <span className="kicker">Add rule</span>
      <div className="sp-fields">
        {input('addLow', 'Add from $')}
        {input('addHigh', 'Add up to $')}
        {input('addMax', 'Most per month $', { placeholder: 'No cap' })}
        <div className="sp-two">
          <Combo label="Paid from" options={FUNDING} value={form.depositsOnly ? 'deposits' : 'any'} onChange={(v) => setForm((f) => ({ ...f, depositsOnly: v === 'deposits' }))} />
        </div>
        <Field id={id('addNote')} label="Add note" wide>
          <input id={id('addNote')} value={form.addNote} onChange={set('addNote')} maxLength={300} placeholder="Optional" data-testid="pf-addNote" />
        </Field>
      </div>
      <span className="kicker">Trim rule</span>
      <div className="sp-fields">
        {input('trimAbove', 'Trim above %')}
        {input('trimTo', 'Back to %')}
        {input('trimLow', 'Trim from $')}
        {input('trimHigh', 'Trim up to $')}
        <Field id={id('trimNote')} label="Trim note" wide>
          <input id={id('trimNote')} value={form.trimNote} onChange={set('trimNote')} maxLength={300} placeholder="Optional" data-testid="pf-trimNote" />
        </Field>
      </div>
      <span className="kicker">Exits and taxes</span>
      <div className="sp-fields">
        <Field id={id('exits')} label="What would make you sell, one per line" wide>
          <textarea id={id('exits')} rows={2} value={form.exits} onChange={set('exits')} data-testid="pf-exits" />
        </Field>
        <Field id={id('tax')} label="Tax notes" wide>
          <textarea id={id('tax')} rows={2} maxLength={1200} value={form.tax} onChange={set('tax')} data-testid="pf-tax" />
        </Field>
      </div>
      <p className="muted sp-small">Margin is never part of a plan. Nothing here places a trade.</p>
      <span className="sp-acts">
        <button className="btn sm" type="button" disabled={Boolean(busy)} onClick={() => save(true)} data-testid="pf-approve">
          <Icon name="check" />
          {busy === 'approve' ? 'Saving…' : 'Save and approve'}
        </button>
        <button className="btn sm ghost" type="submit" disabled={Boolean(busy)} data-testid="pf-draft">
          {busy === 'draft' ? 'Saving…' : 'Save as a draft'}
        </button>
        <button className="btn sm ghost" type="button" onClick={onCancel} disabled={Boolean(busy)}>
          Cancel
        </button>
      </span>
      <Err text={err} />
    </form>
  );
}

// ---------- step form ----------
export function StepForm({ symbol, plan, fact, meta, onDone, onCancel }) {
  const kinds = (meta?.step_kinds || Object.keys(STEP_KIND)).filter((k) => STEP_KIND[k]).map((k) => ({ v: k, t: STEP_KIND[k] }));
  const lots = Object.entries(meta?.lot_methods || {}).map(([v, t]) => ({ v, t: `${t.charAt(0).toUpperCase()}${t.slice(1)}` }));
  const accounts = [{ v: '', t: 'Any account' }, ...[...new Set((fact?.accounts || []).map(accountLabel))].map((a) => ({ v: a, t: a }))];
  const atLoss = (fact?.numbers?.unrealized_usd ?? 0) < 0;
  const [form, setForm] = useState(() => startStep(atLoss ? 'harvest' : 'add', meta?.step_templates));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const shape = stepShape(form.kind);
  const approve = approvesOnSave(plan);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const id = (k) => `st-${symbol}-${k}`;

  const save = async (e) => {
    e.preventDefault();
    const bad = stepCheck(form);
    if (bad) {
      setErr(bad);
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const r = await put(symbol, withStep(plan, stepFromForm(form)), approve);
      onDone(savedText(r, symbol, approve));
    } catch (x) {
      setErr(refusal(x));
      setBusy(false);
    }
  };

  return (
    <form className="sp-form" noValidate onSubmit={save} data-testid="step-form" data-kind={form.kind}>
      <div className="sp-form-head">
        <b>Add a step to the {symbol} plan</b>
        <small className="muted">{approve ? 'It goes straight onto the approved plan.' : 'It joins the draft. Approve the draft to put it in force.'}</small>
      </div>
      <div className="sp-fields">
        <div className="sp-two">
          <Combo label="Step" options={kinds} value={form.kind} onChange={(v) => setForm(startStep(v, meta?.step_templates))} />
        </div>
        {shape.text ? (
          <Field id={id('text')} label="What to do" wide>
            <input id={id('text')} value={form.text} onChange={set('text')} maxLength={200} data-testid="sf-text" />
          </Field>
        ) : null}
        {shape.shares ? (
          <Field id={id('shares')} label="Shares">
            <input id={id('shares')} value={form.shares} onChange={set('shares')} inputMode="decimal" placeholder={form.kind === 'add' ? 'Optional' : '10 or all'} autoComplete="off" data-testid="sf-shares" />
          </Field>
        ) : null}
        {shape.amount ? (
          <Field id={id('amount')} label="Dollars">
            <input id={id('amount')} value={form.amount} onChange={set('amount')} inputMode="decimal" placeholder="Optional" autoComplete="off" data-testid="sf-amount" />
          </Field>
        ) : null}
        <Field id={id('due')} label={shape.until ? 'From' : 'On'}>
          <input id={id('due')} type="date" value={form.due} onChange={set('due')} data-testid="sf-due" />
        </Field>
        {shape.until ? (
          <Field id={id('until')} label="Until">
            <input id={id('until')} type="date" value={form.until} onChange={set('until')} data-testid="sf-until" />
          </Field>
        ) : null}
        {shape.account ? <Combo label="Account" options={accounts} value={form.account} onChange={(v) => setForm((f) => ({ ...f, account: v }))} /> : null}
        {shape.lots && lots.length ? (
          <div className="sp-two">
            <Combo label="Lots" options={lots} value={form.lots} onChange={(v) => setForm((f) => ({ ...f, lots: v }))} />
          </div>
        ) : null}
        {shape.noBuy ? (
          <Field id={id('noBuy')} label="No buys after, days">
            <input id={id('noBuy')} value={form.noBuy} onChange={set('noBuy')} inputMode="numeric" placeholder="0" autoComplete="off" data-testid="sf-noBuy" />
          </Field>
        ) : null}
        {shape.when ? (
          <Field id={id('when')} label="Or when" wide>
            <input id={id('when')} value={form.when} onChange={set('when')} maxLength={200} placeholder="No date? Say what it waits on" data-testid="sf-when" />
          </Field>
        ) : null}
        <Field id={id('note')} label="Note" wide>
          <input id={id('note')} value={form.note} onChange={set('note')} maxLength={400} placeholder="Optional" data-testid="sf-note" />
        </Field>
      </div>
      <span className="sp-acts">
        <button className="btn sm" type="submit" disabled={busy} data-testid="sf-save">
          <Icon name="plus" />
          {busy ? 'Saving…' : 'Add step'}
        </button>
        <button className="btn sm ghost" type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </span>
      <Err text={err} />
    </form>
  );
}

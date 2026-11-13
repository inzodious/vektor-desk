import { useEffect, useRef, useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { postJson } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { approvesOnSave, canMarkDone, canUndo, draftLine, planChanges, refusal, ruleLines, savedText, sortSteps, withoutStep } from '../lib/stockPlans.js';
import { useConsole } from '../research/consoleContext.js';
import { PlanForm, StepForm } from './PlanForms.jsx';
import { PlanBlock, RoleChip, StepRow, VersionChip } from './PlanParts.jsx';
import { About } from '../components/About.jsx';

const SHOW = 4;
const base = (symbol) => `/api/decisions/plans/${encodeURIComponent(symbol)}`;

// ---------- draft bar ----------
function DraftBar({ plan, busy, onApprove, onDiscard }) {
  const [sure, setSure] = useState(false);
  const changes = planChanges(plan);
  return (
    <div className="sp-draft" data-testid="plan-draft" data-author={plan.author}>
      <span className="sp-draft-text">
        <b>{plan.author === 'desk' ? 'The Plan desk drafted this.' : 'Your draft, not in force yet.'}</b>
        {plan.summary ? <span>{plan.summary}</span> : null}
        {changes.length ? <small data-testid="plan-changes">Changed: {changes.join(', ')}</small> : null}
        <small>{draftLine(plan)}</small>
      </span>
      <span className="sp-acts">
        <button className="btn sm" type="button" disabled={Boolean(busy)} onClick={onApprove} data-testid="plan-approve">
          <Icon name="check" />
          {busy === 'approve' ? 'Approving…' : 'Approve'}
        </button>
        <button className={`btn sm ghost${sure ? ' armed' : ''}`} type="button" disabled={Boolean(busy)} onClick={() => (sure ? onDiscard() : setSure(true))} data-testid="plan-discard">
          {busy === 'discard' ? 'Discarding…' : sure ? 'Yes, discard the draft' : 'Discard'}
        </button>
      </span>
    </div>
  );
}

// ---------- thesis and rules ----------
function Thesis({ plan }) {
  const rules = ruleLines(plan);
  const exits = plan.exit_conditions || [];
  const catalysts = plan.catalysts || [];
  return (
    <details className="job-more sp-fold" data-testid="plan-thesis">
      <summary>Thesis and rules</summary>
      <div className="sp-thesis">
        <p>{plan.thesis}</p>
        {rules.length ? (
          <dl className="sp-rules">
            {rules.map((r) => (
              <div key={r.id} data-rule={r.id}>
                <dt>{r.label}</dt>
                <dd>
                  {r.text}
                  {r.note ? <small>{r.note}</small> : null}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
        {exits.length ? (
          <div>
            <span className="kicker">Sell if</span>
            <ul className="sp-list">
              {exits.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {catalysts.length ? (
          <div>
            <span className="kicker">Watching for</span>
            <ul className="sp-list">
              {catalysts.map((c) => (
                <li key={`${c.text}-${c.date || ''}`}>
                  {c.text}
                  {c.date ? ` · ${dayLabel(c.date)}` : ''}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {plan.tax_notes ? (
          <div>
            <span className="kicker">Taxes</span>
            <p>{plan.tax_notes}</p>
          </div>
        ) : null}
        {plan.next_review ? (
          <small className="muted">
            Next review {dayLabel(plan.next_review, true)}
            {plan.review_due ? ' · due now' : ''}
          </small>
        ) : null}
      </div>
    </details>
  );
}

// ---------- steps ----------
function Steps({ plan, lotMethods, busy, onDone, onRemove }) {
  const [sure, setSure] = useState(null);
  const steps = sortSteps(plan.steps);
  const nextId = plan.next_step?.id;
  const row = (s) => (
    <StepRow key={s.id} step={s} lotMethods={lotMethods} next={s.id === nextId}>
      {canMarkDone(plan, s) ? (
        <button className="btn sm ghost" type="button" disabled={Boolean(busy)} onClick={() => onDone(s, false)} aria-label={`Mark done: ${s.text}`} data-testid="step-done">
          {busy === `done-${s.id}` ? 'Saving…' : 'Done'}
        </button>
      ) : null}
      {canUndo(plan, s) ? (
        <button className="btn sm ghost" type="button" disabled={Boolean(busy)} onClick={() => onDone(s, true)} aria-label={`Undo done: ${s.text}`} data-testid="step-undo">
          Undo
        </button>
      ) : null}
      {s.status !== 'done' ? (
        <button
          className={`btn sm ghost sp-remove${sure === s.id ? ' armed' : ''}`}
          type="button"
          disabled={Boolean(busy)}
          onClick={() => (sure === s.id ? onRemove(s) : setSure(s.id))}
          aria-label={sure === s.id ? `Yes, remove: ${s.text}` : `Remove: ${s.text}`}
          data-testid="step-remove"
        >
          {busy === `remove-${s.id}` ? 'Removing…' : sure === s.id ? 'Remove?' : <Icon name="x" />}
        </button>
      ) : null}
    </StepRow>
  );
  return (
    <div className="sp-row" data-testid="plan-steps" data-count={steps.length}>
      <div className="sp-row-head">
        <span className="kicker">Steps</span>
        <small className="sp-line">{steps.length ? `${steps.length} on this plan` : 'None yet'}</small>
      </div>
      {steps.length ? (
        <>
          <ul className="sp-steps">{steps.slice(0, SHOW).map(row)}</ul>
          {steps.length > SHOW ? (
            <details className="job-more">
              <summary>{steps.length - SHOW} more</summary>
              <ul className="sp-steps">{steps.slice(SHOW).map(row)}</ul>
            </details>
          ) : null}
        </>
      ) : (
        <p className="empty-hint">Add a step for anything dated: a sale window, a deposit, a review.</p>
      )}
    </div>
  );
}

// ---------- card ----------
export function PlanCard({ card, meta, focus, i, onChanged }) {
  const { symbol, plan, fact } = card;
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const { openConsole } = useConsole();
  const box = useRef(null);
  useEffect(() => {
    if (focus) box.current?.scrollIntoView({ block: 'start' });
  }, [focus]);

  const act = async (key, call, text) => {
    setBusy(key);
    setErr(null);
    setMsg(null);
    try {
      const r = await call();
      setMsg(typeof text === 'function' ? text(r) : text);
      onChanged();
    } catch (x) {
      setErr(refusal(x));
    } finally {
      setBusy(null);
    }
  };
  const approve = () => act('approve', () => postJson(`${base(symbol)}/approve`, {}), (r) => `${symbol} plan v${r?.plan?.version ?? plan.version} is approved and in force.`);
  const discard = () => act('discard', () => postJson(`${base(symbol)}/discard`, {}), 'Draft discarded.');
  const done = (s, undo) => act(`done-${s.id}`, () => postJson(`${base(symbol)}/steps/${encodeURIComponent(s.id)}/done`, undo ? { undo: true } : {}), undo ? 'Marked not done.' : 'Marked done.');
  const remove = (s) => {
    const ok = approvesOnSave(plan);
    return act(`remove-${s.id}`, () => postJson(base(symbol), ok ? { plan: withoutStep(plan, s.id), approve: true } : { plan: withoutStep(plan, s.id) }, { method: 'PUT' }), (r) => `Step removed. ${savedText(r, symbol, ok)}`);
  };
  const saved = (text) => {
    setMsg(text);
    setErr(null);
    setOpen(null);
    onChanged();
  };

  return (
    <article className="card c6 sp-card" style={{ '--i': i }} ref={box} data-testid="plan-card" data-plan={symbol} data-status={plan.status}>
      <div className="card-head">
        <span className="sp-name">
          <button type="button" className="sym sym-btn" data-sym={symbol}>
            {symbol}
          </button>
          {fact?.name ? <small className="muted">{fact.name}</small> : null}
        </span>
        <span className="acts">
          <RoleChip plan={plan} />
          <VersionChip plan={plan} />
        </span>
      </div>
      {plan.status === 'draft' ? <DraftBar plan={plan} busy={busy} onApprove={approve} onDiscard={discard} /> : null}
      <PlanBlock symbol={symbol} plan={plan} fact={fact} />
      <Steps plan={plan} lotMethods={meta?.lot_methods} busy={busy} onDone={done} onRemove={remove} />
      <Thesis plan={plan} />
      {(plan.warnings || []).map((w) => (
        <p className="note sp-warn" key={w} data-testid="plan-warning">
          <Icon name="info" />
          <span>{w}</span>
        </p>
      ))}
      {msg ? (
        <p className="job-note done" role="status" data-testid="plan-msg">
          {msg}
        </p>
      ) : null}
      {err ? (
        <p className="job-note refused" role="alert" data-testid="plan-act-err">
          {err}
        </p>
      ) : null}
      {open === 'step' ? <StepForm symbol={symbol} plan={plan} fact={fact} meta={meta} onDone={saved} onCancel={() => setOpen(null)} /> : null}
      {open === 'plan' ? <PlanForm symbol={symbol} plan={plan} fact={fact} onDone={saved} onCancel={() => setOpen(null)} /> : null}
      {!open ? (
        <span className="sp-acts sp-foot">
          <button className="btn sm" type="button" onClick={() => setOpen('step')} data-testid="plan-add-step">
            <Icon name="plus" />
            Add step
          </button>
          <button className="btn sm ghost" type="button" onClick={() => setOpen('plan')} data-testid="plan-edit">
            Edit plan
          </button>
          <button className="btn sm ghost" type="button" onClick={() => openConsole({ desk: 'plans', symbol, question: `Refresh the ${symbol} plan` })} data-testid="plan-ask">
            <Icon name="telescope" />
            Ask the Plan desk
          </button>
        </span>
      ) : null}
    </article>
  );
}

// ---------- holdings without a plan ----------
export function BareCard({ rows, i, onChanged }) {
  const [open, setOpen] = useState(null);
  const [msg, setMsg] = useState(null);
  const { openConsole } = useConsole();
  if (!rows.length) return null;
  return (
    <div className="card c12 sp-bare" style={{ '--i': i }} data-testid="plans-bare" data-count={rows.length}>
      <div className="card-head">
        <span className="tag sky">No plan yet</span>
        <span className="acts">
          <span className="chip">{rows.length === 1 ? '1 holding' : `${rows.length} holdings`}</span>
        </span>
      </div>
      <About label="How plans work" testid="plans-about">
        <p>Write one yourself, or ask the Plan desk for a draft. A draft does nothing until you approve it.</p>
      </About>
      {msg ? (
        <p className="job-note done" role="status" data-testid="plan-msg">
          {msg}
        </p>
      ) : null}
      <ul className="sp-bare-list">
        {rows.map(({ symbol, fact }) => (
          <li key={symbol} data-bare={symbol}>
            <span className="sp-bare-top">
              <span className="sp-name">
                <button type="button" className="sym sym-btn" data-sym={symbol}>
                  {symbol}
                </button>
                <small className="muted">{[fact.name, fact.numbers?.weight_pct != null ? `${fact.numbers.weight_pct.toFixed(1)}% of the portfolio` : null].filter(Boolean).join(' · ')}</small>
              </span>
              {open !== symbol ? (
                <span className="sp-acts">
                  <button className="btn sm" type="button" onClick={() => setOpen(symbol)} data-testid="bare-write">
                    <Icon name="plus" />
                    Write a plan
                  </button>
                  <button className="btn sm ghost" type="button" onClick={() => openConsole({ desk: 'plans', symbol, question: `Draft a plan for ${symbol}` })} data-testid="bare-ask">
                    <Icon name="telescope" />
                    Ask the Plan desk
                  </button>
                </span>
              ) : null}
            </span>
            {open === symbol ? (
              <>
                <PlanBlock symbol={symbol} plan={null} fact={fact} />
                <PlanForm
                  symbol={symbol}
                  plan={null}
                  fact={fact}
                  onDone={(text) => {
                    setMsg(text);
                    setOpen(null);
                    onChanged();
                  }}
                  onCancel={() => setOpen(null)}
                />
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

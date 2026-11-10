import { Icon } from '../components/Icon.jsx';
import { bandWord, roleOf, ruler, rulerKey, rulerLabel, stepFacts, stepStamp, stepStatus, stepWhen, versionChip, weightLine, weightMeter, whereWord } from '../lib/stockPlans.js';

// ---------- chips ----------
export function RoleChip({ plan }) {
  if (!plan) return null;
  const role = roleOf(plan.role);
  return (
    <span className={`chip ${role.tone}`} title={role.hint} data-testid="plan-role">
      {role.t}
    </span>
  );
}

export function VersionChip({ plan }) {
  const v = versionChip(plan);
  if (!v) return null;
  return (
    <span className={`chip ${v.tone}`} data-testid="plan-version">
      {v.t}
    </span>
  );
}

// ---------- weight against its band ----------
export function WeightMeter({ symbol, plan, fact }) {
  const m = weightMeter(plan, fact);
  if (!m) return null;
  const status = plan?.band_status || fact?.band?.status;
  const word = m.band ? bandWord(status) : null;
  const line = weightLine(plan, fact);
  return (
    <div className="sp-row" data-testid="plan-weight" data-band={m.band ? status || 'none' : 'none'}>
      <div className="sp-row-head">
        <span className="kicker">Weight</span>
        <small className="sp-line">{line}</small>
        {word ? <span className={`chip ${word.tone}`}>{word.t}</span> : null}
      </div>
      <span className="cv-meter" role="img" aria-label={`${symbol}: ${line}`}>
        <span className="cv-track">
          {m.band ? <i className="cv-band" style={{ left: `${m.from}%`, width: `${Math.max(1, m.to - m.from)}%` }} /> : null}
          {m.mark != null ? <i className={`cv-mark ${m.band ? status || '' : ''}`} style={{ left: `${m.mark}%` }} /> : null}
        </span>
        <span className="cv-scale" aria-hidden="true">
          <small>0%</small>
          <small>{m.max}%</small>
        </span>
      </span>
    </div>
  );
}

// ---------- price ruler with add and trim zones ----------
export function PriceRuler({ symbol, plan, fact }) {
  const r = ruler(plan, fact);
  if (!r) {
    return (
      <div className="sp-row" data-testid="plan-ruler" data-where="none">
        <div className="sp-row-head">
          <span className="kicker">Price</span>
          <small className="sp-line">No price for {symbol} yet. It fills in after tonight’s numbers.</small>
        </div>
      </div>
    );
  }
  const where = whereWord(r);
  return (
    <div className="sp-row" data-testid="plan-ruler" data-where={r.where}>
      <div className="sp-row-head">
        <span className="kicker">Price</span>
        <small className="sp-line">{r.add || r.trim ? (r.suggested ? 'Zones suggested from its monthly swing' : 'Add and trim zones from the plan') : 'No add or trim zone set'}</small>
        {where ? <span className={`chip ${where.tone}`}>{where.t}</span> : null}
      </div>
      <div className="sp-ruler" role="img" aria-label={rulerLabel(symbol, r)}>
        <div className="sp-track">
          {r.low52 && r.high52 ? <i className="sp-range" style={{ left: `${r.low52.left}%`, width: `${Math.max(1, r.high52.left - r.low52.left)}%` }} /> : null}
          {r.add ? <i className={`sp-zone add${r.suggested ? ' hint' : ''}`} style={{ left: `${r.add.left}%`, width: `${r.add.width}%` }} /> : null}
          {r.trim ? <i className={`sp-zone trim${r.suggested ? ' hint' : ''}`} style={{ left: `${r.trim.left}%`, width: `${r.trim.width}%` }} /> : null}
          <i className="sp-price" style={{ left: `${r.price.left}%` }} />
        </div>
      </div>
      <ul className="sp-key">
        {rulerKey(r).map((k) => (
          <li key={k.id} data-key={k.id}>
            <i className={`sp-dot ${k.id}`} aria-hidden="true" />
            <small>{k.label}</small>
            <b>{k.value}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------- one step ----------
export function StepStamp({ step }) {
  const stamp = stepStamp(step);
  if (!stamp) {
    return (
      <span className="sp-nodate" aria-hidden="true">
        <Icon name={step.status === 'standing' ? 'pin' : 'clock'} />
      </span>
    );
  }
  return (
    <span className="disc-stamp" aria-hidden="true">
      <b>{stamp.day}</b>
      <small>{stamp.mon}</small>
    </span>
  );
}

export function StepRow({ step, lotMethods, next = false, children }) {
  const st = stepStatus(step);
  const facts = stepFacts(step, lotMethods);
  return (
    <li className={`sp-step${next ? ' next' : ''}`} data-step={step.id} data-status={step.status} data-by={step.by}>
      <StepStamp step={step} />
      <span className="sp-step-main">
        <b>{step.text}</b>
        <small>{[stepWhen(step), ...facts].join(' · ')}</small>
        {step.note ? <small className="sp-step-note">{step.note}</small> : null}
      </span>
      <span className="sp-step-side">
        <span className={`chip ${st.tone}`}>{st.t}</span>
        {children}
      </span>
    </li>
  );
}

// ---------- weight, price and next step together ----------
export function PlanBlock({ symbol, plan, fact, lotMethods, showNext = false }) {
  return (
    <div className="sp-block" data-testid="plan-block">
      <WeightMeter symbol={symbol} plan={plan} fact={fact} />
      <PriceRuler symbol={symbol} plan={plan} fact={fact} />
      {showNext && plan ? (
        <div className="sp-row" data-testid="plan-next">
          <div className="sp-row-head">
            <span className="kicker">Next step</span>
          </div>
          {plan.next_step ? (
            <ul className="sp-steps">
              <StepRow step={plan.next_step} lotMethods={lotMethods} next />
            </ul>
          ) : (
            <p className="empty-hint">Nothing queued on this plan.</p>
          )}
        </div>
      ) : null}
    </div>
  );
}

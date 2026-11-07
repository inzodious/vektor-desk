import { Icon } from '../components/Icon.jsx';
import { DESK_ICO } from '../components/icons.js';
import { Conf, Lights } from './Lights.jsx';
import { DESK_KEY, FUNDING, expiresLabel, oneLine, kindName, lampsOf, needsReason, originName, preflightMetric } from '../lib/decisions.js';
import { usd } from '../lib/format.js';

export function ProposalCard({ d, on = false, onPick, actions, busy }) {
  const lamps = lampsOf(d);
  const key = DESK_KEY[d.origin] || 'plan';
  const reason = needsReason(d);
  const cost = d.funding === 'margin' ? preflightMetric(d, 'margin.cost_month')?.after : null;
  const pick = () => onPick?.(d);
  return (
    <div
      className={`prop${on ? ' on' : ''}`}
      data-prop={d.id}
      role="button"
      tabIndex={0}
      aria-pressed={onPick ? on : undefined}
      aria-label={`${d.title}, ${originName(d.origin)}`}
      onClick={pick}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          pick();
        }
      }}
    >
      <span className={`desk-ico ${key}`}>
        <Icon name={DESK_ICO[key] || 'compass'} />
      </span>
      <span style={{ minWidth: 0 }}>
        <span className="kicker" style={{ fontSize: 10 }}>
          {originName(d.origin)} · {kindName(d.kind)}
        </span>
        <b>{d.title}</b>
        {d.thesis ? <span className="why">{oneLine(d.thesis)}</span> : null}
        <span className="meta">
          <Lights lamps={lamps} withText />
          {d.funding ? <span className={`chip${d.funding === 'margin' ? ' act' : ''}`}>{FUNDING[d.funding] || d.funding}</span> : null}
          {d.funding === 'margin' ? <span className="chip watch">{cost != null ? `About ${usd(cost)} a month in interest` : 'Interest not set'}</span> : null}
          {d.skeptic?.verdict === 'flag' ? <span className="chip lilac">Skeptic: flag</span> : null}
          {d.status === 'snoozed' ? <span className="chip">Back from snooze</span> : null}
          {d.expires_at ? <span className="chip">{expiresLabel(d.expires_at)}</span> : null}
        </span>
      </span>
      <span className="prop-side">
        <Conf value={d.confidence} />
        {actions ? (
          <span className="prop-acts" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()} role="group" aria-label={`Actions for ${d.title}`}>
            {reason ? (
              <a className="btn sm" href={`/decisions?d=${d.id}`} onClick={(e) => { e.preventDefault(); actions.review(d); }}>
                Review
              </a>
            ) : (
              <button className="btn sm" type="button" disabled={busy} onClick={() => actions.approve(d)}>
                Approve
              </button>
            )}
            <button className="icon-btn sm" type="button" disabled={busy} title="Snooze a day" aria-label={`Snooze ${d.title} a day`} onClick={() => actions.snooze(d)}>
              <Icon name="snooze" />
            </button>
            <button className="icon-btn sm" type="button" disabled={busy} title="Dismiss" aria-label={`Dismiss ${d.title}`} onClick={() => actions.dismiss(d)}>
              <Icon name="x" />
            </button>
          </span>
        ) : null}
      </span>
    </div>
  );
}

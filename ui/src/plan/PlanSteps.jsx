import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { useApi } from '../lib/api.js';
import { bridgeSteps } from '../lib/stockPlans.js';

const DAYS = 14;

export function PlanSteps({ i }) {
  const api = useApi(`/api/decisions/plan-steps?days=${DAYS}`);
  const { rows, noBuy, count } = bridgeSteps(api.data);
  if (!api.data || (!count && !noBuy.length)) return null;
  return (
    <div className="card c12 sp-bridge" style={{ '--i': i }} data-testid="plan-steps-card" data-count={count}>
      <div className="card-head">
        <span className="tag lilac">Plan steps</span>
        <span className="acts">
          <span className="chip">{count ? `${count} in the next ${DAYS} days` : 'Nothing due this week'}</span>
          <Link className="link" to="/plan/stocks">
            Stock plans
          </Link>
        </span>
      </div>
      {count ? (
        <ul className="sp-steps sp-bridge-list">
          {rows.map((r) => (
            <li className={`sp-step${r.open ? ' next' : ''}`} key={r.key} data-step={r.id}>
              {r.stamp ? (
                <span className="disc-stamp" aria-hidden="true">
                  <b>{r.stamp.day}</b>
                  <small>{r.stamp.mon}</small>
                </span>
              ) : (
                <span className="sp-nodate" aria-hidden="true">
                  <Icon name="clock" />
                </span>
              )}
              <span className="sp-step-main">
                <b>
                  {r.text}{' '}
                  <button type="button" className="sym sym-btn" data-sym={r.symbol}>
                    {r.symbol}
                  </button>
                </b>
                <small>{r.when}</small>
                {r.note ? <small className="sp-step-note">{r.note}</small> : null}
              </span>
              <span className="sp-step-side">
                <span className={`chip ${r.status.tone}`}>{r.status.t}</span>
                <Link className="btn sm ghost" to={`/plan/stocks?symbol=${encodeURIComponent(r.symbol)}`}>
                  Open
                </Link>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {noBuy.map((n) => (
        <p className="note sp-warn" key={n.symbol} data-testid="no-buy" data-symbol={n.symbol}>
          <Icon name="shield" />
          <span>
            <b>{n.text}.</b> {n.reason ? `${n.reason}.` : ''} Buying it in any account inside the window would void the loss.
          </span>
        </p>
      ))}
    </div>
  );
}

import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { px } from '../lib/format.js';
import { headLine, listWord, reasonText, valuationText, verdictWord } from '../lib/discounts.js';
import { signedPct } from '../lib/strategy.js';

const SHOW = 4;

function Row({ r }) {
  const list = listWord(r.list);
  const v = verdictWord(r.case);
  const val = valuationText(r.valuation);
  return (
    <li className="disc-row" data-disc={r.symbol} data-reason={r.reason} data-verdict={r.case?.verdict || 'pending'}>
      <span className="disc-stamp" aria-hidden="true">
        <b>{dayLabel(r.as_of).split(' ')[1]}</b>
        <small>{dayLabel(r.as_of).split(' ')[0]}</small>
      </span>
      <span className="disc-main">
        <span className="disc-top">
          <button type="button" className="sym sym-btn" data-sym={r.symbol}>
            {r.symbol}
          </button>
          {r.name ? <small className="disc-name">{r.name}</small> : null}
          <span className={`chip ${list.tone}`}>{list.t}</span>
        </span>
        <small className="disc-why">{reasonText(r)}</small>
        {val ? <small className="disc-val">{val}</small> : null}
        {r.case ? (
          <details className="disc-case">
            <summary>{r.case.case}</summary>
            {r.case.risks ? (
              <p>
                <b>Risks:</b> {r.case.risks}
              </p>
            ) : null}
            <p className="muted">
              {r.case.confidence != null ? `${Math.round(r.case.confidence * 100)}% sure` : ''}
              {r.case.horizon_days ? ` · over ${r.case.horizon_days} days` : ''}
              {r.case.written_at ? ` · written ${dayLabel(r.case.written_at.slice(0, 10))}` : ''}
            </p>
          </details>
        ) : (
          <small className="disc-wait">Research is reading this one.</small>
        )}
      </span>
      <span className="disc-side">
        <b className="num">${px(r.price)}</b>
        <small className="dn">{signedPct(r.drop_from_high_pct)} from high</small>
        {v ? (
          <span className={`chip ${v.tone}`} data-testid="disc-verdict">
            {v.t}
          </span>
        ) : (
          <span className="chip">Reading</span>
        )}
      </span>
    </li>
  );
}

export function Discounts({ i = 7 }) {
  const api = useApi('/api/engine/discounts');
  const d = api.data;
  const rows = d?.rows || [];
  if (api.error?.status === 404) return null;
  const line = headLine(d);
  return (
    <div className="card c12 disc" style={{ '--i': i }} data-testid="discounts" data-count={rows.length}>
      <div className="card-head">
        <span className="tag coral">Discount days</span>
        <span className="acts">{d?.as_of ? <span className="chip">{`Scan ${dayLabel(d.as_of)}${d.scanned ? ` · ${d.scanned} names` : ''}`}</span> : null}</span>
      </div>
      {api.loading && !d ? (
        <p className="empty-hint">Checking the after-close scan…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">The scan didn’t load. It comes back with the desk API.</p>
      ) : rows.length ? (
        <>
          <p className="disc-lede" data-testid="disc-lede">
            <b>{line}.</b> <span className="muted">Research writes a case for each; nothing buys on its own.</span>
          </p>
          <ul className="disc-rows">
            {rows.slice(0, SHOW).map((r) => (
              <Row key={r.signal_id} r={r} />
            ))}
          </ul>
          {rows.length > SHOW ? (
            <details className="job-more">
              <summary>{rows.length - SHOW} more from the last 10 days</summary>
              <ul className="disc-rows">
                {rows.slice(SHOW).map((r) => (
                  <Row key={r.signal_id} r={r} />
                ))}
              </ul>
            </details>
          ) : null}
        </>
      ) : (
        <p className="empty-hint" data-testid="disc-empty">
          {d?.note || 'No discounts in the last 10 days.'} {d?.rule ? <span className="muted">The scan looks for {d.rule.replace(/^After the close: /, '').replace(/^./, (c) => c.toLowerCase())}.</span> : null}
        </p>
      )}
    </div>
  );
}

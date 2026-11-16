import { useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { Panel } from '../components/Panel.jsx';
import { postJson } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { etTime, pct, usd } from '../lib/format.js';
import { BUSY, bigMoves, chipRows, confidenceWords, moveChip, moveHead, quietMoves } from '../lib/moves.js';
import { isLink } from '../lib/research.js';


const tone = (v) => (v == null ? '' : v >= 0 ? 'up' : 'dn');

// ---------- chips on the Bridge ----------
export function MoverChips({ data, today, onOpen }) {
  const rows = chipRows(data);
  if (!rows.length) return null;
  const kicker = data.day && data.day !== today ? `Movers ${dayLabel(data.day)}` : 'Movers today';
  return (
    <div className="movers" data-testid="movers">
      <span className="kicker">{kicker}</span>
      {rows.map((r) => {
        const big = r.label === 'due';
        const c = big ? moveChip(r, data.ask) : null;
        return (
          <button type="button" className="chip chip-btn" key={r.symbol} data-mover={r.symbol} data-sym={big ? undefined : r.symbol} data-move={r.status} onClick={big ? () => onOpen(r.symbol) : undefined}>
            {r.symbol} <span className={tone(r.pct)}>{pct(r.pct / 100, 1, true)}</span>
            {c ? <span className={`chip mv-badge ${c.tone}`}>{c.t}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

// ---------- one big move ----------
function Detail({ r }) {
  const d = r.detail || {};
  const when = r.written_at ? `${etTime(new Date(r.written_at))} ET` : null;
  return (
    <div className="mv-detail" data-testid="move-detail">
      <p className="mv-headline">
        <b>{d.headline}</b>
      </p>
      <p>{d.why}</p>
      <div className="mv-cases">
        <div>
          <small className="kicker">Case it’s overdone</small>
          <p>{d.overdone_case}</p>
        </div>
        <div>
          <small className="kicker">Case it’s real</small>
          <p>{d.real_case}</p>
        </div>
      </div>
      {d.watch ? (
        <p>
          <b>Watch:</b> {d.watch}
        </p>
      ) : null}
      {d.plan_note ? (
        <p>
          <b>Your plan:</b> {d.plan_note}
        </p>
      ) : null}
      {d.sources?.length ? (
        <ul className="mv-sources">
          {d.sources.map((s) => (
            <li key={s.url}>
              {isLink(s) ? (
                <a href={s.url} target="_blank" rel="noreferrer noopener">
                  {s.title || s.url}
                </a>
              ) : (
                s.title
              )}
              {s.date ? <small className="muted"> · {s.date}</small> : null}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="muted mv-foot">
        {[confidenceWords(d.confidence), usd(r.change_usd, { sign: true }) + ' on your shares', when ? `written ${when}${r.after_close ? ', after the close' : ', before the close'}` : null]
          .filter(Boolean)
          .join(' · ')}
      </p>
    </div>
  );
}

function BigMove({ r, ask, open, next }) {
  const c = moveChip(r, ask);
  const waitWords = r.status === 'failed' ? `Didn’t finish: ${r.note || 'the research call failed'}.` : r.status === 'capped' ? 'Three names a day get researched; this one missed the cut.' : r.status === 'running' ? 'The research desk is reading the news now.' : next ? `Researched after the close, ${etTime(new Date(next))} ET, or press Explain now.` : 'Waiting for the research desk.';
  return (
    <details className="mv-row" data-move-row={r.symbol} data-status={r.status} open={open || undefined}>
      <summary>
        <span className="sym">{r.symbol}</span>
        <span className={`num ${tone(r.pct)}`}>{pct(r.pct / 100, 1, true)}</span>
        <span className={`chip ${c.tone}`}>{c.t}</span>
      </summary>
      {r.detail ? <Detail r={r} /> : <p className="muted mv-wait">{waitWords}</p>}
    </details>
  );
}

// ---------- the drawer ----------
export function WhyMovedDrawer({ open, onClose, api, focus }) {
  const d = api.data;
  const [asking, setAsking] = useState(false);
  const [err, setErr] = useState(null);
  const big = bigMoves(d);
  const quiet = quietMoves(d);
  const market = d?.market?.pct;
  const sub = d?.day ? `${dayLabel(d.day)}${d.trading ? ', so far' : ''} · S&P 500 ${market == null ? 'not quoted' : pct(market / 100, 1, true)}` : 'Why your holdings moved, and whether it looks overdone.';

  const ask = async () => {
    setAsking(true);
    setErr(null);
    try {
      await postJson('/api/agents/moves/ask');
      api.reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setAsking(false);
    }
  };

  return (
    <Panel open={open} onClose={onClose} title="Why it moved" sub={sub} crumbs={[{ label: 'Bridge', go: onClose }]}>
      {api.loading && !d ? (
        <p className="empty-hint">Checking today’s moves…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">Today’s moves didn’t load. They come back with the desk API.</p>
      ) : (
        <div className="mv" data-testid="why-moved">
          <p className="mv-lede">
            <b data-testid="move-head">{moveHead(d)}</b>
            {d?.can_ask ? (
              <button className="btn sm" type="button" onClick={ask} disabled={asking} data-testid="explain-now">
                <Icon name="telescope" />
                {asking ? 'Asking…' : 'Explain now'}
              </button>
            ) : BUSY.includes(d?.ask?.status) ? (
              <span className="chip info">Researching</span>
            ) : null}
          </p>
          {d?.blocked ? <p className="empty-hint">The research desk is switched off. {d.blocked}</p> : null}
          {err ? (
            <p className="empty-hint" role="alert">
              {err}
            </p>
          ) : null}
          {big.length ? (
            <div className="mv-rows">
              {big.map((r) => (
                <BigMove key={r.symbol} r={r} ask={d.ask} open={r.symbol === focus || big.length === 1} next={d.next} />
              ))}
            </div>
          ) : null}
          {quiet.length ? (
            <details className="job-more" data-testid="moved-with-market" open={quiet.some((r) => r.symbol === focus) || undefined}>
              <summary>{quiet.length} moved with the market or barely moved</summary>
              <ul className="mv-quiet">
                {quiet.map((r) => (
                  <li key={r.symbol} data-move-row={r.symbol}>
                    <span className="sym">{r.symbol}</span>
                    <span className={`num ${tone(r.pct)}`}>{pct(r.pct / 100, 1, true)}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      )}
    </Panel>
  );
}

import { useState } from 'react';
import { Icon } from '../components/Icon.jsx';
import { ApiDown, ResearchHero } from '../research/parts.jsx';
import { useConsole } from '../research/consoleContext.js';
import { useResearchData } from '../lib/useResearch.js';
import { useMetrics } from '../lib/metrics.js';
import { postJson } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { pct, px, usd } from '../lib/format.js';
import { VERDICT, cleanSymbol } from '../lib/research.js';

function sig(m, id, sym) {
  const r = m.rows.find((x) => x.metric_id === id && x.scope_id === sym);
  return r && r.value != null ? r.value : null;
}

// ---------- add form ----------
function AddSymbol({ onDone }) {
  const [v, setV] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const add = async (e) => {
    e.preventDefault();
    const s = cleanSymbol(v);
    if (!s) {
      setErr('Use a ticker, like NOVA.');
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      await postJson('/api/engine/watchlist', { symbol: s });
      setV('');
      onDone(`Added ${s}. The engine fetches its prices and research on the next run.`);
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="override-row" onSubmit={add} style={{ marginBottom: 10 }}>
      <div className="field" style={{ flex: 1, minWidth: 140 }}>
        <input aria-label="Symbol to watch" placeholder="Add a symbol" value={v} maxLength={10} onChange={(e) => setV(e.target.value.toUpperCase())} />
      </div>
      <button className="btn sm" type="submit" disabled={busy}>
        <Icon name="plus" />
        Watch it
      </button>
      {err ? (
        <p className="act-err" role="alert" style={{ flexBasis: '100%' }}>
          {err}
        </p>
      ) : null}
    </form>
  );
}

// ---------- page ----------
export default function Watchlist() {
  const r = useResearchData();
  const m = useMetrics('sig.*', 'scope=holding');
  const { openConsole } = useConsole();
  const [note, setNote] = useState(null);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const bySym = Object.fromEntries(r.list.map((d) => [d.symbol, d]));
  const rows = r.watchRows;

  const remove = async (s) => {
    setBusy(s);
    setErr(null);
    try {
      await postJson(`/api/engine/watchlist/${encodeURIComponent(s)}`, {}, { method: 'DELETE' });
      setNote(`Stopped watching ${s}.`);
      r.watch.reload();
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(null);
    }
  };

  if (r.watch.loading && !r.watch.data) return <ResearchHero kicker="Watchlist" big={<b>Checking…</b>} />;
  if (r.watch.error && !r.watch.data && r.watch.error.status !== 404) {
    return (
      <>
        <ResearchHero kicker="Watchlist" big={<b>No answer</b>} />
        <ApiDown what="The watchlist will" reload={r.watch.reload} />
      </>
    );
  }

  return (
    <>
      <ResearchHero
        kicker="Watchlist"
        big={
          r.watchServed ? (
            <>
              <b>{rows.length}</b>
              <span className="muted">{rows.length === 1 ? 'symbol' : 'symbols'} watched · researched like holdings</span>
            </>
          ) : (
            <>
              <b>Soon</b>
              <span className="muted">the engine starts serving the watchlist in its next release</span>
            </>
          )
        }
      />
      <section className="grid">
        <div className="card c8 top" data-testid="watchlist">
          <div className="card-head">
            <span className="tag sky">Watchlist</span>
            <span className="chip">Last close, not live</span>
          </div>
          {r.watchServed ? (
            <AddSymbol
              onDone={(t) => {
                setNote(t);
                r.watch.reload();
              }}
            />
          ) : null}
          {note ? (
            <p className="act-note" role="status">
              <Icon name="check" />
              {note}
            </p>
          ) : null}
          {rows.length ? (
            <div className="tscroll">
              <table className="t watch-t">
                <thead>
                  <tr>
                    <th scope="col">Symbol</th>
                    <th scope="col" className="r">
                      Last close
                    </th>
                    <th scope="col" className="r">
                      Day
                    </th>
                    <th scope="col">Dossier</th>
                    <th scope="col">Next earnings</th>
                    <th scope="col" className="r">
                      Insiders, 90 days
                    </th>
                    <th scope="col" aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((w) => {
                    const ch = w.last_close != null && w.prev_close ? w.last_close / w.prev_close - 1 : null;
                    const d = bySym[w.symbol];
                    const v = d?.dossier?.verdict ? VERDICT[d.dossier.verdict] : null;
                    const days = sig(m, 'sig.earnings_days', w.symbol);
                    const ins = sig(m, 'sig.insider_net', w.symbol);
                    return (
                      <tr key={w.symbol} className="still" data-watch={w.symbol}>
                        <td>
                          <button type="button" className="sym sym-btn" data-sym={w.symbol}>
                            <i style={{ '--c': 'var(--s3)' }} />
                            {w.symbol}
                          </button>
                          <small className="muted cell-sub">
                            {w.name || 'No name on file'}
                            {w.added_at ? ` · since ${dayLabel(w.added_at.slice(0, 10))}` : ''}
                          </small>
                        </td>
                        <td className="r num">{w.last_close != null ? `$${px(w.last_close)}` : '—'}</td>
                        <td className={`r num ${ch == null ? '' : ch >= 0 ? 'up' : 'dn'}`}>{ch == null ? '—' : pct(ch, 2, true)}</td>
                        <td>{v ? <span className={`chip ${v.tone}`}>{v.t}</span> : d ? <span className="chip">Written</span> : <button className="link" type="button" onClick={() => openConsole({ desk: 'research', symbol: w.symbol, question: `Deep dive on ${w.symbol}` })}>Ask for one</button>}</td>
                        <td>{days == null ? '—' : days === 0 ? 'Today' : `In ${days} ${days === 1 ? 'day' : 'days'}`}</td>
                        <td className={`r num ${ins == null || ins === 0 ? '' : ins > 0 ? 'up' : 'dn'}`}>{ins == null ? '—' : ins === 0 ? 'None' : usd(ins, { sign: true })}</td>
                        <td className="r">
                          {w.source === 'env' ? (
                            <span className="chip" title="Set by DESK_WATCHLIST on the NAS">
                              Pinned
                            </span>
                          ) : (
                            <button className="btn sm ghost" type="button" disabled={busy === w.symbol} onClick={() => remove(w.symbol)} aria-label={`Stop watching ${w.symbol}`}>
                              <Icon name="x" />
                              Remove
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty-hint">{r.watchServed ? 'Nothing watched yet. Add a symbol above and the desk researches it like a holding.' : 'The watchlist page fills in once the engine serves /api/engine/watchlist.'}</p>
          )}
          {err ? (
            <p className="act-err" role="alert">
              {err}
            </p>
          ) : null}
        </div>
        <div className="stack c4">
          <div className="card">
            <div className="card-head">
              <span className="tag mint">How watching works</span>
            </div>
            <div className="rule">
              <Icon name="eye" />
              <span>
                <b>Researched like a holding</b>
                <small>Filings, earnings and insider trades are fetched for every watched stock.</small>
              </span>
              <span />
            </div>
            <div className="rule">
              <Icon name="flag" />
              <span>
                <b>No buy signal</b>
                <small>Watching is not a plan change. New single stocks still trip the plan rules.</small>
              </span>
              <span />
            </div>
            <div className="rule">
              <Icon name="pin" />
              <span>
                <b>Pinned rows</b>
                <small>Symbols in DESK_WATCHLIST on the NAS stay put and can only be changed there.</small>
              </span>
              <span />
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

import { useMemo } from 'react';
import { Icon } from '../components/Icon.jsx';
import { LineChart } from '../components/LineChart.jsx';
import { useConsole } from './consoleContext.js';
import { useLive } from '../live/context.js';
import { useApi } from '../lib/api.js';
import { useMetrics } from '../lib/metrics.js';
import { dayLabel, parseDay, periodStart } from '../lib/charts.js';
import { etStamp, plural } from '../lib/format.js';
import { SOURCE_WORD, coreFund, eventsOf, fmtBasis, freshness, isLink, isPriceBasis, keyNumbers, rangeGeo, rangeLine, rebase, sourceKind, triggersOf, verdictOf } from '../lib/research.js';

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const SHOW_EVENTS = 6;

export function DateBox({ day }) {
  const d = parseDay(day);
  return (
    <span className="datebox">
      <small>{MON[d.getUTCMonth()]}</small>
      <b>{d.getUTCDate()}</b>
    </span>
  );
}

// ---------- valuation range ----------
export function RangeStrip({ range, nowValue }) {
  const now = range?.now ?? nowValue ?? null;
  const g = rangeGeo({ ...range, now });
  if (!g) return <p className="empty-hint">No valuation range written yet.</p>;
  return (
    <div>
      <span className="kicker">Valuation range · {range.basis}</span>
      <div className="range" role="img" aria-label={`Range ${fmtBasis(range.low, range.basis)} to ${fmtBasis(range.high, range.basis)}. ${rangeLine(range, nowValue)}`}>
        <span className="lab" style={{ left: `${g.left}%` }}>
          {fmtBasis(range.low, range.basis)}
        </span>
        <span className="lab mid" style={{ left: `${g.mid}%` }}>
          fair
        </span>
        <span className="lab" style={{ left: `${g.left + g.width}%` }}>
          {fmtBasis(range.high, range.basis)}
        </span>
        <span className="bar" style={{ left: `${g.left}%`, width: `${g.width}%` }} />
        {g.now != null ? <span className={`now ${g.where}`} style={{ left: `${g.now}%` }} title={`Now ${fmtBasis(now, range.basis)}`} /> : null}
      </div>
      <p className="empty-hint">{rangeLine(range, nowValue)}</p>
    </div>
  );
}

// ---------- price against core ----------
function PriceVsCore({ symbol, core, start }) {
  const a = useApi(`/api/engine/prices?symbol=${encodeURIComponent(symbol)}&start=${start}`);
  const same = !core || core === symbol;
  const b = useApi(same ? null : `/api/engine/prices?symbol=${encodeURIComponent(core)}&start=${start}`);
  const r = useMemo(() => rebase(a.data, same ? null : b.data), [a.data, b.data, same]);
  if (a.loading || (!same && b.loading)) return <p className="empty-hint">Loading prices…</p>;
  if (r.x.length < 2) return <p className="empty-hint">No price history for {symbol} yet. It fills in after the nightly backfill.</p>;
  const series = [{ name: symbol, color: 'var(--s1)', values: r.a }, ...(same ? [] : [{ name: core, color: 'var(--s2)', values: r.b }])];
  return <LineChart label={`${symbol}${same ? '' : ` against ${core}`}, rebased to 100`} height={200} x={r.x} series={series} refs={[{ y: 100, dash: true }]} fmtY={(v) => v.toFixed(0)} fmtTip={(v) => v.toFixed(1)} endLabels />;
}

// ---------- key numbers ----------
function KeyNumbers({ symbol }) {
  const m = useMetrics('*', `scope=holding&scope_id=${encodeURIComponent(symbol)}`);
  const rows = keyNumbers(m.rows, symbol);
  return (
    <div className="card" data-testid="key-numbers">
      <div className="card-head">
        <span className="tag">Key numbers</span>
        <span className="chip">{m.asOf ? `From the engine, ${dayLabel(m.asOf)} close` : 'From the engine'}</span>
      </div>
      {rows.length ? (
        <div className="kv">
          {rows.map((k) => (
            <div key={k.id}>
              <small>{k.t}</small>
              <b>{k.v}</b>
              {k.quality && k.quality !== 'ok' ? <span className="tag lilac q">{k.quality.replace(/_/g, ' ')}</span> : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-hint">{m.loading ? 'Reading the engine…' : `The engine has no numbers for ${symbol} yet.`}</p>
      )}
    </div>
  );
}

// ---------- filings and events ----------
function Events({ symbol, today }) {
  const res = useApi(`/api/engine/research?symbol=${encodeURIComponent(symbol)}`);
  const events = useMemo(() => eventsOf(res.data, today), [res.data, today]);
  const next = events.filter((e) => e.date > today).sort((x, y) => x.date.localeCompare(y.date));
  const past = events.filter((e) => e.date <= today);
  const shown = [...next, ...past].slice(0, SHOW_EVENTS);
  return (
    <div className="card c6" data-testid="events">
      <div className="card-head">
        <span className="tag sky">Filings and events</span>
        <span className="chip">SEC EDGAR · Finnhub</span>
      </div>
      {shown.length ? (
        <div className="rows">
          {shown.map((e) => (
            <div className="row still" key={e.key} data-kind={e.kind}>
              <span className="l">
                <DateBox day={e.date} />
                <span style={{ minWidth: 0 }}>
                  <b>
                    {isLink(e) ? (
                      <a href={e.url} target="_blank" rel="noreferrer noopener">
                        {e.title}
                      </a>
                    ) : (
                      e.title
                    )}
                  </b>
                  <small>{e.detail}</small>
                </span>
              </span>
              {e.date > today ? <span className="chip info">Coming up</span> : <span />}
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-hint">{res.loading ? 'Reading filings…' : 'No filings or events on file. Funds file holdings each quarter, and those show here once fetched.'}</p>
      )}
    </div>
  );
}

// ---------- sources ----------
export function SourceRow({ s, symbol }) {
  const kind = s.kind || sourceKind(s);
  const w = SOURCE_WORD[kind];
  return (
    <div className="src" data-kind={kind}>
      <span className={`chip ${w.tone}`}>{w.t}</span>
      {isLink(s) ? (
        <a href={s.url} target="_blank" rel="noreferrer noopener">
          {s.title || s.url}
        </a>
      ) : (
        <span>{s.title}</span>
      )}
      {symbol ? (
        <button type="button" className="sym sym-btn" data-sym={symbol}>
          <i style={{ '--c': 'var(--s1)' }} />
          {symbol}
        </button>
      ) : null}
      <span className="muted src-date">{s.date ? dayLabel(s.date.slice(0, 10), true) : ''}</span>
    </div>
  );
}

function Sources({ sources }) {
  const primary = sources.filter((s) => sourceKind(s) === 'primary').length;
  return (
    <div className="card c6" data-testid="dossier-sources">
      <div className="card-head">
        <span className="tag lilac">Sources</span>
        <span className="chip">{sources.length ? `${plural(sources.length, 'source')} · ${primary} primary` : 'None cited'}</span>
      </div>
      {sources.length ? sources.map((s) => <SourceRow key={`${s.url}-${s.title}`} s={s} />) : <p className="empty-hint">This dossier cites no sources. Refresh it to get some.</p>}
    </div>
  );
}

// ---------- dossier ----------
export function Dossier({ entry, today }) {
  const { openConsole } = useConsole();
  const live = useLive();
  const plan = useMetrics('plan.target', 'scope=holding');
  const d = entry.dossier || {};
  const sym = entry.symbol;
  const verdict = verdictOf(entry);
  const fresh = freshness(entry.created_at);
  const row = live.symbols.find((s) => s.symbol === sym);
  const nowPrice = isPriceBasis(d.valuation_range?.basis) ? (row?.price ?? null) : null;
  const core = coreFund(plan.rows);
  const triggers = triggersOf(d.what_would_change);
  const start = periodStart('1Y', today);
  const name = live.names?.[sym];

  return (
    <div className="stack" data-testid="dossier" data-symbol={sym}>
      <div className="card">
        <div className="card-head">
          <span style={{ display: 'grid', gap: 2, minWidth: 0 }}>
            <span className="kicker">
              Research desk · {etStamp(entry.created_at) || 'never'} · {plural((d.sources || []).length, 'source')}
            </span>
            <h2 className="dossier-title">
              <button type="button" className="sym sym-btn" data-sym={sym}>
                <i style={{ '--c': 'var(--s1)' }} />
                {sym}
              </button>
              {name ? <span className="muted"> · {name}</span> : null}
            </h2>
          </span>
          <span className="acts">
            {verdict ? <span className={`chip ${verdict.tone}`} data-testid="verdict">{verdict.t}</span> : null}
            <span className={`chip ${fresh.tone}`}>{fresh.t}</span>
            <button className="btn sm" type="button" onClick={() => openConsole({ desk: 'research', symbol: sym, question: `Refresh the ${sym} dossier`, now: true })}>
              <Icon name="play" />
              Refresh now
            </button>
          </span>
        </div>
        <div className="split">
          <div>
            <RangeStrip range={d.valuation_range} nowValue={nowPrice} />
            {d.changes_since_last ? (
              <div className="note" style={{ marginTop: 10 }}>
                <Icon name="swap" />
                <span>
                  <b style={{ color: 'var(--ink)' }}>Since last time.</b> {d.changes_since_last}
                </span>
              </div>
            ) : null}
          </div>
          <div className="bb">
            <div className="bull">
              <b>Thesis</b>
              {d.thesis || 'No thesis written.'}
            </div>
            <div className="bear">
              <b>Bear case</b>
              {d.bear_case || 'No bear case written.'}
            </div>
          </div>
        </div>
      </div>
      <div className="grid inner">
        <div className="card c7">
          <div className="card-head">
            <span className="tag">{core && core !== sym ? `${sym} against ${core}` : `${sym}, 1 year`}</span>
            <span className="chip">{core && core !== sym ? 'Rebased to 100 · core fund' : 'Rebased to 100'}</span>
          </div>
          <PriceVsCore symbol={sym} core={core} start={start} />
        </div>
        <div className="card c5" data-testid="triggers">
          <div className="card-head">
            <span className="tag mustard">What would change the call</span>
          </div>
          {triggers.length ? (
            triggers.map((t) => (
              <div className="rule" key={t}>
                <span style={{ color: 'var(--watch)' }}>
                  <Icon name="flag" />
                </span>
                <span>
                  <b>{t}</b>
                </span>
                <span />
              </div>
            ))
          ) : (
            <p className="empty-hint">No triggers written yet.</p>
          )}
        </div>
      </div>
      <KeyNumbers symbol={sym} />
      <div className="grid inner">
        <Events symbol={sym} today={today} />
        <Sources sources={d.sources || []} />
      </div>
    </div>
  );
}

import { useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { Combo } from '../components/Combo.jsx';
import { Dossier } from '../research/Dossier.jsx';
import { useConsole } from '../research/consoleContext.js';
import { ApiDown, MarketCard, ResearchHero, WatchRow } from '../research/parts.jsx';
import { useResearchData } from '../lib/useResearch.js';
import { useLive } from '../live/context.js';
import { dayLabel } from '../lib/charts.js';
import { plural } from '../lib/format.js';
import { todayEt } from '../lib/tax.js';
import { freshness, verdictOf } from '../lib/research.js';

const SHOW = [
  { v: 'all', t: 'Everything' },
  { v: 'held', t: 'Held' },
  { v: 'other', t: 'Not held' },
];
const WATCH_TOP = 5;

function queuedLine(queued) {
  if (!queued.length) return 'no deep dive queued';
  return `${plural(queued.length, 'deep dive')} queued${queued.some((q) => !q.run_now) ? ' for tonight' : ''}`;
}

// ---------- dossier list ----------
function DossierList({ list, cur, onPick, held }) {
  const [show, setShow] = useState('all');
  const shown = list.filter((d) => show === 'all' || (show === 'held') === held.has(d.symbol));
  return (
    <div className="card" data-testid="dossier-list">
      <div className="card-head">
        <span className="tag lilac">Dossiers</span>
        <span className="acts">{list.length > 1 ? <Combo label="Show" options={SHOW} value={show} onChange={setShow} /> : <span className="chip">Refreshed in rotation</span>}</span>
      </div>
      {shown.length ? (
        <div className="rows">
          {shown.map((d) => {
            const v = verdictOf(d);
            const f = freshness(d.created_at);
            return (
              <button type="button" className={`row dossier-row${d.symbol === cur ? ' on' : ''}`} key={d.symbol} aria-pressed={d.symbol === cur} onClick={() => onPick(d.symbol)}>
                <span className="l">
                  <span className="desk-ico research sm">
                    <Icon name={held.has(d.symbol) ? 'book' : 'eye'} />
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <b>{d.symbol}</b>
                    <small>
                      Updated {dayLabel(d.created_at.slice(0, 10))} · {plural((d.dossier?.sources || []).length, 'source')}
                    </small>
                  </span>
                </span>
                {v ? <span className={`chip ${v.tone}`}>{v.t}</span> : <span className={`chip ${f.tone}`}>{f.tone ? 'Stale' : 'Fresh'}</span>}
              </button>
            );
          })}
        </div>
      ) : (
        <p className="empty-hint">Nothing in this view. Pick Everything to see the rest.</p>
      )}
    </div>
  );
}

// ---------- page ----------
export default function Research() {
  const r = useResearchData();
  const live = useLive();
  const { openConsole } = useConsole();
  const [params, setParams] = useSearchParams();
  const detailRef = useRef(null);
  const today = todayEt();
  const held = useMemo(() => new Set(live.symbols.map((s) => s.symbol)), [live.symbols]);
  const want = (params.get('s') || '').toUpperCase();
  const entry = r.list.find((d) => d.symbol === want) || r.list[0] || null;
  const bySym = Object.fromEntries(r.list.map((d) => [d.symbol, d]));

  const pick = (sym) => {
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        n.set('s', sym);
        return n;
      },
      { replace: true },
    );
    if (window.matchMedia?.('(max-width: 860px)').matches) requestAnimationFrame(() => detailRef.current?.scrollIntoView({ block: 'start' }));
  };

  if (r.dossiers.loading && !r.dossiers.data) return <ResearchHero kicker="Dossiers" big={<b>Checking…</b>} />;
  if (r.dossiers.error && !r.dossiers.data && r.dossiers.error.status !== 404) {
    return (
      <>
        <ResearchHero kicker="Dossiers" big={<b>No answer</b>} />
        <ApiDown what="Dossiers" reload={r.dossiers.reload} />
      </>
    );
  }

  return (
    <>
      <ResearchHero
        kicker="Dossiers"
        big={
          <>
            <b>{r.list.length}</b>
            <span className="muted">
              {r.list.length === 1 ? 'dossier' : 'dossiers'} · {queuedLine(r.queued)}
            </span>
          </>
        }
      />
      <section className="grid">
        <div className="stack c4 keep">
          {r.list.length ? (
            <DossierList list={r.list} cur={entry?.symbol} onPick={pick} held={held} />
          ) : (
            <div className="card">
              <div className="card-head">
                <span className="tag lilac">Dossiers</span>
              </div>
              <p className="empty-hint">No dossiers yet. The research desk writes one per holding in rotation, or ask for a deep dive.</p>
            </div>
          )}
          <div className="card" data-testid="watch-card">
            <div className="card-head">
              <span className="tag sky">Watchlist</span>
              <Link className="link" to="/research/watchlist">
                {r.watchRows.length > WATCH_TOP ? `All ${r.watchRows.length}` : 'Open'}
              </Link>
            </div>
            {r.watchRows.length ? (
              <div className="rows">
                {r.watchRows.slice(0, WATCH_TOP).map((w) => (
                  <WatchRow key={w.symbol} w={w} dossier={bySym[w.symbol]} />
                ))}
              </div>
            ) : (
              <p className="empty-hint">{r.watchServed ? 'Nothing on the watchlist. Add a symbol from the Watchlist tab.' : 'The watchlist shows here once the engine serves it.'}</p>
            )}
          </div>
          <MarketCard />
        </div>
        <div className="c8 keep" ref={detailRef}>
          {entry ? (
            <Dossier key={entry.symbol} entry={entry} today={today} />
          ) : (
            <div className="card">
              <div className="queue-clear">
                <Icon name="book" />
                <span>
                  <b>No dossier open</b>
                  <small>Ask the research desk for a deep dive on any symbol, held or not. It runs tonight unless you press Run now.</small>
                </span>
              </div>
              <button className="btn sm" type="button" style={{ marginTop: 10 }} onClick={() => openConsole({ desk: 'research', question: 'Deep dive on ' })}>
                <Icon name="telescope" />
                Request a deep dive
              </button>
            </div>
          )}
        </div>
      </section>
    </>
  );
}

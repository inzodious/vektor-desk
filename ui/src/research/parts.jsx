import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { useConsole } from './consoleContext.js';
import { useMetrics } from '../lib/metrics.js';
import { dayLabel } from '../lib/charts.js';
import { pct, px } from '../lib/format.js';
import { MACRO, RESEARCH_TABS, VERDICT } from '../lib/research.js';

export function ResearchHero({ kicker, big, extra }) {
  const { openConsole } = useConsole();
  return (
    <Hero
      kicker={`Research · ${kicker}`}
      title="Research"
      art="research"
      big={big}
      foot={
        <>
          <Subtabs label="Research views" tabs={RESEARCH_TABS} />
          {extra}
          <button className="btn sm" type="button" onClick={() => openConsole({ desk: 'research', question: 'Deep dive on ' })}>
            <Icon name="telescope" />
            Request a deep dive
          </button>
        </>
      }
    />
  );
}

export function ApiDown({ what, reload }) {
  return (
    <section className="card" role="alert">
      <div className="card-head">
        <span className="tag coral">The desk API didn&apos;t answer</span>
        <button className="btn sm" type="button" onClick={reload}>
          <Icon name="swap" />
          Retry
        </button>
      </div>
      <p className="muted">{what} come back as soon as it does.</p>
    </section>
  );
}

// ---------- watch rows ----------
export function WatchRow({ w, dossier }) {
  const change = w.last_close != null && w.prev_close ? w.last_close / w.prev_close - 1 : null;
  const v = dossier?.dossier?.verdict ? VERDICT[dossier.dossier.verdict] : null;
  return (
    <div className="row" data-sym={w.symbol} tabIndex={0} data-watch={w.symbol}>
      <span className="l">
        <span className="sym">
          <i style={{ '--c': 'var(--s3)' }} />
          {w.symbol}
        </span>
        <span style={{ minWidth: 0 }}>
          <small>
            {w.name || 'No name on file'}
            {v ? ` · ${v.t}` : ''}
          </small>
        </span>
      </span>
      <span className="v">
        {w.last_close != null ? `$${px(w.last_close)}` : '—'}
        <small className={change == null ? '' : change >= 0 ? 'up' : 'dn'}>{change == null ? (w.last_bar ? dayLabel(w.last_bar) : 'No price yet') : `${pct(change, 2, true)} last close`}</small>
      </span>
    </div>
  );
}

// ---------- market backdrop ----------
export function MarketCard({ span = '' }) {
  const m = useMetrics('macro.*', 'scope=macro');
  const rows = MACRO.map((k) => {
    const r = m.rows.find((x) => x.metric_id === k.id);
    return r && r.value != null ? { ...k, r } : null;
  }).filter(Boolean);
  return (
    <div className={`card ${span}`} data-testid="market">
      <div className="card-head">
        <span className="tag sky">Market backdrop</span>
        <span className="chip">{m.asOf ? `FRED · ${dayLabel(m.asOf)}` : 'FRED'}</span>
      </div>
      {rows.length ? (
        <div className="mini-kpis macro">
          {rows.map((k) => (
            <div key={k.id}>
              <small>{k.t}</small>
              <b>{k.f(k.r.value)}</b>
              {k.hint ? <span className="muted">{k.hint(k.r.value)}</span> : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-hint">{m.loading ? 'Reading rates…' : 'No rates yet. They fill in once the FRED key is set and the engine runs.'}</p>
      )}
    </div>
  );
}

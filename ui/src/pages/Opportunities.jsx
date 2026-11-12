import { Link } from 'react-router-dom';
import { ApiDown, ResearchHero } from '../research/parts.jsx';
import { useApi } from '../lib/api.js';
import { useAsOf, fromDay } from '../lib/asof.js';
import { whenWords } from '../lib/morning.js';
import { earningsLine, entryLine, heldLine, opportunityNotes, sizeLine, stanceOf } from '../lib/opportunities.js';
import { EmptyState } from '../start/EmptyState.jsx';

// ---------- one idea ----------
function Idea({ row, deskDay }) {
  const stance = stanceOf(row);
  const entry = entryLine(row.entry);
  const size = sizeLine(row.size);
  const earnings = earningsLine(row.next_earnings);
  const older = fromDay(row.as_of, deskDay);
  return (
    <article className="card idea" data-idea={row.symbol} data-stance={row.stance}>
      <div className="card-head">
        <span className="idea-name">
          <i className="idea-rank" aria-label={`Rank ${row.rank}`}>
            {row.rank}
          </i>
          <button type="button" className="sym sym-btn" data-sym={row.symbol}>
            <i style={{ '--c': 'var(--s1)' }} />
            {row.symbol}
          </button>
          <span className="muted">{row.name}</span>
        </span>
        <span className="acts">
          <span className={`chip ${stance.tone}`}>{stance.t}</span>
        </span>
      </div>
      <p className="idea-why">{row.why_now}</p>
      {row.facts?.length ? (
        <ul className="idea-facts">
          {row.facts.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      ) : null}
      <dl className="idea-plan">
        {entry ? (
          <div>
            <dt>Entry zone</dt>
            <dd>
              {entry}
              {row.entry.basis ? <small>{row.entry.basis}</small> : null}
            </dd>
          </div>
        ) : null}
        {size ? (
          <div>
            <dt>Size</dt>
            <dd>{size}</dd>
          </div>
        ) : null}
        {row.wrong_if ? (
          <div>
            <dt>Wrong if</dt>
            <dd>{row.wrong_if}</dd>
          </div>
        ) : null}
      </dl>
      <p className="idea-foot muted">
        <span>{heldLine(row)}</span>
        {row.source_label ? <span>{row.source_label}</span> : null}
        {earnings ? <span>{earnings}</span> : null}
        {older ? <span>Numbers {older}</span> : null}
        <Link className="link" to={`/research?s=${encodeURIComponent(row.symbol)}`}>
          Open its research
        </Link>
        {row.decision_id ? (
          <Link className="link" to="/decisions">
            See it in Decisions
          </Link>
        ) : null}
      </p>
    </article>
  );
}

// ---------- page ----------
export default function Opportunities() {
  const api = useApi('/api/opportunities', { every: 300000 });
  const clock = useAsOf();
  const d = api.data;

  if (!d && api.loading) return <ResearchHero kicker="Opportunities" big={<b>Checking…</b>} />;
  if (!d) {
    const missing = api.error?.status === 404;
    return (
      <>
        <ResearchHero kicker="Opportunities" big={<b>{missing ? 'Not yet' : 'No answer'}</b>} />
        {missing ? <EmptyState k="research.opportunities" card icon="bolt" title="No list yet" why="The ranked list of buying opportunities arrives with the next desk update." /> : <ApiDown what="Buying opportunities" reload={api.reload} />}
      </>
    );
  }

  const rows = Array.isArray(d.rows) ? d.rows : [];
  const total = d.counts?.total ?? rows.length;
  const fresh = whenWords(d.freshness?.night_run_at || d.built_at);
  const notes = opportunityNotes(d);
  const passed = Array.isArray(d.passed) ? d.passed : [];

  return (
    <>
      <ResearchHero
        kicker="Opportunities"
        big={
          <>
            <b data-testid="opp-count">{total}</b>
            <span className="muted">{total === 1 ? 'idea' : 'ideas'} · advice only, nothing here places a trade</span>
          </>
        }
      />
      <section className="card opp-top" data-testid="opp-top">
        <div className="card-head">
          <span className="tag mint">Buying opportunities</span>
          <span className="acts">{fresh && rows.length ? <span className="chip">Checked {fresh} ET</span> : null}</span>
        </div>
        <p className="opp-headline">{rows.length ? d.headline : d.note || d.headline}</p>
        {notes.map((n) => (
          <p className="muted opp-note" key={n}>
            {n}
          </p>
        ))}
        {d.method ? <p className="muted opp-note">{d.method}</p> : null}
      </section>
      {rows.length ? (
        <section className="ideas" data-testid="ideas">
          {rows.map((r) => (
            <Idea row={r} deskDay={clock?.day} key={r.symbol} />
          ))}
        </section>
      ) : null}
      {passed.length ? (
        <section className="card" data-testid="opp-passed">
          <div className="card-head">
            <span className="tag">Looked at and passed on</span>
            <span className="chip">{passed.length}</span>
          </div>
          <div className="rows">
            {passed.map((p) => (
              <div className="row still" key={p.symbol}>
                <span className="l">
                  <span style={{ minWidth: 0 }}>
                    <b>
                      {p.symbol} <span className="muted">{p.name}</span>
                    </b>
                    <small className="wrap">{p.reason}</small>
                  </span>
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );
}

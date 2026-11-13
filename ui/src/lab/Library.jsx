import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { benchmarkWords, benchmarksView, excessWords, libraryChip, libraryGroups, libraryLegend, libraryTop, whenWords } from '../lib/morning.js';

const RETEST = 'This result is from an older version of the rule. It is queued to run again.';

function Row({ r }) {
  const chip = libraryChip(r);
  const excess = excessWords(r);
  const bench = benchmarkWords(r.benchmark);
  const tested = r.status === 'tested';
  return (
    <details className="lib-row" data-lib={r.id} data-verdict={tested ? r.verdict || r.status : r.status}>
      <summary>
        <b>{r.title}</b>
        <span className="lib-end">
          {excess ? <small>{excess}</small> : null}
          <span className={`chip ${chip.tone}`}>{chip.t}</span>
        </span>
      </summary>
      <div className="lib-more-text">
        {r.description ? <p className="lib-desc">{r.description}</p> : null}
        <p className="lib-line">{r.line || r.reason || 'No result yet.'}</p>
        {r.outdated ? (
          <p className="lib-retest" data-testid="lib-retest">
            {RETEST}
          </p>
        ) : null}
        <p className="lib-facts">
          {bench ? (
            <span className="lib-bench" data-testid="lib-bench" title={r.benchmark_words || undefined}>
              {bench}
            </span>
          ) : null}
          {r.family ? <span>{r.family}</span> : null}
          {r.research_only ? <span>Research data, not a fund you can buy</span> : null}
          {tested ? (
            <Link className="link" to={`/strategies/${encodeURIComponent(r.id)}`} data-testid="lib-open">
              Open the full test
            </Link>
          ) : null}
        </p>
      </div>
    </details>
  );
}

function Benchmarks({ v }) {
  if (!v) return null;
  return (
    <div className="lib-benchmarks" data-testid="lib-benchmarks">
      <p>
        <b>{v.lead}</b>
        {v.words ? ` ${v.words}` : ''}
      </p>
      {v.rest.length ? (
        <details>
          <summary>The other {v.rest.length === 1 ? 'benchmark' : `${v.rest.length} benchmarks`}</summary>
          <ul>
            {v.rest.map((b) => (
              <li key={b.name}>
                <b>{b.name}</b> <span className="muted">· {b.count}</span>
                {b.words ? <small>{b.words}</small> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function Group({ g, top }) {
  const [all, setAll] = useState(false);
  const shown = all ? g.rows : g.rows.slice(0, top);
  return (
    <div className="lib-group" data-kind={g.key}>
      <div className="lib-head">
        <h3>{g.title}</h3>
        <span className="muted">{g.line}</span>
      </div>
      <div className="rows">
        {shown.map((r) => (
          <Row r={r} key={r.id} />
        ))}
      </div>
      {g.rows.length > top ? (
        <button type="button" className="link lib-more" onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? 'Show fewer' : `Show all ${g.rows.length}`}
        </button>
      ) : null}
    </div>
  );
}

export function Library({ api }) {
  const d = api.data;
  if (!d) {
    if (api.loading || api.error?.status === 404) return null;
    return (
      <section className="card" role="alert" data-testid="library">
        <div className="card-head">
          <span className="tag coral">The overnight table didn&apos;t load</span>
          <button className="btn sm" type="button" onClick={api.reload}>
            <Icon name="swap" />
            Retry
          </button>
        </div>
      </section>
    );
  }
  const groups = libraryGroups(d);
  const fresh = whenWords(d.as_of);
  const c = d.counts || {};
  const legend = libraryLegend(d);
  const top = libraryTop(d);
  const benchmarks = benchmarksView(d);
  return (
    <section className="card library" data-testid="library">
      <div className="card-head">
        <span className="tag mint">{c.tested ? 'Tested overnight' : 'On tonight’s list'}</span>
        <span className="acts">
          <span className="chip">{c.tested ? `${c.tested} of ${c.total} tested${fresh ? ` · ${fresh} ET` : ''}` : `${c.total || 0} waiting for their first run`}</span>
        </span>
      </div>
      {legend || d.note || benchmarks ? (
        <details className="lib-how" data-testid="lib-how">
          <summary>How to read this</summary>
          {legend ? (
            <p className="lib-note" data-testid="lib-legend">
              {legend}
            </p>
          ) : null}
          {d.note ? (
            <p className={legend ? 'muted lib-note' : 'lib-note'} data-testid="lib-note">
              {d.note}
            </p>
          ) : null}
          <Benchmarks v={benchmarks} />
        </details>
      ) : null}
      {groups.length ? groups.map((g) => <Group g={g} top={top} key={g.key} />) : <p className="empty-hint">The library is empty. It fills in with the next desk update.</p>}
    </section>
  );
}

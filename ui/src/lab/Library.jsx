import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { excessWords, libraryChip, libraryGroups, whenWords } from '../lib/morning.js';

const TOP = 5;

function Row({ r }) {
  const chip = libraryChip(r);
  const excess = excessWords(r);
  const body = (
    <>
      <span className="l">
        <span style={{ minWidth: 0 }}>
          <b>{r.title}</b>
          <small>
            {r.family}
            {r.benchmark ? ` · against ${r.benchmark}` : ''}
            {r.research_only ? ' · research data, not a fund you can buy' : ''}
          </small>
          <small className="lib-desc">{r.description}</small>
          <small className="lib-line">{r.line || r.reason || 'No result yet.'}</small>
        </span>
      </span>
      <span className="lib-end">
        <span className={`chip ${chip.tone}`}>{chip.t}</span>
        {r.outdated ? (
          <span className="chip lilac" data-testid="lib-retest" title="This result is from an older version of the rule. It is queued to run again.">
            Retest pending
          </span>
        ) : null}
        {excess ? <small>{excess}</small> : null}
      </span>
    </>
  );
  return r.status === 'tested' ? (
    <Link className="row lib-row" to={`/strategies/${encodeURIComponent(r.id)}`} data-lib={r.id} data-verdict={r.verdict || r.status}>
      {body}
    </Link>
  ) : (
    <div className="row still lib-row" data-lib={r.id} data-verdict={r.status}>
      {body}
    </div>
  );
}

function Group({ g }) {
  const [all, setAll] = useState(false);
  const shown = all ? g.rows : g.rows.slice(0, TOP);
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
      {g.rows.length > TOP ? (
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
  return (
    <section className="card library" data-testid="library">
      <div className="card-head">
        <span className="tag mint">{c.tested ? 'Tested overnight' : 'On tonight’s list'}</span>
        <span className="acts">
          <span className="chip">{c.tested ? `${c.tested} of ${c.total} tested${fresh ? ` · ${fresh} ET` : ''}` : `${c.total || 0} waiting for their first run`}</span>
        </span>
      </div>
      {d.note ? <p className="muted lib-note">{d.note}</p> : null}
      {groups.length ? groups.map((g) => <Group g={g} key={g.key} />) : <p className="empty-hint">The library is empty. It fills in with the next desk update.</p>}
    </section>
  );
}

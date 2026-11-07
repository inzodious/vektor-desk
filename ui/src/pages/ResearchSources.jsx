import { useMemo, useState } from 'react';
import { Combo } from '../components/Combo.jsx';
import { SourceRow } from '../research/Dossier.jsx';
import { ApiDown, ResearchHero } from '../research/parts.jsx';
import { useResearchData } from '../lib/useResearch.js';
import { plural } from '../lib/format.js';
import { SOURCE_WORD, allSources } from '../lib/research.js';

const KINDS = [{ v: 'all', t: 'Any kind' }, ...Object.entries(SOURCE_WORD).map(([v, w]) => ({ v, t: w.t }))];

const GRADES = [
  ['primary', 'SEC filings, FRED series, the fund issuer and the engine itself. Claims rest on these first.'],
  ['web', 'Everything else the research desk read, such as trade press. Treat as colour, never the only reason.'],
  ['note', 'Your own notes. They count as sources so the desk has to square its call with them.'],
];

export default function ResearchSources() {
  const r = useResearchData();
  const [kind, setKind] = useState('all');
  const [sym, setSym] = useState('all');
  const all = useMemo(() => allSources(r.list), [r.list]);
  const symbols = useMemo(() => [{ v: 'all', t: 'Every dossier' }, ...[...new Set(all.map((s) => s.symbol))].sort().map((s) => ({ v: s, t: s }))], [all]);
  const shown = all.filter((s) => (kind === 'all' || s.kind === kind) && (sym === 'all' || s.symbol === sym));
  const n = (k) => all.filter((s) => s.kind === k).length;

  if (r.dossiers.loading && !r.dossiers.data) return <ResearchHero kicker="Sources" big={<b>Checking…</b>} />;
  if (r.dossiers.error && !r.dossiers.data && r.dossiers.error.status !== 404) {
    return (
      <>
        <ResearchHero kicker="Sources" big={<b>No answer</b>} />
        <ApiDown what="Sources" reload={r.dossiers.reload} />
      </>
    );
  }

  return (
    <>
      <ResearchHero
        kicker="Sources"
        big={
          <>
            <b>{all.length}</b>
            <span className="muted">
              {all.length === 1 ? 'source' : 'sources'} across {plural(r.list.length, 'dossier')} · {n('primary')} primary
            </span>
          </>
        }
      />
      <section className="grid">
        <div className="card c8 top" data-testid="sources">
          <div className="card-head">
            <span className="tag lilac">Every cited source</span>
            <span className="acts">
              <Combo label="Kind" options={KINDS} value={kind} onChange={setKind} />
              {symbols.length > 2 ? <Combo label="Dossier" options={symbols} value={sym} onChange={setSym} /> : null}
            </span>
          </div>
          {shown.length ? (
            shown.map((s) => <SourceRow key={`${s.symbol}-${s.url}-${s.title}`} s={s} symbol={s.symbol} />)
          ) : (
            <p className="empty-hint">{all.length ? 'Nothing matches. Widen the filters.' : 'No sources yet. They arrive with the first dossier.'}</p>
          )}
        </div>
        <div className="stack c4">
          <div className="card" data-testid="source-mix">
            <div className="card-head">
              <span className="tag">Source mix</span>
            </div>
            <div className="mini-kpis">
              {Object.entries(SOURCE_WORD).map(([k, w]) => (
                <div key={k}>
                  <small>{w.t}</small>
                  <b>{n(k)}</b>
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="card-head">
              <span className="tag mint">How sources are graded</span>
            </div>
            {GRADES.map(([k, t]) => (
              <div className="rule" key={k}>
                <span className={`chip ${SOURCE_WORD[k].tone}`}>{SOURCE_WORD[k].t}</span>
                <span>
                  <small>{t}</small>
                </span>
                <span />
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}

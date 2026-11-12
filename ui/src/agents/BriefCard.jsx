import { briefLines, whenLabel } from '../lib/agents.js';
import { useNow } from '../lib/useNow.js';
import { dayLabel } from '../lib/charts.js';
import { EmptyState } from '../start/EmptyState.jsx';

const DOT = { ok: 'var(--teal)', watch: 'var(--mustard)', info: 'var(--sky)' };

export function BriefCard({ brief, i = 6, tag = "Today's brief", span = 'c4', emptyKey = 'bridge.brief', children }) {
  const now = useNow(60000);
  const b = brief.data;
  const lines = briefLines(b?.summary);
  const asOf = dayLabel(b?.as_of);
  return (
    <div className={`card ${span} brief`} style={{ '--i': i }} data-testid="brief">
      <div className="card-head">
        <span className="tag">{tag}</span>
        {b?.created_at ? <span className="chip">Plan keeper · {whenLabel(b.created_at, now)}</span> : null}
      </div>
      {lines.length ? (
        lines.map((l, k) => (
          <p key={k} data-tone={l.tone}>
            <i style={{ '--c': DOT[l.tone] }} aria-hidden="true" />
            <span>
              <span className="sr-only">{l.tone === 'watch' ? 'Heads up: ' : ''}</span>
              <b>{l.lead}</b>
              {l.rest ? ` ${l.rest}` : ''}
            </span>
          </p>
        ))
      ) : (
        brief.error || brief.loading ? (
          <p className="brief-empty">{brief.error ? "The brief didn't load. It comes back with the desk API." : 'Reading the brief…'}</p>
        ) : (
          <EmptyState k={emptyKey} slim icon="clock" why="No brief yet. The plan keeper writes one after its evening run." />
        )
      )}
      {children}
      {asOf ? <span className="muted brief-foot" data-testid="brief-foot">Built from engine numbers as of {asOf}</span> : null}
    </div>
  );
}

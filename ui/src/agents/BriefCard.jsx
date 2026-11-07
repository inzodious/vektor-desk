import { briefLines, whenLabel } from '../lib/agents.js';
import { useNow } from '../lib/useNow.js';
import { dayLabel } from '../lib/charts.js';

const DOT = { ok: 'var(--teal)', watch: 'var(--mustard)', info: 'var(--sky)' };

export function BriefCard({ brief, i = 6 }) {
  const now = useNow(60000);
  const b = brief.data;
  const lines = briefLines(b?.summary);
  return (
    <div className="card c4 brief" style={{ '--i': i }} data-testid="brief">
      <div className="card-head">
        <span className="tag">Today&apos;s brief</span>
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
        <p className="brief-empty">
          {brief.error ? "The brief didn't load. It comes back with the desk API." : brief.loading ? 'Reading the brief…' : 'No brief yet. The plan keeper writes one after its evening run.'}
        </p>
      )}
      {b?.as_of ? <span className="muted brief-foot">Built from engine numbers as of {dayLabel(b.as_of)}</span> : null}
    </div>
  );
}

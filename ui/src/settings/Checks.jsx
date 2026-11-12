import { useApi } from '../lib/api.js';
import { healthChecks } from '../lib/health.js';

export function Checks() {
  const api = useApi('/api/engine/health', { every: 600000 });
  const v = healthChecks(api.data);
  if (!v) return null;
  return (
    <details className="card c12 fold-card" data-testid="data-checks">
      <summary>
        <b>Data checks</b>
        <span className={`chip ${v.tone}`}>{v.chip}</span>
        <small>The desk checks its own data after every run and refreshes what it can by itself.</small>
      </summary>
      {v.rows.length ? (
        <ul className="check-list">
          {v.rows.map((r) => (
            <li key={r.key} data-status={r.status}>
              <b>{r.name}</b>
              <span>{r.detail}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {v.fine ? <p className="muted check-fine">{v.fine}</p> : null}
    </details>
  );
}

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
        <small>The desk checks its own data after every run and fixes what it can by itself.</small>
      </summary>
      {v.groups.map((g) => (
        <div className="check-group" key={g.key} data-kind={g.key}>
          <h3>{g.title}</h3>
          <ul className="check-list">
            {g.rows.map((r) => (
              <li key={r.key}>
                <b>{r.name}</b>
                <span>{r.detail}</span>
                {r.tried ? <small className="muted">{r.tried}</small> : null}
                {r.more ? (
                  <details className="check-more">
                    <summary>The longer version</summary>
                    <p>{r.more}</p>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {v.fine ? <p className="muted check-fine">{v.fine}</p> : null}
    </details>
  );
}

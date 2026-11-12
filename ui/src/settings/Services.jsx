import { servicesView } from '../lib/services.js';

export function Services({ containers }) {
  const v = servicesView(containers);
  if (!v) return null;
  return (
    <details className="card c12 fold-card" data-testid="services" data-state={v.state}>
      <summary>
        <b>Services</b>
        <span className={`chip ${v.tone}`}>{v.chip}</span>
        {v.note ? <small>{v.note}</small> : null}
      </summary>
      {v.rows.length ? (
        <div className="job-list">
          {v.rows.map((r) => (
            <div className="job-row" key={r.name} data-service={r.name}>
              <span className={`job-dot ${r.dot}`} aria-hidden="true" />
              <span className="job-text">
                <b>{r.title}</b>
                {r.words ? <small>{r.words}</small> : null}
              </span>
              <span className="job-act">
                <span className={`chip ${r.tone}`}>{r.t}</span>
              </span>
            </div>
          ))}
        </div>
      ) : null}
      {v.link ? (
        <p className="svc-link" data-testid="services-link">
          {v.link}
        </p>
      ) : null}
      {v.checked ? <p className="muted svc-checked">{v.checked}</p> : null}
    </details>
  );
}

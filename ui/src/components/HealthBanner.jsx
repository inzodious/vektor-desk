import { useState } from 'react';
import { Icon } from './Icon.jsx';
import { useApi } from '../lib/api.js';
import { healthBanner } from '../lib/health.js';

const KEY = 'desk.health.dismissed';

function readDismissed() {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function HealthBanner() {
  const api = useApi('/api/engine/health', { every: 600000 });
  const [dismissed, setDismissed] = useState(readDismissed);
  const b = healthBanner(api.data);
  if (!b || (b.level === 'warn' && dismissed === b.key)) return null;
  const hide = () => {
    setDismissed(b.key);
    try {
      window.localStorage.setItem(KEY, b.key);
    } catch {
      return;
    }
  };
  return (
    <section className={`health-banner ${b.level}`} role={b.level === 'fail' ? 'alert' : 'status'} data-testid="health-banner" data-level={b.level}>
      <Icon name="info" />
      <div className="hb-body">
        <p>
          <b>{b.head}</b> <span>{b.fix}</span>
        </p>
        {b.others.length ? (
          <details>
            <summary>{b.others.length === 1 ? '1 more check' : `${b.others.length} more checks`}</summary>
            <ul>
              {b.others.map((o) => (
                <li key={o.name} data-status={o.status}>
                  <b>{o.name}:</b> {o.detail}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
      {b.level === 'warn' ? (
        <button className="link" type="button" onClick={hide}>
          Hide until the next run
        </button>
      ) : null}
    </section>
  );
}

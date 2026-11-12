import { Icon } from './Icon.jsx';
import { useApi } from '../lib/api.js';
import { healthAlert } from '../lib/health.js';

export function HealthWatch() {
  const api = useApi('/api/engine/health', { every: 600000 });
  const b = healthAlert(api.data);
  if (!b) return null;
  return (
    <section className="health-banner fail" role="alert" data-testid="health-banner" data-level="fail">
      <Icon name="info" />
      <div className="hb-body">
        <p>
          <b>{b.head}</b> <span>{b.fix}</span>
        </p>
      </div>
    </section>
  );
}

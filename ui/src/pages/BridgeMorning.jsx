import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { useApi } from '../lib/api.js';
import { DOORS } from '../lib/morning.js';
import { useNow } from '../lib/useNow.js';

function Door({ door, now }) {
  const api = useApi(door.api, { every: 300000 });
  const v = door.view(api, now);
  return (
    <Link className={`door ${v.tone || ''}`} to={door.to} data-door={door.key} data-state={v.state}>
      <span className="desk-ico sm">
        <Icon name={door.icon} />
      </span>
      <span className="door-copy">
        <span className="kicker">{door.title}</span>
        <b data-testid={`door-${door.key}-count`}>
          {v.count}
          {v.unit ? <i> {v.unit}</i> : null}
        </b>
        <span className="door-line">{v.line}</span>
        <small>
          {v.fresh ? `${v.fresh} ET · ` : ''}
          <span className="door-go">{door.go}</span>
        </small>
      </span>
      <Icon name="right" />
    </Link>
  );
}

export function Morning() {
  const now = useNow(300000);
  const night = useApi('/api/overnight', { every: 120000 });
  const summary = night.data?.summary || 'What ran overnight, and where to read it';
  return (
    <section className="card morning" data-testid="morning" aria-label="This morning">
      <div className="card-head">
        <span className="tag mint">This morning</span>
        <span className="muted morning-sub" data-testid="morning-night" data-state={night.data?.state || 'unknown'}>
          {summary}
        </span>
      </div>
      <div className="doors">
        {DOORS.map((d) => (
          <Door door={d} now={now} key={d.key} />
        ))}
      </div>
    </section>
  );
}

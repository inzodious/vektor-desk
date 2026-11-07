import { Link } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { areaByKey } from '../lib/areas.js';

export default function Soon({ area }) {
  const a = areaByKey[area];
  return (
    <>
      <Hero kicker={a.kicker} title={a.title} art={a.art} foot={<span className="chip lilac">Lands in phase {a.phase}</span>} />
      <section className="card soon" style={{ '--i': 1 }}>
        <span className="desk-ico">
          <Icon name={a.key} />
        </span>
        <div>
          <b style={{ color: 'var(--ink)' }}>Not wired up yet</b>
          <p className="muted" style={{ fontSize: 12.5 }}>
            {a.lands}
          </p>
        </div>
        <Link className="btn ghost sm" to="/settings">
          <Icon name="settings" />
          Check data freshness
        </Link>
      </section>
    </>
  );
}

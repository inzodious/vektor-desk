import { Icon } from './Icon.jsx';
import { QUALITY } from '../lib/quality.js';

export function Kpi({ label, value, unit, line, quality, asOf, metric, spark, cream, i = 1, onOpen, tone }) {
  const q = quality && quality !== 'ok' ? QUALITY[quality] || quality : null;
  const title = [metric, asOf ? `as of ${asOf}` : null].filter(Boolean).join(' · ');
  return (
    <button type="button" className={`card kpi${cream ? ' cream' : ''}`} style={{ '--i': i }} title={title || undefined} onClick={onOpen} data-kpi={metric}>
      <span className="kicker">
        <span>{label}</span>
        <Icon name="right" />
      </span>
      <span className={`v${tone ? ` tone-${tone}` : ''}`}>
        {value}
        {unit ? <small>{unit}</small> : null}
      </span>
      <span className="d">
        {q ? <span className="chip lilac kpi-q">{q}</span> : null}
        {line}
        {asOf ? <span className="kpi-asof"> · {asOf}</span> : null}
      </span>
      {spark ? <span className="spark">{spark}</span> : null}
    </button>
  );
}

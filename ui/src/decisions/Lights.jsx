import { LAMP_COLOR, LAMP_WORD, lampSummary } from '../lib/decisions.js';

export function Lights({ lamps, big = false, withText = false }) {
  if (!lamps) return withText ? <span className="chip">Not checked</span> : null;
  const sum = lampSummary(lamps);
  const label = `Preflight: ${lamps.map((l) => `${l.label} ${LAMP_WORD[l.status]}`).join(', ')}`;
  return (
    <span className={`lights${big ? ' big' : ''}`} role="img" aria-label={label}>
      {lamps.map((l) => (
        <i key={l.id} title={`${l.label}: ${LAMP_WORD[l.status]}`} className={l.status} style={{ '--c': LAMP_COLOR[l.status] }} />
      ))}
      {withText ? <span className={`lights-text tone-${sum.tone}`}>{sum.text}</span> : null}
    </span>
  );
}

export function Conf({ value }) {
  if (value == null) return null;
  const steps = [0.2, 0.4, 0.6, 0.8, 1];
  return (
    <span className="conf" role="img" aria-label={`Confidence ${Math.round(value * 100)}%`} title={`Confidence ${Math.round(value * 100)}%`}>
      {steps.map((t) => (
        <i key={t} className={value >= t - 0.1 ? 'on' : ''} />
      ))}
    </span>
  );
}

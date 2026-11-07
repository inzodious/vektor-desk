import { LAMP_COLOR, LAMP_WORD } from '../lib/decisions.js';
import { usd } from '../lib/format.js';

const num = (v) => typeof v === 'number' && Number.isFinite(v);

function change(l) {
  if (!num(l.before) && !num(l.after)) return null;
  if (l.id === 'concentration') return [`${(l.before ?? 0).toFixed(1)}%`, `${(l.after ?? 0).toFixed(1)}%`];
  if (l.id === 'drift_after') return [`${(l.before ?? 0).toFixed(1)} pts`, `${(l.after ?? 0).toFixed(1)} pts`];
  if (l.id === 'funding') return l.after ? [usd(l.before ?? 0), `${usd(l.after)} on margin`] : null;
  return null;
}

function short(l) {
  if (l.id === 'plan_rules') return l.status === 'ok' ? 'All rules hold' : (l.detail || '').replace(/\.$/, '');
  if (l.id === 'wash_sales') return l.status === 'ok' ? 'None open' : l.clears ? `Clears ${l.clears}` : 'Window open';
  if (l.id === 'lots_tax') return l.status === 'ok' ? 'Checked' : 'Needs a look';
  if (l.id === 'funding') return l.status === 'ok' ? 'Covered' : 'Needs margin';
  return l.status === 'ok' ? 'Stays near' : 'Moves';
}

export function Annunciator({ lamps }) {
  return (
    <div className="annun" role="list" aria-label="Preflight lamps">
      {lamps.map((l) => {
        const c = change(l);
        return (
          <div className="lamp" role="listitem" key={l.id} style={{ '--c': LAMP_COLOR[l.status] }} title={l.detail || undefined} data-lamp={l.id} data-status={l.status}>
            <i aria-hidden="true" />
            <b>{l.label}</b>
            <small>
              <span className="sr-only">{LAMP_WORD[l.status]}. </span>
              {c ? (
                <>
                  {c[0]} → <em>{c[1]}</em>
                </>
              ) : (
                short(l)
              )}
            </small>
          </div>
        );
      })}
    </div>
  );
}

export function LampNotes({ lamps }) {
  const lit = lamps.filter((l) => l.status !== 'ok' && l.detail);
  if (!lit.length) return null;
  return (
    <ul className="lamp-notes">
      {lit.map((l) => (
        <li key={l.id} className={l.status}>
          <b>{l.label}</b> {l.detail}
        </li>
      ))}
    </ul>
  );
}

import { useState } from 'react';
import { Tip } from './Tip.jsx';
import { usd } from '../lib/format.js';

const fmtPct = (v, dg = 1) => (v == null ? '—' : `${v.toFixed(dg)}%`);
const fmtPts = (v) => (v == null ? '—' : `${v < 0 ? '−' : v > 0 ? '+' : ''}${Math.abs(v).toFixed(1)} pts`);

export function DriftRows({ rows, band = 5, onPick, values = {} }) {
  const [hover, setHover] = useState(null);
  const top = Math.max(10, ...rows.map((r) => Math.max(r.weight ?? 0, (r.target ?? 0) + band))) * 1.08;
  const X = (v) => `${(Math.max(0, v) / top) * 100}%`;
  return (
    <div className="drift">
      {rows.map((r) => {
        const target = r.target ?? 0;
        const lo = Math.max(0, target - band);
        const hi = target + band;
        const over = r.weight != null && (r.weight > hi || r.weight < lo);
        const label = `${r.symbol}: ${fmtPct(r.weight)} against a ${fmtPct(target, 0)} target, ${fmtPts(r.drift)}${over ? ', outside the band' : ''}`;
        return (
          <button
            type="button"
            key={r.symbol}
            className={`drift-row${over ? ' over' : ''}`}
            data-sym={onPick ? undefined : r.symbol}
            aria-label={label}
            onClick={onPick ? () => onPick(r) : undefined}
            onPointerMove={(e) => setHover({ r, at: { x: e.clientX, y: e.clientY } })}
            onPointerLeave={() => setHover(null)}
          >
            <span className="drift-name">{r.symbol}</span>
            <span className="drift-track" aria-hidden="true">
              <span className="drift-line" />
              {r.target != null ? <span className="drift-band" style={{ left: X(lo), width: `calc(${X(hi)} - ${X(lo)})` }} /> : null}
              {r.target != null ? <span className="drift-target" style={{ left: X(target) }} /> : null}
              {r.weight != null ? <span className="drift-dot" style={{ left: `calc(${X(r.weight)} - 7px)` }} /> : null}
            </span>
            <span className="drift-num">
              {fmtPct(r.weight)}
              <small>{r.target == null ? 'Not in plan' : fmtPts(r.drift)}</small>
            </span>
          </button>
        );
      })}
      <div className="legend drift-legend">
        <span>
          <i className="dot" style={{ '--c': 'var(--teal)' }} />
          Actual
        </span>
        <span>
          <i style={{ '--c': 'var(--ink)', width: 2, height: 12 }} />
          Target
        </span>
        <span>
          <i className="band" />
          Band ±{band} pts
        </span>
        <span>
          <i className="dot" style={{ '--c': 'var(--mustard)' }} />
          Outside band
        </span>
      </div>
      {hover ? (
        <Tip
          at={hover.at}
          head={hover.r.symbol}
          rows={[
            { color: 'var(--teal)', label: 'Actual', value: fmtPct(hover.r.weight) },
            { label: 'Target', value: fmtPct(hover.r.target, 0) },
            { label: 'Drift', value: fmtPts(hover.r.drift) },
            ...(values[hover.r.symbol] != null ? [{ label: 'Value', value: usd(values[hover.r.symbol]) }] : []),
          ]}
          hint="Click for the symbol sheet"
        />
      ) : null}
    </div>
  );
}

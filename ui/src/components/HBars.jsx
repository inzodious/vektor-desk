import { useState } from 'react';
import { Tip } from './Tip.jsx';
import { useWidth } from '../lib/useWidth.js';

export function HBars({ items, fmt = (v) => String(v), name = 'Value', label, labelW = 80, rowH = 26, tone = 'sign', legend, table = true, empty = 'Nothing to show yet.', onPick, picked }) {
  const [ref, width] = useWidth(360);
  const [asTable, setAsTable] = useState(false);
  const [hover, setHover] = useState(null);
  const W = Math.max(240, width);
  const vals = items.map((d) => d.value).filter((v) => v != null);
  const lo = Math.min(0, ...vals);
  const hi = Math.max(0, ...vals);
  const span = hi - lo || 1;
  const valW = 74;
  const L = labelW;
  const plot = W - L - valW;
  const X = (v) => L + ((v - lo) / span) * plot;
  const H = items.length * rowH + 4;
  const colorOf = (d) => (d.color ? d.color : tone === 'sign' ? (d.value < 0 ? 'var(--dn)' : 'var(--up)') : 'var(--s1)');

  if (!items.length || !vals.length)
    return (
      <div className="chart hbars" ref={ref}>
        <p className="empty-hint">{empty}</p>
      </div>
    );

  return (
    <div className="chart hbars" ref={ref}>
      {legend || table ? (
        <div className="chart-tools">
          {legend || <span />}
          {table ? (
            <button className="link" type="button" onClick={() => setAsTable((t) => !t)} aria-pressed={asTable}>
              {asTable ? 'Chart view' : 'Table view'}
            </button>
          ) : null}
        </div>
      ) : null}
      {asTable ? (
        <div className="tscroll chart-table">
          <table className="t">
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col" className="r">
                  {name}
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.label} className="still">
                  <td>{d.label}</td>
                  <td className="r">{d.value == null ? d.note || '—' : fmt(d.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label || name}>
          {lo < 0 ? <line className="axis" x1={X(0)} x2={X(0)} y1={0} y2={H} /> : null}
          {items.map((d, k) => {
            const y = k * rowH + 2;
            const has = d.value != null;
            const x0 = X(Math.min(0, d.value ?? 0));
            const x1 = X(Math.max(0, d.value ?? 0));
            return (
              <g
                key={d.label}
                data-bar={d.label}
                className={onPick ? `hb-pick${picked === d.label ? ' on' : ''}` : undefined}
                role={onPick ? 'button' : undefined}
                tabIndex={onPick ? 0 : undefined}
                aria-pressed={onPick ? picked === d.label : undefined}
                aria-label={onPick ? `${d.label}: ${has ? fmt(d.value) : d.note || 'no value'}` : undefined}
                onClick={onPick ? () => onPick(d) : undefined}
                onKeyDown={onPick ? (e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onPick(d)) : undefined}
                onPointerMove={(e) => setHover({ d, at: { x: e.clientX, y: e.clientY } })}
                onPointerLeave={() => setHover(null)}
              >
                <rect className="hit" x={0} y={y} width={W} height={rowH} rx={onPick ? 8 : undefined} />
                <text x={L - 8} y={y + rowH / 2 + 4} textAnchor="end" className="lbl hb-lbl">
                  {d.label}
                </text>
                {has ? <rect x={x0} y={y + 5} width={Math.max(2, x1 - x0)} height={rowH - 10} rx={4} fill={colorOf(d)} /> : null}
                <text x={W - 2} y={y + rowH / 2 + 4} textAnchor="end" className={has ? 'hb-val' : 'hb-none'}>
                  {has ? fmt(d.value) : d.note || '—'}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {hover && !asTable ? <Tip at={hover.at} head={hover.d.label} rows={[{ label: name, value: hover.d.value == null ? hover.d.note || '—' : fmt(hover.d.value), color: hover.d.value == null ? undefined : colorOf(hover.d) }]} hint={hover.d.hint} /> : null}
    </div>
  );
}

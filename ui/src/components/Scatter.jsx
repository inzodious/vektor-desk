import { useState } from 'react';
import { Tip } from './Tip.jsx';
import { useWidth } from '../lib/useWidth.js';
import { niceTicks } from '../lib/charts.js';

function placeLabels(pts, X, Y, W) {
  const boxes = [];
  return pts.map((p) => {
    const left = X(p.x) > W - 90;
    const w = String(p.label).length * 6.6 + 4;
    const x0 = left ? X(p.x) - 10 - w : X(p.x) + 10;
    const base = Y(p.y) + 4 + (p.dy || 0);
    let y = base;
    for (const step of [0, -13, 13, -26, 26, -39, 39]) {
      y = base + step;
      const hit = boxes.some((b) => x0 < b.x1 && x0 + w > b.x0 && Math.abs(y - b.y) < 12);
      if (!hit) break;
    }
    boxes.push({ x0, x1: x0 + w, y });
    return { left, y };
  });
}

export function Scatter({ points, xName, yName, fmtX = (v) => v, fmtY = (v) => v, height = 260, label, table = true, legend }) {
  const [ref, width] = useWidth(420);
  const [asTable, setAsTable] = useState(false);
  const [hover, setHover] = useState(null);
  const W = Math.max(280, width);
  const H = height;
  const L = 46;
  const R = 16;
  const T = 12;
  const B = 34;
  const pts = points.filter((p) => p.x != null && p.y != null);
  const xs = pts.map((p) => p.x);
  const ys = pts.map((p) => p.y);
  const xt = niceTicks(Math.min(0, ...xs), Math.max(...xs, 1), 4);
  const yt = niceTicks(Math.min(0, ...ys), Math.max(0, ...ys), 4);
  const X = (v) => L + ((v - xt[0]) / (xt[xt.length - 1] - xt[0] || 1)) * (W - L - R);
  const Y = (v) => T + (1 - (v - yt[0]) / (yt[yt.length - 1] - yt[0] || 1)) * (H - T - B);
  const spots = placeLabels(pts, X, Y, W);

  return (
    <div className="chart scatter" ref={ref}>
      <div className="chart-tools">
        {legend || <span />}
        {table ? (
          <button className="link" type="button" onClick={() => setAsTable((t) => !t)} aria-pressed={asTable}>
            {asTable ? 'Chart view' : 'Table view'}
          </button>
        ) : null}
      </div>
      {asTable ? (
        <div className="tscroll chart-table">
          <table className="t">
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col" className="r">
                  {xName}
                </th>
                <th scope="col" className="r">
                  {yName}
                </th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.label} className="still">
                  <td>{p.label}</td>
                  <td className="r">{p.x == null ? '—' : fmtX(p.x)}</td>
                  <td className="r">{p.y == null ? '—' : fmtY(p.y)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label || `${yName} against ${xName}`}>
          {yt.map((t) => (
            <g key={`y${t}`}>
              <line className={t === 0 ? 'axis' : 'gridl'} x1={L} x2={W - R} y1={Y(t)} y2={Y(t)} />
              <text x={L - 8} y={Y(t) + 4} textAnchor="end">
                {fmtY(t)}
              </text>
            </g>
          ))}
          {xt.map((t) => (
            <text key={`x${t}`} x={X(t)} y={H - 16} textAnchor="middle">
              {fmtX(t)}
            </text>
          ))}
          <text x={W - R} y={H - 2} textAnchor="end" className="axis-name">
            {xName} →
          </text>
          {pts.map((p, k) => {
            const { left, y } = spots[k];
            return (
              <g key={p.label} data-point={p.label} data-sym={p.sym || undefined} className={p.sym ? 'pt sym-pt' : 'pt'} onPointerMove={(e) => setHover({ p, at: { x: e.clientX, y: e.clientY } })} onPointerLeave={() => setHover(null)}>
                <circle cx={X(p.x)} cy={Y(p.y)} r={p.r || 6} fill={p.color} stroke="var(--card)" strokeWidth="2" />
                <text x={X(p.x) + (left ? -10 : 10)} y={y} textAnchor={left ? 'end' : 'start'} className="lbl">
                  {p.label}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {hover && !asTable ? (
        <Tip
          at={hover.at}
          head={hover.p.label}
          rows={[
            { label: xName, value: fmtX(hover.p.x) },
            { label: yName, value: fmtY(hover.p.y), color: hover.p.color },
          ]}
          hint={hover.p.sym ? 'Click for the symbol sheet' : undefined}
        />
      ) : null}
    </div>
  );
}

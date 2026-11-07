import { useState } from 'react';
import { Tip } from './Tip.jsx';
import { useWidth } from '../lib/useWidth.js';
import { divergingColor } from '../lib/charts.js';

export function Heatmap({ rows, cols, values, color = divergingColor, fmt = (v) => v.toFixed(2), name = 'Value', label, cellH = 30, showVals = true, rowW = 64, tipHead, table = true, scale }) {
  const [ref, width] = useWidth(420);
  const [asTable, setAsTable] = useState(false);
  const [hover, setHover] = useState(null);
  const W = Math.max(260, width);
  const T = 22;
  const cw = (W - rowW) / Math.max(1, cols.length);
  const H = T + rows.length * cellH;
  const narrow = cw < 34;

  return (
    <div className="chart heat" ref={ref}>
      {table ? (
        <div className="chart-tools">
          {scale || <span />}
          <button className="link" type="button" onClick={() => setAsTable((t) => !t)} aria-pressed={asTable}>
            {asTable ? 'Chart view' : 'Table view'}
          </button>
        </div>
      ) : null}
      {asTable ? (
        <div className="tscroll chart-table">
          <table className="t">
            <thead>
              <tr>
                <th scope="col" />
                {cols.map((c) => (
                  <th scope="col" className="r" key={c}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r} className="still">
                  <th scope="row">{r}</th>
                  {cols.map((c, j) => (
                    <td className="r" key={c}>
                      {values[i]?.[j] == null ? '—' : fmt(values[i][j])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label || name}>
          {cols.map((c, j) => (
            <text key={c} x={rowW + j * cw + cw / 2} y={14} textAnchor="middle" className="hm-col">
              {narrow && c.length > 3 ? c.slice(0, 3) : c}
            </text>
          ))}
          {rows.map((r, i) => (
            <g key={r}>
              <text x={rowW - 8} y={T + i * cellH + cellH / 2 + 4} textAnchor="end" className="lbl">
                {r}
              </text>
              {cols.map((c, j) => {
                const v = values[i]?.[j];
                const x = rowW + j * cw;
                const y = T + i * cellH;
                const col = v == null ? null : color(v);
                return (
                  <g key={c} onPointerMove={(e) => setHover({ i, j, v, at: { x: e.clientX, y: e.clientY } })} onPointerLeave={() => setHover(null)}>
                    <rect x={x + 1} y={y + 1} width={cw - 2} height={cellH - 2} rx={5} fill={col ? col.fill : 'var(--track)'} />
                    {showVals && v != null && !narrow ? (
                      <text x={x + cw / 2} y={y + cellH / 2 + 4} textAnchor="middle" className="hm-val" style={{ fill: col.ink }}>
                        {fmt(v)}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </g>
          ))}
        </svg>
      )}
      {hover && !asTable ? <Tip at={hover.at} head={tipHead ? tipHead(hover.i, hover.j) : `${rows[hover.i]} · ${cols[hover.j]}`} rows={[{ label: name, value: hover.v == null ? '—' : fmt(hover.v) }]} /> : null}
    </div>
  );
}

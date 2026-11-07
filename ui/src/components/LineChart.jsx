import { useMemo, useState } from 'react';
import { Tip } from './Tip.jsx';
import { useWidth } from '../lib/useWidth.js';
import { dayLabel, extent, linePath, monthTicks, niceTicks } from '../lib/charts.js';

export function Legend({ series }) {
  return (
    <div className="legend">
      {series.map((s) => (
        <span key={s.name}>
          <i className={s.dash ? 'dash' : undefined} style={{ '--c': s.color }} />
          {s.name}
        </span>
      ))}
    </div>
  );
}

export function LineChart({ series, x, height = 240, fmtY = (v) => v, fmtTip, refs = [], markers = [], label = 'Line chart', endLabels = false, zero = false, tipHint, onPick, table = true, tableFmt }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const [asTable, setAsTable] = useState(false);
  const W = Math.max(280, width);
  const H = height;
  const narrow = W < 520;
  const L = 52;
  const R = endLabels && !narrow ? 92 : 12;
  const T = 10;
  const B = 26;
  const n = x.length;

  const geo = useMemo(() => {
    let [lo, hi] = extent(series, refs);
    if (zero) {
      lo = Math.min(lo, 0);
      hi = Math.max(hi, 0);
    }
    const ticks = niceTicks(lo, hi, narrow ? 3 : 4);
    lo = ticks[0];
    hi = ticks[ticks.length - 1];
    const X = (i) => L + (n > 1 ? i / (n - 1) : 0.5) * (W - L - R);
    const Y = (v) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
    return { ticks, X, Y };
  }, [series, refs, zero, narrow, n, W, R, H]);

  const xticks = useMemo(() => monthTicks(x, narrow ? 4 : 9), [x, narrow]);

  if (!n) return <p className="empty-hint">Nothing to chart yet.</p>;
  const { ticks, X, Y } = geo;
  const fmt = fmtTip || fmtY;

  const move = (e) => {
    const svg = e.currentTarget.ownerSVGElement;
    const r = svg.getBoundingClientRect();
    const sx = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((sx - L) / (W - L - R)) * (n - 1))));
    setHover({ i, at: { x: e.clientX, y: e.clientY } });
  };

  const ends = [];
  if (endLabels && !narrow) {
    series.forEach((s) => {
      const v = s.values[n - 1];
      if (v == null) return;
      let y = Y(v) + 4;
      ends.forEach((p) => {
        if (Math.abs(p.y - y) < 14) y = p.y + (y >= p.y ? 14 : -14);
      });
      ends.push({ y, name: s.short || s.name });
    });
  }

  return (
    <div className={`chart${hover ? ' hover' : ''}`} ref={ref}>
      <div className="chart-tools">
        {series.length > 1 ? <Legend series={series} /> : <span />}
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
                <th scope="col">Date</th>
                {series.map((s) => (
                  <th scope="col" className="r" key={s.name}>
                    {s.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {x
                .map((d, i) => ({ d, i }))
                .reverse()
                .map(({ d, i }) => (
                  <tr key={d} className="still">
                    <td>{dayLabel(d, true)}</td>
                    {series.map((s) => (
                      <td className="r" key={s.name}>
                        {s.values[i] == null ? '—' : (tableFmt || fmt)(s.values[i], s, i)}
                      </td>
                    ))}
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="gridl" x1={L} x2={W - R} y1={Y(t)} y2={Y(t)} />
              <text x={L - 8} y={Y(t) + 4} textAnchor="end">
                {fmtY(t)}
              </text>
            </g>
          ))}
          {xticks.map((t) => (
            <text key={t.i} x={X(t.i)} y={H - 6} textAnchor="middle">
              {t.label}
            </text>
          ))}
          {refs.map((r) => (
            <g key={r.label || r.y}>
              <line className="ref" x1={L} x2={W - R} y1={Y(r.y)} y2={Y(r.y)} />
              {r.label ? (
                <text x={L + 6} y={Y(r.y) - 6} className="lbl" style={{ fontWeight: 600 }}>
                  {r.label}
                </text>
              ) : null}
            </g>
          ))}
          {zero ? <line className="axis" x1={L} x2={W - R} y1={Y(0)} y2={Y(0)} /> : null}
          {series.map((s) => (
            <path key={s.name} className="mark" d={linePath(s.values, X, Y)} fill="none" stroke={s.color} strokeWidth={s.width || 2} strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dash ? '5 5' : undefined} />
          ))}
          {markers.map((m) =>
            series[0].values[m.i] == null ? null : <circle key={`${m.i}-${m.label}`} cx={X(m.i)} cy={Y(series[0].values[m.i])} r="5" fill={m.color || 'var(--card)'} stroke={series[0].color} strokeWidth="2" />,
          )}
          {ends.map((e) => (
            <text key={e.name} x={W - R + 8} y={e.y} className="lbl">
              {e.name}
            </text>
          ))}
          {hover ? (
            <>
              <line className="xh" x1={X(hover.i)} x2={X(hover.i)} y1={T} y2={H - B} style={{ opacity: 0.6 }} />
              {series.map((s) => (s.values[hover.i] == null ? null : <circle key={s.name} r="4.5" cx={X(hover.i)} cy={Y(s.values[hover.i])} fill={s.color} stroke="var(--card)" strokeWidth="2" />))}
            </>
          ) : null}
          <rect className="hit" x={L} y={T} width={W - L - R} height={H - T - B} onPointerMove={move} onPointerLeave={() => setHover(null)} onClick={onPick && hover ? () => onPick(hover.i) : undefined} />
        </svg>
      )}
      {hover && !asTable ? (
        <Tip
          at={hover.at}
          head={dayLabel(x[hover.i], true)}
          rows={series.filter((s) => s.values[hover.i] != null).map((s) => ({ color: s.color, label: s.name, value: fmt(s.values[hover.i], s, hover.i) }))}
          hint={[markers.find((m) => m.i === hover.i)?.label, tipHint].filter(Boolean).join(' · ') || undefined}
        />
      ) : null}
    </div>
  );
}

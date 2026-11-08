import { useState } from 'react';
import { money } from '../lib/mixes.js';
import { useWidth } from '../lib/useWidth.js';

const H = 180;
const L = 44;
const R = 10;
const T = 10;
const B = 24;

function ticks(lo, hi) {
  const out = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e += 1) {
    [1, 3].forEach((m) => {
      const v = m * 10 ** e;
      if (v >= lo && v <= hi) out.push(v);
    });
  }
  return out;
}

export function RangeBars({ bands = [], fi = null, label }) {
  const [asTable, setAsTable] = useState(false);
  const [ref, width] = useWidth();
  const W = Math.max(260, width);
  const rows = bands.filter((b) => b.p10 != null && b.p90 != null);
  if (!rows.length) return null;
  const vals = rows.flatMap((b) => [b.p10, b.p90, b.contributed]).concat(fi ? [fi] : []).filter((v) => v > 0);
  const lo = Math.min(...vals) * 0.8;
  const hi = Math.max(...vals) * 1.15;
  const y = (v) => T + (H - T - B) * (1 - (Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo)));
  const step = (W - L - R) / rows.length;
  const x = (i) => L + step * (i + 0.5);
  const yt = ticks(lo, hi);
  return (
    <div className="chart range-bars" ref={ref}>
      <div className="chart-tools">
        <span className="rb-key">
          <i className="rb-k-range" aria-hidden="true" />1 in 10 to 9 in 10
          <i className="rb-k-mid" aria-hidden="true" />
          Middle
          <i className="rb-k-in" aria-hidden="true" />
          Put in
          {fi ? (
            <>
              <i className="rb-k-fi" aria-hidden="true" />
              FI
            </>
          ) : null}
        </span>
        <button className="link" type="button" onClick={() => setAsTable((t) => !t)} aria-pressed={asTable}>
          {asTable ? 'Chart view' : 'Table view'}
        </button>
      </div>
      {asTable ? (
        <div className="tscroll chart-table">
          <table className="t">
            <thead>
              <tr>
                <th scope="col">In</th>
                <th scope="col" className="r">
                  Low (1 in 10)
                </th>
                <th scope="col" className="r">
                  Middle
                </th>
                <th scope="col" className="r">
                  High (9 in 10)
                </th>
                <th scope="col" className="r">
                  Put in
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.years} className="still">
                  <td>{b.years === 1 ? '1 year' : `${b.years} years`}</td>
                  <td className="r">{money(b.p10)}</td>
                  <td className="r">{money(b.p50)}</td>
                  <td className="r">{money(b.p90)}</td>
                  <td className="r">{money(b.contributed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={label}>
          {yt.map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--grid)" strokeWidth="1" />
              <text x={L - 6} y={y(v) + 3.5} textAnchor="end" className="rb-tick">
                {money(v)}
              </text>
            </g>
          ))}
          {fi ? <line x1={L} x2={W - R} y1={y(fi)} y2={y(fi)} stroke="var(--coral)" strokeWidth="1.5" strokeDasharray="5 4" /> : null}
          {rows.map((b, i) => (
            <g key={b.years} data-years={b.years}>
              <line x1={x(i)} x2={x(i)} y1={y(b.p10)} y2={y(b.p90)} stroke="var(--s1)" strokeWidth="12" strokeLinecap="round" opacity="0.55" />
              {b.contributed > 0 ? <line x1={x(i) - 11} x2={x(i) + 11} y1={y(b.contributed)} y2={y(b.contributed)} stroke="var(--mustard-ink)" strokeWidth="2" strokeDasharray="3 2" /> : null}
              <circle cx={x(i)} cy={y(b.p50)} r="5" fill="var(--ink)" stroke="var(--card)" strokeWidth="2" />
              <text x={x(i)} y={H - 6} textAnchor="middle" className="rb-tick">
                {b.years}y
              </text>
            </g>
          ))}
        </svg>
      )}
    </div>
  );
}

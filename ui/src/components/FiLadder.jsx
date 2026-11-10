import { useState } from 'react';
import { chanceText, ladderColumns, money, yearsText } from '../lib/mixes.js';
import { useWidth } from '../lib/useWidth.js';

const H = 230;
const L = 40;
const R = 12;
const T = 22;
const B = 40;

const bare = (v, max) => yearsText(v, max).replace(/ years?$/, '');

function span(l, max) {
  const lo = l.fastest?.years ?? null;
  const hi = l.slowest?.years ?? null;
  if (lo == null || (hi != null && Math.abs(hi - lo) < 0.05)) return yearsText(lo, max);
  return `${bare(lo, max)} to ${yearsText(hi, max)}`;
}

export function FiLadder({ ladder, targetYears = null, targetLabel = null, label }) {
  const [asTable, setAsTable] = useState(false);
  const [ref, width] = useWidth();
  const W = Math.max(260, width);
  const { levels, max } = ladder;
  const cols = ladderColumns(levels, Math.max(5, Math.floor((W - L - R) / 46)));
  const top = max;
  const y = (v) => T + (H - T - B) * (1 - Math.min(v ?? top, top) / top);
  const step = (W - L - R) / cols.length;
  const x = (i) => L + step * (i + 0.5);
  const ticks = [0, 10, 20, 30, 40].filter((v) => v <= top);
  const byTarget = targetLabel ? `By ${targetLabel}` : 'By your date';
  return (
    <div className="chart fi-ladder" ref={ref} data-testid="fi-ladder">
      <div className="chart-tools">
        <span className="rb-key">
          <b className="fl-axis">Years to FI</b>
          <i className="rb-k-range" aria-hidden="true" />1 in 10 to 9 in 10, {ladder.ref.name}
          <i className="fl-k-mid" aria-hidden="true" />
          Middle path, {ladder.mixes === 1 ? 'the mix' : `all ${ladder.mixes} mixes`}
          {targetYears != null ? (
            <>
              <i className="rb-k-fi" aria-hidden="true" />
              {targetLabel || 'Your date'}
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
                <th scope="col">A month</th>
                <th scope="col" className="r">
                  Middle
                </th>
                <th scope="col" className="r">
                  Early (1 in 10)
                </th>
                <th scope="col" className="r">
                  Late (9 in 10)
                </th>
                <th scope="col" className="r">
                  Across mixes
                </th>
                {targetYears != null ? (
                  <th scope="col" className="r">
                    {byTarget}
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {levels.map((l) => (
                <tr key={l.deposit} className={l.current ? 'still fl-you' : 'still'} data-deposit={l.deposit}>
                  <td>
                    {money(l.deposit)}
                    {l.current ? ' (you)' : ''}
                  </td>
                  <td className="r">{yearsText(l.p50, max)}</td>
                  <td className="r">{yearsText(l.p10, max)}</td>
                  <td className="r">{yearsText(l.p90, max)}</td>
                  <td className="r">{span(l, max)}</td>
                  {targetYears != null ? <td className="r">{chanceText(l.chance) || '—'}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={label}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--grid)" strokeWidth="1" />
              <text x={L - 6} y={y(v) + 3.5} textAnchor="end" className="rb-tick">
                {v === top ? `${v}+` : v}
              </text>
            </g>
          ))}
          {targetYears != null && targetYears < top ? <line x1={L} x2={W - R} y1={y(targetYears)} y2={y(targetYears)} stroke="var(--coral)" strokeWidth="1.5" strokeDasharray="5 4" /> : null}
          {cols.map((l, i) => {
            const lo = l.fastest?.years;
            const hi = l.slowest?.years;
            return (
              <g key={l.deposit} data-deposit={l.deposit} data-current={l.current ? 'yes' : 'no'}>
                {l.current ? <rect x={x(i) - step / 2 + 3} y={T - 6} width={step - 6} height={H - T - 8} rx="10" fill="var(--teal-soft)" /> : null}
                {l.p10 != null ? <line x1={x(i)} x2={x(i)} y1={y(l.p10)} y2={y(l.p90)} stroke="var(--s1)" strokeWidth="12" strokeLinecap="round" opacity="0.55" /> : null}
                {lo != null ? <line x1={x(i)} x2={x(i)} y1={y(lo)} y2={y(hi)} stroke="var(--ink)" strokeWidth="7" strokeLinecap="round" /> : null}
                {lo == null ? (
                  <text x={x(i)} y={y(top) - 9} textAnchor="middle" className="rb-tick">
                    {top}+
                  </text>
                ) : null}
                <text x={x(i)} y={H - 20} textAnchor="middle" className={l.current ? 'rb-tick fl-on' : 'rb-tick'}>
                  {money(l.deposit)}
                </text>
                {l.current ? (
                  <text x={x(i)} y={H - 6} textAnchor="middle" className="rb-tick fl-on">
                    You
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

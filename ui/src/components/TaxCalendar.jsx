import { useMemo, useState } from 'react';
import { useWidth } from '../lib/useWidth.js';
import { accountLabel } from '../live/context.js';
import { dayLabel, parseDay } from '../lib/charts.js';
import { mergeWindows, windowLine } from '../lib/tax.js';

const DAY = 86400000;
const MAX_DAYS = 200;
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const KIND = {
  recent_buy: { label: 'Recent buy', color: 'var(--s5)', soft: 'var(--sky-soft)' },
  loss_sale: { label: 'Loss sale', color: 'var(--s4)', soft: 'var(--mustard-soft)' },
};

const iso = (t) => new Date(t).toISOString().slice(0, 10);

export function TaxCalendar({ events = [], windows = [], today }) {
  const [ref, width] = useWidth(720);
  const [asTable, setAsTable] = useState(false);
  const rows = useMemo(() => mergeWindows(windows), [windows]);
  const t0 = parseDay(today).getTime();
  const start = Math.min(t0 - 7 * DAY, ...rows.map((r) => parseDay(r.date).getTime()));
  const wantEnd = Math.max(t0 + 45 * DAY, ...rows.map((r) => parseDay(r.clears).getTime()), ...events.map((e) => parseDay(e.date).getTime()));
  const end = Math.min(wantEnd, start + MAX_DAYS * DAY);
  const upcoming = events.filter((e) => e.date >= iso(t0)).sort((a, b) => a.date.localeCompare(b.date));
  const shown = upcoming.filter((e) => parseDay(e.date).getTime() <= end);
  const narrow = width < 520;
  const L = narrow ? 52 : 70;
  const R = 14;
  const TOP = 34;
  const ROW = 26;
  const H = TOP + Math.max(1, rows.length) * ROW + 28;
  const X = (t) => L + ((t - start) / (end - start || 1)) * (width - L - R);
  const months = [];
  for (let d = new Date(start); d.getTime() <= end; d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1))) {
    const first = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
    if (first >= start) months.push(first);
  }
  const every = Math.ceil(months.length / (narrow ? 4 : 8));

  return (
    <div className="chart tax-cal" ref={ref}>
      <div className="chart-tools">
        <div className="legend">
          <span>
            <i style={{ '--c': KIND.recent_buy.color }} />
            Recent buy window
          </span>
          <span>
            <i style={{ '--c': KIND.loss_sale.color }} />
            Loss sale window
          </span>
          <span>
            <i className="diamond" />
            Tax date
          </span>
        </div>
        <button className="link" type="button" onClick={() => setAsTable((t) => !t)} aria-pressed={asTable}>
          {asTable ? 'Chart view' : 'Table view'}
        </button>
      </div>
      {asTable ? (
        <div className="tscroll chart-table">
          <table className="t">
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">What</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {[
                ...upcoming.map((e) => ({ date: e.date, what: 'Tax date', detail: e.title, key: `e-${e.date}-${e.title}` })),
                ...rows.map((w) => ({ date: w.clears, what: `${w.symbol} window clears`, detail: `${windowLine(w)} ${w.accounts.map(accountLabel).join(', ')}.`, key: `w-${w.symbol}-${w.kind}` })),
              ]
                .sort((a, b) => a.date.localeCompare(b.date))
                .map((r) => (
                  <tr key={r.key} className="still">
                    <td>{dayLabel(r.date, true)}</td>
                    <td>{r.what}</td>
                    <td>{r.detail}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ) : (
        <svg viewBox={`0 0 ${width} ${H}`} role="img" aria-label={`Tax calendar: ${shown.length} tax dates and ${rows.length} wash-sale windows`}>
          {months.map((m, k) => (
            <g key={m}>
              <line className="gridl" x1={X(m)} x2={X(m)} y1={TOP - 6} y2={H - 22} />
              {k % every === 0 ? (
                <text x={X(m) + 3} y={H - 6}>
                  {MON[new Date(m).getUTCMonth()]}
                </text>
              ) : null}
            </g>
          ))}
          {shown.map((e, k) => {
            const x = X(parseDay(e.date).getTime());
            return (
              <g key={`${e.date}-${e.title}`} className="tax-date">
                <title>{`${dayLabel(e.date, true)}: ${e.title}`}</title>
                <line x1={x} x2={x} y1={20} y2={H - 22} className="tax-date-line" />
                <path d={`M${x} 6 l7 7 l-7 7 l-7 -7z`} className="tax-diamond" />
                <text x={x} y={17} textAnchor="middle" className="tax-num">
                  {k + 1}
                </text>
              </g>
            );
          })}
          {rows.map((w, k) => {
            const y = TOP + k * ROW;
            const x1 = X(parseDay(w.date).getTime());
            const x2 = X(parseDay(w.clears).getTime());
            const kind = KIND[w.kind] || KIND.recent_buy;
            const label = `clears ${dayLabel(w.clears)}`;
            const room = width - R - x2 > 74;
            return (
              <g key={`${w.symbol}-${w.kind}`} data-wash={w.symbol}>
                <title>{windowLine(w)}</title>
                <text x={L - 8} y={y + 14} textAnchor="end" className="tax-sym">
                  {w.symbol}
                </text>
                <rect x={x1} y={y + 4} width={Math.max(4, x2 - x1)} height={14} rx={7} fill={kind.soft} stroke={kind.color} strokeWidth={1.5} />
                <text x={room ? x2 + 6 : x2 - 6} y={y + 15} textAnchor={room ? 'start' : 'end'} className="tax-lbl">
                  {label}
                </text>
              </g>
            );
          })}
          {!rows.length ? (
            <text x={L} y={TOP + 16} className="tax-lbl">
              No wash-sale windows open
            </text>
          ) : null}
          <line x1={X(t0)} x2={X(t0)} y1={TOP - 10} y2={H - 22} className="tax-today" />
          <text x={X(t0) + 4} y={TOP - 2} className="tax-lbl">
            Today
          </text>
        </svg>
      )}
      {upcoming.length ? (
        <ol className="tax-list">
          {upcoming.map((e, k) => (
            <li key={`${e.date}-${e.title}`} className={parseDay(e.date).getTime() > end ? 'later' : ''}>
              <span className="tax-badge">{parseDay(e.date).getTime() > end ? '·' : k + 1}</span>
              <b>{dayLabel(e.date, true)}</b> {e.title}
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty-hint">No tax dates coming up.</p>
      )}
    </div>
  );
}

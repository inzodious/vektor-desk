import { Spark } from './Spark.jsx';
import { pct, px, usd } from '../lib/format.js';

export function Flap({ text, size = 5 }) {
  const chars = String(text).toUpperCase().padEnd(size, ' ').split('');
  return (
    <span className="flap" aria-label={text}>
      {chars.map((c, i) => (
        <span key={`${i}-${c}`} className="flip" aria-hidden="true">
          {c === ' ' ? ' ' : c}
        </span>
      ))}
    </span>
  );
}

export function Board({ rows, names = {}, intraday = {}, label = 'Live holdings', nav = false }) {
  return (
    <div className="board" role="table" aria-label={label}>
      <div className="board-row head" role="row">
        <span role="columnheader">Symbol</span>
        <span role="columnheader">Name</span>
        <span role="columnheader" style={{ textAlign: 'right' }}>
          Last
        </span>
        <span role="columnheader" style={{ textAlign: 'right' }}>
          Today
        </span>
        <span role="columnheader" style={{ textAlign: 'right' }}>
          Value
        </span>
        <span role="columnheader">Session</span>
      </div>
      {rows.map((r) => {
        const up = (r.day_change ?? 0) >= 0;
        const series = intraday[r.symbol]?.map((p) => p.price);
        return (
          <div className="board-row" role="row" key={r.symbol} data-sym={r.symbol} tabIndex={0} aria-label={`${r.symbol}, open symbol sheet`}>
            <span role="cell">
              <Flap text={r.symbol} />
            </span>
            <span role="cell" className="nm">
              {names[r.symbol] || '—'}
              {nav && r.source === 'holdings' ? <span className="tag-nav">NAV</span> : null}
            </span>
            <span role="cell" className="px" key={`p-${r.price}`}>
              {px(r.price)}
            </span>
            <span role="cell" className={`ch ${up ? 'u' : 'd'}`}>
              {r.change_pct == null ? '—' : pct(r.change_pct, 2, true)}
              <small style={{ display: 'block', fontWeight: 600, opacity: 0.8 }}>{usd(r.day_change, { sign: true })}</small>
            </span>
            <span role="cell" className="px" style={{ fontSize: 18 }}>
              {usd(r.value)}
            </span>
            <span role="cell" className="sp">
              {series && series.length > 1 ? <Spark values={series} base={r.prev_close} color={up ? '#7fe3c2' : '#ffd677'} /> : <span className="nm">{r.source !== 'holdings' ? 'No ticks yet' : nav ? 'Prices at 4 PM' : 'Last close'}</span>}
            </span>
          </div>
        );
      })}
    </div>
  );
}

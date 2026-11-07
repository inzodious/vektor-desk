import { Panel } from '../components/Panel.jsx';
import { DriftRows } from '../components/DriftRows.jsx';
import { accountLabel } from '../live/context.js';
import { val } from '../lib/metrics.js';
import { pct, plural, usd } from '../lib/format.js';

const WINDOWS = [
  { v: 'MTD', t: 'Month to date' },
  { v: 'QTD', t: 'Quarter to date' },
  { v: 'YTD', t: 'Year to date' },
  { v: '1Y', t: 'Past year' },
  { v: 'ITD', t: 'Since the start' },
];

const toneOf = (v) => (v == null ? '' : v >= 0 ? 'up' : 'dn');

export function ValueDrawer({ open, onClose, accounts, total, symbols }) {
  const rows = [...symbols].sort((a, b) => Math.abs(b.day_change) - Math.abs(a.day_change));
  return (
    <Panel open={open} onClose={onClose} title="Market value" sub="Split by account, then today's move by holding." crumbs={[{ label: 'Bridge', go: onClose }]}>
      <div className="tscroll">
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Account</th>
              <th scope="col" className="r">
                Value
              </th>
              <th scope="col" className="r">
                Share
              </th>
              <th scope="col" className="r">
                Today
              </th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.account} className="still">
                <td>{accountLabel(a.account)}</td>
                <td className="r">{usd(a.value)}</td>
                <td className="r">{pct(total ? a.value / total : 0)}</td>
                <td className={`r ${toneOf(a.day_change)}`}>{usd(a.day_change, { sign: true })}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td className="r">{usd(total)}</td>
              <td className="r">100%</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
      <span className="kicker">Today by holding</span>
      <div className="rows">
        {rows.map((r) => (
          <button type="button" className="row row-btn" key={r.symbol} onClick={() => onClose(r.symbol)}>
            <span className="l">
              <span className="sym">
                <i style={{ '--c': 'var(--s1)' }} />
                {r.symbol}
              </span>
            </span>
            <span className="v">
              <span className={toneOf(r.day_change)}>{usd(r.day_change, { sign: true })}</span>
              <small>{r.change_pct == null ? '—' : pct(r.change_pct, 2, true)}</small>
            </span>
          </button>
        ))}
      </div>
    </Panel>
  );
}

export function ExcessDrawer({ open, onClose, m }) {
  return (
    <Panel open={open} onClose={onClose} title="Against the shadows" sub="Your value minus a shadow that got the same deposits on the same days." crumbs={[{ label: 'Bridge', go: onClose }]}>
      <div className="tscroll">
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Window</th>
              <th scope="col" className="r">
                vs plan
              </th>
              <th scope="col" className="r">
                vs S&amp;P 500
              </th>
            </tr>
          </thead>
          <tbody>
            {WINDOWS.map((w) => {
              const p = val(m.get('bm.excess', { scope: 'shadow', scopeId: 'plan_shadow', window: w.v }));
              const s = val(m.get('bm.excess', { scope: 'shadow', scopeId: 'sp500_shadow', window: w.v }));
              return (
                <tr key={w.v} className="still">
                  <td>{w.t}</td>
                  <td className={`r ${toneOf(p)}`}>{p == null ? '—' : usd(p, { sign: true })}</td>
                  <td className={`r ${toneOf(s)}`}>{s == null ? '—' : usd(s, { sign: true })}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 12.5 }}>
        Dollars, not percents, so a short window never turns into a scary annual rate.
      </p>
    </Panel>
  );
}

export function DriftDrawer({ open, onClose, funds, band, values }) {
  return (
    <Panel open={open} onClose={onClose} title="Drift by fund" sub="Actual weight against the plan target. Pick a fund for its symbol sheet." crumbs={[{ label: 'Bridge', go: onClose }]}>
      <DriftRows rows={funds.filter((f) => f.target != null)} band={band} values={values} onPick={(r) => onClose(r.symbol)} />
    </Panel>
  );
}

export function SinglesDrawer({ open, onClose, funds, cap }) {
  const singles = funds.filter((f) => f.single != null);
  return (
    <Panel open={open} onClose={onClose} title="Single stocks" sub={`Share of the desk in individual stocks. The cap is ${cap}%.`} crumbs={[{ label: 'Bridge', go: onClose }]}>
      {singles.length ? (
        <div className="rows">
          {singles.map((f) => (
            <button type="button" className="row row-btn" key={f.symbol} onClick={() => onClose(f.symbol)}>
              <span className="l">
                <span className="sym">
                  <i style={{ '--c': 'var(--s2)' }} />
                  {f.symbol}
                </span>
              </span>
              <span className="v">{f.single.toFixed(2)}%</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="empty-hint">No single stocks held.</p>
      )}
    </Panel>
  );
}

export function CashDrawer({ open, onClose, m, accounts }) {
  const pending = m.get('cash.pending');
  const days = val(m.get('cash.pending_days'));
  const debit = val(m.get('margin.debit'));
  return (
    <Panel open={open} onClose={onClose} title="Cash and margin" sub="Settled cash in core positions, deposits on their way, and anything borrowed." crumbs={[{ label: 'Bridge', go: onClose }]}>
      <div className="mini-kpis">
        <div>
          <small>Ready</small>
          <b>{usd(val(m.get('cash.ready')))}</b>
        </div>
        <div>
          <small>Pending</small>
          <b>{usd(val(pending))}</b>
        </div>
        <div>
          <small>Lands in</small>
          <b>{days == null ? '—' : plural(Math.round(days), 'day')}</b>
        </div>
      </div>
      {pending?.quality === 'modelled' ? (
        <span className="chip lilac" style={{ justifySelf: 'start' }}>
          Pending is modelled from the deposit schedule
        </span>
      ) : null}
      <p className="muted" style={{ fontSize: 12.5 }}>
        {debit ? `Margin balance ${usd(debit)}, costing about ${usd(val(m.get('margin.cost_month')) || 0)} a month.` : 'Nothing borrowed on margin.'}
      </p>
      <div className="tscroll">
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Account</th>
              <th scope="col" className="r">
                Cash
              </th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.account} className="still">
                <td>{accountLabel(a.account)}</td>
                <td className="r">{usd(a.cash)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

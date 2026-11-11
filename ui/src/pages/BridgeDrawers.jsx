import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Board } from '../components/Board.jsx';
import { Combo } from '../components/Combo.jsx';
import { DriftRows } from '../components/DriftRows.jsx';
import { Gauge } from '../components/Gauge.jsx';
import { Icon } from '../components/Icon.jsx';
import { LineChart } from '../components/LineChart.jsx';
import { Panel } from '../components/Panel.jsx';
import { Discounts } from '../research/Discounts.jsx';
import { accountLabel } from '../live/context.js';
import { useApi } from '../lib/api.js';
import { PERIODS, dayLabel, periodStart } from '../lib/charts.js';
import { val } from '../lib/metrics.js';
import { driftWords, referenceOf } from '../lib/plan.js';
import { QUALITY } from '../lib/quality.js';
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

// ---------- against the shadows ----------
function useSeries(scope, scopeId, start) {
  return useApi(`/api/engine/series?id=value&scope=${scope}&scope_id=${scopeId}${start ? `&start=${start}` : ''}`);
}

function ShadowChart({ lastDay }) {
  const [period, setPeriod] = useState('1Y');
  const start = periodStart(period, lastDay);
  const mine = useSeries('portfolio', 'all', start);
  const mix = useSeries('shadow', 'plan_shadow', start);
  const spx = useSeries('shadow', 'sp500_shadow', start);
  const chart = useMemo(() => {
    const rows = (mine.data?.rows || []).filter((r) => !start || r.date >= start);
    const x = rows.map((r) => r.date);
    const pick = (data) => {
      const map = new Map((data?.rows || []).map((r) => [r.date, r.value]));
      return x.map((d) => map.get(d) ?? null);
    };
    return {
      x,
      series: [
        { name: 'You', short: 'You', color: 'var(--s1)', values: rows.map((r) => r.value), width: 2.5 },
        { name: 'Safe mix shadow', short: 'Safe mix', color: 'var(--s3)', values: pick(mix.data) },
        { name: 'S&P 500 shadow', short: 'S&P 500', color: 'var(--s5)', values: pick(spx.data), dash: true },
      ],
    };
  }, [mine.data, mix.data, spx.data, start]);
  const q = [mine.data?.quality, mix.data?.quality].find((x) => x && x !== 'ok');
  const last = chart.x.length - 1;
  const gap = last >= 0 && chart.series[1].values[last] != null ? chart.series[0].values[last] - chart.series[1].values[last] : null;
  return (
    <div data-testid="shadow-chart">
      <div className="drawer-bar">
        <Combo label="Period" options={PERIODS} value={period} onChange={setPeriod} />
        {q ? <span className="chip lilac">{QUALITY[q] || q}</span> : null}
      </div>
      <p className="muted" style={{ fontSize: 12.5, margin: '6px 0 4px' }}>
        Same deposits on the same days, so the gap is choices, not cash.{gap != null ? ` You are ${usd(Math.abs(gap))} ${gap >= 0 ? 'ahead of' : 'behind'} the safe mix.` : ''}
      </p>
      {mine.loading && !mine.data ? <p className="empty-hint">Loading the value history…</p> : <LineChart label="Your value against the safe mix and S&P 500 shadows" height={210} x={chart.x} series={chart.series} fmtY={(v) => usd(v)} />}
    </div>
  );
}

export function ExcessDrawer({ open, onClose, m, lastDay }) {
  return (
    <Panel open={open} onClose={onClose} title="Against the shadows" sub="Your value minus a shadow that got the same deposits on the same days." crumbs={[{ label: 'Bridge', go: onClose }]}>
      <ShadowChart lastDay={lastDay} />
      <div className="tscroll">
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Window</th>
              <th scope="col" className="r">
                vs safe mix
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

// ---------- holdings ----------
export function HoldingsDrawer({ open, onClose, symbols, names, intraday, nav, accounts }) {
  return (
    <Panel open={open} onClose={onClose} kind="sheet" title="Holdings" sub={`${plural(symbols.length, 'holding')} across ${plural(accounts.length, 'account')}. Pick a row for its symbol sheet.`} crumbs={[{ label: 'Bridge', go: onClose }]}>
      <Board rows={symbols} names={names} intraday={intraday} nav={nav} onPick={(sym) => onClose(sym)} />
      <Link className="btn sm ghost" style={{ justifySelf: 'start' }} to="/portfolio" data-testid="to-portfolio">
        Open Portfolio
        <Icon name="right" />
      </Link>
    </Panel>
  );
}

// ---------- mix and instruments ----------
export function MixDrawer({ open, onClose, funds, limits, values, m, reference = referenceOf(null) }) {
  const drift = val(m.get('plan.drift_max'));
  const single = val(m.get('plan.single_stock'));
  const debit = val(m.get('margin.debit'));
  const cost = val(m.get('margin.cost_month'));
  const fi = val(m.get('fi.progress'));
  const band = limits.driftPts;
  const cap = limits.satelliteCap;
  const words = driftWords(reference, limits);
  const span = words.judged ? band * 2 : Math.max(band * 2, Math.ceil(((drift || 0) * 1.25) / 5) * 5);
  const inMix = funds.filter((f) => f.target != null);
  const singles = funds.filter((f) => f.single != null);
  return (
    <Panel open={open} onClose={onClose} title="Mix and instruments" sub={words.judged ? 'Each fund against its target, and the two dials the rules watch.' : `Each fund against ${reference.mix}, as a yardstick, and the single-stock dial the rules watch.`} crumbs={[{ label: 'Bridge', go: onClose }]}>
      <div className="gauges" data-testid="instruments">
        <Gauge
          label={words.label}
          unit="PTS"
          value={drift}
          min={0}
          max={span}
          zones={
            words.judged
              ? [
                  { from: 0, to: band * 0.6, color: 'var(--mint)' },
                  { from: band * 0.6, to: band, color: 'var(--mustard)' },
                  { from: band, to: band * 2, color: 'var(--coral)' },
                ]
              : [{ from: 0, to: span, color: 'var(--sky)' }]
          }
          reading={drift == null ? '—' : `${drift.toFixed(1)} pts`}
          note={words.line}
        />
        <Gauge
          label="Single stocks"
          unit="%"
          value={single}
          min={0}
          max={cap * 2}
          zones={[
            { from: 0, to: cap * 0.7, color: 'var(--mint)' },
            { from: cap * 0.7, to: cap, color: 'var(--mustard)' },
            { from: cap, to: cap * 2, color: 'var(--coral)' },
          ]}
          reading={single == null ? '—' : `${single.toFixed(1)}%`}
          note={`Cap ${cap}%`}
        />
      </div>
      <p className="muted instrument-line" style={{ marginTop: 0 }}>
        <Icon name="shield" />
        {debit ? `Margin ${usd(debit)}, about ${usd(cost || 0)} interest a month.` : 'No margin balance, so no call distance to watch.'}
        {fi != null ? ` FI progress ${fi.toFixed(1)}%.` : ''}
      </p>
      <span className="kicker">{words.rows}</span>
      {inMix.length ? <DriftRows rows={inMix} band={band} values={values} onPick={(r) => onClose(r.symbol)} judged={words.judged} target={words.target} gap={words.gap} /> : <p className="empty-hint">Targets show after the engine&apos;s first daily run.</p>}
      <span className="kicker">Single stocks</span>
      {singles.length ? (
        <div className="rows" data-testid="singles">
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

// ---------- discount days ----------
export function DiscountsDrawer({ open, onClose, api }) {
  const d = api.data;
  return (
    <Panel open={open} onClose={onClose} title="Discount days" sub={d?.as_of ? `After-close scan ${dayLabel(d.as_of)}${d.scanned ? ` · ${d.scanned} names` : ''}` : 'Names that fell hard, each with a research case.'} crumbs={[{ label: 'Bridge', go: onClose }]}>
      <Discounts api={api} plain onPick={(sym) => onClose(sym)} />
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

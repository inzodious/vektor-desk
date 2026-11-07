import { useMemo, useState } from 'react';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Kpi } from '../components/Kpi.jsx';
import { Board } from '../components/Board.jsx';
import { Combo } from '../components/Combo.jsx';
import { LineChart } from '../components/LineChart.jsx';
import { Spark } from '../components/Spark.jsx';
import { Panel } from '../components/Panel.jsx';
import { accountLabel, useLive, useSymbol } from '../live/context.js';
import { useApi } from '../lib/api.js';
import { PERIODS, dayLabel, periodStart } from '../lib/charts.js';
import { QUALITY } from '../lib/quality.js';
import { etTime, pct, plural, usd } from '../lib/format.js';

const STATE_WORD = { open: 'Market open', pre: 'Pre-market', after: 'After hours', closed: 'Market closed' };

function useAccounts(live) {
  return useMemo(() => {
    const map = new Map();
    (live?.rows || []).forEach((r) => {
      const a = map.get(r.account) || { account: r.account, value: 0, day_change: 0, cash: 0 };
      a.value += r.value || 0;
      a.day_change += r.day_change || 0;
      if (r.source === 'cash') a.cash += r.value || 0;
      map.set(r.account, a);
    });
    return [...map.values()].sort((a, b) => b.value - a.value);
  }, [live]);
}

// ---------- value trend ----------
function ValueTrend({ accounts, lastDay }) {
  const [period, setPeriod] = useState('1Y');
  const [account, setAccount] = useState('all');
  const start = periodStart(period, lastDay);
  const q = new URLSearchParams();
  if (start) q.set('start', start);
  if (account !== 'all') q.set('account', account);
  const api = useApi(`/api/engine/value${q.toString() ? `?${q}` : ''}`);
  const series = useMemo(() => api.data?.series || [], [api.data]);
  const modelled = series.filter((p) => p.quality && p.quality !== 'ok').length;
  const first = series[0]?.value;
  const last = series[series.length - 1]?.value;
  const opts = useMemo(() => [{ v: 'all', t: 'All accounts' }, ...accounts.map((a) => ({ v: a.account, t: accountLabel(a.account) }))], [accounts]);
  return (
    <div className="card c12" style={{ '--i': 6 }}>
      <div className="card-head">
        <span className="tag">Value over time</span>
        <span className="acts">
          <Combo label="Account" options={opts} value={account} onChange={setAccount} />
          <Combo label="Period" options={PERIODS} value={period} onChange={setPeriod} />
        </span>
      </div>
      {series.length > 1 ? (
        <p className="muted" style={{ fontSize: 12.5, marginBottom: 6 }}>
          {usd(last)} now, {usd(last - first, { sign: true })} since {dayLabel(series[0].date, true)}. Deposits count as growth here; the plan shadow lands in phase 3.
          {modelled ? <span className="chip lilac" style={{ marginLeft: 6 }}>{QUALITY.pro_forma} on {plural(modelled, 'day')}</span> : null}
        </p>
      ) : null}
      {api.loading && !api.data ? (
        <p className="empty-hint">Loading the value history…</p>
      ) : (
        <LineChart label="Portfolio value over time" height={260} x={series.map((p) => p.date)} series={[{ name: 'Value', color: 'var(--s1)', values: series.map((p) => p.value) }]} fmtY={(v) => usd(v)} tipHint={modelled ? 'Days between snapshots are rolled forward from prices' : undefined} />
      )}
    </div>
  );
}

// ---------- drill drawers ----------
function AccountsDrawer({ open, onClose, accounts, total }) {
  return (
    <Panel open={open} onClose={onClose} title="Market value" sub="Split by account, from the latest holdings and quotes." crumbs={[{ label: 'Bridge', go: onClose }]}>
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
                <td className={`r ${a.day_change >= 0 ? 'up' : 'dn'}`}>{usd(a.day_change, { sign: true })}</td>
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
    </Panel>
  );
}

function MoversDrawer({ open, onClose, symbols }) {
  const rows = [...symbols].sort((a, b) => Math.abs(b.day_change) - Math.abs(a.day_change));
  return (
    <Panel open={open} onClose={onClose} title="Today" sub="Each holding's share of today's move. Pick a row for its symbol sheet." crumbs={[{ label: 'Bridge', go: onClose }]}>
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
              <span className={r.day_change >= 0 ? 'up' : 'dn'}>{usd(r.day_change, { sign: true })}</span>
              <small>{r.change_pct == null ? '—' : pct(r.change_pct, 2, true)}</small>
            </span>
          </button>
        ))}
      </div>
    </Panel>
  );
}

// ---------- page ----------
export default function Bridge() {
  const ctx = useLive();
  const { openSymbol } = useSymbol();
  const live = ctx.live;
  const accounts = useAccounts(live);
  const spark = useApi('/api/engine/value');
  const [drill, setDrill] = useState(null);
  const sparkVals = useMemo(() => (spark.data?.series || []).slice(-30).map((p) => p.value), [spark.data]);

  if (ctx.loading) {
    return <Hero kicker="Bridge" title="Bridge" art="bridge" big={<b>Checking…</b>} foot={<span className="chip">Reading the latest holdings</span>} />;
  }

  if (!live) {
    return (
      <>
        <Hero kicker="Bridge" title="Bridge" art="bridge" big={<b>No answer</b>} foot={<span className="chip watch">Desk API offline</span>} />
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button className="btn sm" type="button" onClick={ctx.reload}>
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">Live holdings come back as soon as it does.</p>
        </section>
      </>
    );
  }

  if (!live.rows?.length) {
    return (
      <>
        <Hero kicker="Bridge" title="Bridge" art="bridge" big={<b>Waiting on holdings</b>} foot={<span className="chip info">No holdings yet</span>} />
        <section className="card soon">
          <span className="desk-ico">
            <Icon name="bridge" />
          </span>
          <div>
            <b style={{ color: 'var(--ink)' }}>The engine hasn&apos;t built holdings yet</b>
            <p className="muted" style={{ fontSize: 12.5 }}>
              It runs after the next mirror pull. Settings shows when that was.
            </p>
          </div>
        </section>
      </>
    );
  }

  const up = live.day_change >= 0;
  const trading = ['pre', 'open', 'after'].includes(live.state);
  const moved = ctx.symbols.some((r) => Math.abs(r.day_change) >= 0.5);
  const asOf = live.as_of ? `${etTime(new Date(live.as_of))} ET` : live.holdings_date ? `close ${dayLabel(live.holdings_date)}` : null;
  const q = live.quality && live.quality !== 'ok' ? QUALITY[live.quality] : null;
  const mover = [...ctx.symbols].sort((a, b) => Math.abs(b.day_change) - Math.abs(a.day_change))[0];
  const closeDrill = (sym) => {
    setDrill(null);
    if (typeof sym === 'string') openSymbol?.(sym);
  };

  return (
    <>
      <Hero
        kicker={`Bridge · ${STATE_WORD[live.state] || 'Market'}${asOf ? ` · ${asOf}` : ''}`}
        title="Bridge"
        art="bridge"
        big={
          <>
            <b>{usd(live.value)}</b>
            {trading || moved ? (
              <span className={up ? 'up' : 'dn'}>
                {usd(live.day_change, { sign: true })}
                {live.day_change_pct != null ? ` · ${pct(live.day_change_pct / 100, 2, true)}` : ''} today
              </span>
            ) : (
              <span className="muted">at the last close</span>
            )}
          </>
        }
        foot={
          <>
            {q ? <span className="chip lilac">{q}</span> : null}
            <span className="chip">Holdings {live.holdings_date ? dayLabel(live.holdings_date) : '—'}</span>
            <span className="chip">{plural(ctx.symbols.length, 'fund')} · {plural(accounts.length, 'account')}</span>
          </>
        }
      />
      <section className="kpis kpis-4">
        <Kpi i={1} label="Market value" metric="value.market" value={usd(live.value)} line={`${plural(accounts.length, 'account')}`} asOf={asOf} quality={live.quality} spark={sparkVals.length > 1 ? <Spark values={sparkVals} label="Last 30 days" /> : null} onOpen={() => setDrill('value')} />
        <Kpi i={2} label="Today" metric="value.day_change" value={trading || moved ? usd(live.day_change, { sign: true }) : 'Closed'} tone={trading || moved ? (up ? 'ok' : 'watch') : undefined} line={trading || moved ? (live.day_change_pct != null ? pct(live.day_change_pct / 100, 2, true) : 'No move yet') : 'Moves show when trading opens'} asOf={trading || moved ? asOf : null} quality={live.quality} onOpen={() => setDrill('today')} />
        <Kpi i={3} label="Cash ready" metric="cash.ready" value={usd(ctx.cash)} line={live.value ? `${pct(ctx.cash / live.value)} of the desk` : ''} asOf={asOf} onOpen={() => setDrill('value')} />
        <Kpi i={4} label="Biggest mover" metric="value.day_change" value={moved && mover ? mover.symbol : '—'} line={moved && mover ? `${usd(mover.day_change, { sign: true })} today` : 'Nothing has moved yet'} onOpen={() => setDrill('today')} />
      </section>
      <section className="grid">
        <div className="card c12" style={{ '--i': 5 }}>
          <div className="card-head">
            <span className="tag mustard">Departures board</span>
            <span className="acts">
              <span className="muted" style={{ fontSize: 12 }}>
                Pick a row for its symbol sheet
              </span>
            </span>
          </div>
          <Board rows={ctx.symbols} names={ctx.names} intraday={ctx.intraday} nav={['pre', 'open', 'after'].includes(live.state)} />
        </div>
        <ValueTrend accounts={accounts} lastDay={live.holdings_date} />
      </section>
      <AccountsDrawer open={drill === 'value'} onClose={closeDrill} accounts={accounts} total={live.value} />
      <MoversDrawer open={drill === 'today'} onClose={closeDrill} symbols={ctx.symbols} />
    </>
  );
}

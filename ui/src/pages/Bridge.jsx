import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Kpi } from '../components/Kpi.jsx';
import { Board } from '../components/Board.jsx';
import { Combo } from '../components/Combo.jsx';
import { LineChart } from '../components/LineChart.jsx';
import { Spark } from '../components/Spark.jsx';
import { Gauge } from '../components/Gauge.jsx';
import { DriftRows } from '../components/DriftRows.jsx';
import { QueueCard } from '../decisions/QueueCard.jsx';
import { BriefCard } from '../agents/BriefCard.jsx';
import { Discounts } from '../research/Discounts.jsx';
import { TodayRun } from '../components/TodayRun.jsx';
import { CashDrawer, DriftDrawer, ExcessDrawer, SinglesDrawer, ValueDrawer } from './BridgeDrawers.jsx';
import { LIVE_STATES, useLive, useSymbol } from '../live/context.js';
import { useApi } from '../lib/api.js';
import { fundsFromMetrics, useMetrics, val } from '../lib/metrics.js';
import { usePlanLimits } from '../lib/plan.js';
import { PERIODS, dayLabel, periodStart } from '../lib/charts.js';
import { QUALITY } from '../lib/quality.js';
import { etTime, pct, plural, usd } from '../lib/format.js';

const STATE_WORD = { open: 'Market open', pre: 'Pre-market', after: 'After hours', closed: 'Market closed' };
const HEAD_IDS = 'value.market,value.day_change,bm.excess,plan.drift_max,plan.single_stock,margin.debit,margin.cost_month,cash.ready,cash.pending,cash.pending_days,fi.progress';

const fmtPts = (v) => (v == null ? '—' : `${v.toFixed(1)}`);

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

// ---------- value versus the plan ----------
function useSeries(scope, scopeId, start) {
  return useApi(`/api/engine/series?id=value&scope=${scope}&scope_id=${scopeId}${start ? `&start=${start}` : ''}`);
}

function ValueVsPlan({ lastDay }) {
  const [period, setPeriod] = useState('1Y');
  const start = periodStart(period, lastDay);
  const mine = useSeries('portfolio', 'all', start);
  const plan = useSeries('shadow', 'plan_shadow', start);
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
        { name: 'Plan shadow', short: 'Plan', color: 'var(--s3)', values: pick(plan.data) },
        { name: 'S&P 500 shadow', short: 'S&P 500', color: 'var(--s5)', values: pick(spx.data), dash: true },
      ],
    };
  }, [mine.data, plan.data, spx.data, start]);
  const q = [mine.data?.quality, plan.data?.quality].find((x) => x && x !== 'ok');
  const last = chart.x.length - 1;
  const gap = last >= 0 && chart.series[1].values[last] != null ? chart.series[0].values[last] - chart.series[1].values[last] : null;
  return (
    <div className="card c8" style={{ '--i': 8 }}>
      <div className="card-head">
        <span className="tag">Value versus the plan</span>
        <span className="acts">
          {q ? <span className="chip lilac">{QUALITY[q] || q}</span> : null}
          <Combo label="Period" options={PERIODS} value={period} onChange={setPeriod} />
        </span>
      </div>
      <p className="muted" style={{ fontSize: 12.5, marginBottom: 4 }}>
        Same deposits on the same days, so the gap is choices, not cash.{gap != null ? ` You are ${usd(Math.abs(gap))} ${gap >= 0 ? 'ahead of' : 'behind'} the plan.` : ''}
      </p>
      {mine.loading && !mine.data ? <p className="empty-hint">Loading the value history…</p> : <LineChart label="Your value against the plan and S&P 500 shadows" height={250} x={chart.x} series={chart.series} fmtY={(v) => usd(v)} endLabels />}
    </div>
  );
}

// ---------- instruments ----------
function Instruments({ m, limits, onDrift, onSingles }) {
  const drift = val(m.get('plan.drift_max'));
  const single = val(m.get('plan.single_stock'));
  const debit = val(m.get('margin.debit'));
  const cost = val(m.get('margin.cost_month'));
  const band = limits.driftPts;
  const cap = limits.satelliteCap;
  return (
    <div className="card c4" style={{ '--i': 9 }}>
      <div className="card-head">
        <span className="tag coral">Instruments</span>
      </div>
      <div className="gauges">
        <Gauge
          label="Largest drift"
          unit="PTS"
          value={drift}
          min={0}
          max={band * 2}
          zones={[
            { from: 0, to: band * 0.6, color: 'var(--mint)' },
            { from: band * 0.6, to: band, color: 'var(--mustard)' },
            { from: band, to: band * 2, color: 'var(--coral)' },
          ]}
          reading={drift == null ? '—' : `${fmtPts(drift)} pts`}
          note={`Rebalance at ${band}`}
          onOpen={onDrift}
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
          onOpen={onSingles}
        />
      </div>
      <p className="muted instrument-line">
        <Icon name="shield" />
        {debit ? `Margin ${usd(debit)}, about ${usd(cost || 0)} interest a month.` : 'No margin balance, so no call distance to watch.'}
      </p>
    </div>
  );
}

// ---------- page ----------
export default function Bridge() {
  const ctx = useLive();
  const { openSymbol } = useSymbol();
  const live = ctx.live;
  const accounts = useAccounts(live);
  const m = useMetrics(HEAD_IDS);
  const plan = useMetrics('plan.*', 'scope=holding');
  const limits = usePlanLimits();
  const spark = useApi('/api/engine/value');
  const [drill, setDrill] = useState(null);
  const queue = useApi('/api/decisions/queue', { every: 120000 });
  const brief = useApi('/api/agents/brief', { every: 600000 });
  const sparkVals = useMemo(() => (spark.data?.series || []).slice(-30).map((p) => p.value), [spark.data]);
  const funds = useMemo(() => fundsFromMetrics(plan.rows), [plan.rows]);
  const values = useMemo(() => Object.fromEntries(ctx.symbols.map((s) => [s.symbol, s.value])), [ctx.symbols]);

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
  const trading = LIVE_STATES.includes(live.state);
  const showMove = trading || ctx.symbols.some((r) => Math.abs(r.day_change) >= 0.5);
  const asOf = live.as_of ? `${etTime(new Date(live.as_of))} ET` : live.holdings_date ? `close ${dayLabel(live.holdings_date)}` : null;
  const engineAsOf = m.asOf ? `engine ${dayLabel(m.asOf)}` : null;
  const q = live.quality && live.quality !== 'ok' ? QUALITY[live.quality] : null;
  const closeDrill = (sym) => {
    setDrill(null);
    if (typeof sym === 'string') openSymbol(sym);
  };

  const ex = m.get('bm.excess', { scope: 'shadow', scopeId: 'plan_shadow', window: 'YTD' });
  const exSpx = m.get('bm.excess', { scope: 'shadow', scopeId: 'sp500_shadow', window: 'YTD' });
  const drift = m.get('plan.drift_max');
  const worst = funds.filter((f) => f.drift != null).sort((a, b) => Math.abs(b.drift) - Math.abs(a.drift))[0];
  const single = m.get('plan.single_stock');
  const debit = m.get('margin.debit');
  const marginCost = val(m.get('margin.cost_month'));
  const cash = m.get('cash.ready');
  const pending = m.get('cash.pending');
  const fi = m.get('fi.progress');
  const exV = val(ex);
  const exS = val(exSpx);
  const driftV = val(drift);
  const singleV = val(single);
  const fiV = val(fi);

  return (
    <>
      <Hero
        kicker={`Bridge · ${STATE_WORD[live.state] || 'Market'}${asOf ? ` · ${asOf}` : ''}`}
        title="Bridge"
        art="bridge"
        big={
          <>
            <b>{usd(live.value)}</b>
            {showMove ? (
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
            {worst ? (
              <button type="button" className={`chip chip-btn ${Math.abs(worst.drift) >= limits.driftPts ? 'watch' : ''}`} onClick={() => setDrill('drift')}>
                Largest drift {worst.symbol} {worst.drift > 0 ? '+' : '−'}
                {Math.abs(worst.drift).toFixed(1)} pts
              </button>
            ) : null}
            <span className="chip">
              {plural(ctx.symbols.length, 'fund')} · {plural(accounts.length, 'account')}
            </span>
            {queue.data?.count ? (
              <Link className="btn sm" to="/decisions">
                <Icon name="check" />
                Clear the queue · {queue.data.count}
              </Link>
            ) : null}
            <Link className="btn sm ghost" to="/results/day" data-testid="results-link">
              <Icon name="flag" />
              Results
            </Link>
          </>
        }
      />
      <section className="kpis kpis-7">
        <Kpi i={1} label="Market value" metric="value.market" value={usd(live.value)} line={showMove ? `${usd(live.day_change, { sign: true })} today` : 'At the last close'} asOf={asOf} quality={live.quality} spark={sparkVals.length > 1 ? <Spark values={sparkVals} label="Last 30 days" /> : null} onOpen={() => setDrill('value')} />
        <Kpi i={2} label="Vs the plan" metric="bm.excess" value={exV == null ? '—' : usd(exV, { sign: true })} tone={exV == null ? undefined : exV >= 0 ? 'ok' : 'watch'} line={exS == null ? 'Year to date' : `YTD · S&P ${usd(exS, { sign: true })}`} quality={ex?.quality} asOf={engineAsOf} onOpen={() => setDrill('excess')} />
        <Kpi i={3} label="Largest drift" metric="plan.drift_max" value={driftV == null ? '—' : fmtPts(driftV)} unit="pts" tone={driftV != null && driftV >= limits.driftPts ? 'watch' : undefined} line={`Rebalance at ${limits.driftPts}`} quality={drift?.quality} asOf={engineAsOf} onOpen={() => setDrill('drift')} />
        <Kpi i={4} label="Single stocks" metric="plan.single_stock" value={singleV == null ? '—' : singleV.toFixed(1)} unit="%" tone={singleV != null && singleV >= limits.satelliteCap ? 'watch' : undefined} line={`Cap ${limits.satelliteCap}%`} quality={single?.quality} asOf={engineAsOf} onOpen={() => setDrill('singles')} />
        <Kpi i={5} label="Margin" metric="margin.debit" value={usd(val(debit) ?? 0)} line={val(debit) ? `${usd(marginCost || 0)} a month` : 'Nothing borrowed'} quality={debit?.quality} asOf={engineAsOf} cream={!!val(debit)} onOpen={() => setDrill('cash')} />
        <Kpi i={6} label="Cash ready" metric="cash.ready" value={usd(val(cash) ?? ctx.cash)} line={val(pending) ? `+${usd(val(pending))} on the way` : 'Nothing pending'} quality={pending?.quality === 'modelled' ? 'modelled' : cash?.quality} asOf={engineAsOf} onOpen={() => setDrill('cash')} />
        <Kpi i={7} label="FI progress" metric="fi.progress" value={fiV == null ? 'Not yet' : fiV.toFixed(1)} unit={fiV == null ? undefined : '%'} line={fiV == null ? 'Needs the FI path' : 'of the FI number'} quality={fiV == null ? undefined : fi?.quality} asOf={fiV == null ? null : engineAsOf} />
      </section>
      <section className="grid">
        <TodayRun i={7} />
        <BriefCard brief={brief} i={7} />
        <QueueCard queue={queue} i={7} span="c8" />
        <Discounts i={7} />
        <div className="card c12" style={{ '--i': 7 }}>
          <div className="card-head">
            <span className="tag mustard">Departures board</span>
            <span className="acts">
              <span className="muted" style={{ fontSize: 12 }}>
                Pick a row for its symbol sheet
              </span>
            </span>
          </div>
          <Board rows={ctx.symbols} names={ctx.names} intraday={ctx.intraday} nav={trading} />
        </div>
        <ValueVsPlan lastDay={live.holdings_date || m.asOf} />
        <Instruments m={m} limits={limits} onDrift={() => setDrill('drift')} onSingles={() => setDrill('singles')} />
        <div className="card c12" style={{ '--i': 10 }}>
          <div className="card-head">
            <span className="tag mint">Mix</span>
            <span className="acts">
              <span className="chip">{plural(funds.filter((f) => f.target != null).length, 'plan fund')}</span>
            </span>
          </div>
          {funds.length ? <DriftRows rows={funds.filter((f) => f.target != null)} band={limits.driftPts} values={values} /> : <p className="empty-hint">The plan mix shows after the engine&apos;s first daily run.</p>}
        </div>
      </section>
      <ValueDrawer open={drill === 'value'} onClose={closeDrill} accounts={accounts} total={live.value} symbols={ctx.symbols} />
      <ExcessDrawer open={drill === 'excess'} onClose={closeDrill} m={m} />
      <DriftDrawer open={drill === 'drift'} onClose={closeDrill} funds={funds} band={limits.driftPts} values={values} />
      <SinglesDrawer open={drill === 'singles'} onClose={closeDrill} funds={funds} cap={limits.satelliteCap} />
      <CashDrawer open={drill === 'cash'} onClose={closeDrill} m={m} accounts={accounts} />
    </>
  );
}

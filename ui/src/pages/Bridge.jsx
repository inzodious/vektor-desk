import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Kpi } from '../components/Kpi.jsx';
import { Spark } from '../components/Spark.jsx';
import { BriefCard } from '../agents/BriefCard.jsx';
import { TodayRun } from '../components/TodayRun.jsx';
import { StepsDue } from './BridgeSteps.jsx';
import { CashDrawer, DiscountsDrawer, ExcessDrawer, HoldingsDrawer, MixDrawer, ValueDrawer } from './BridgeDrawers.jsx';
import { LIVE_STATES, useLive, useSymbol } from '../live/context.js';
import { useApi } from '../lib/api.js';
import { fundsFromMetrics, useMetrics, val } from '../lib/metrics.js';
import { driftTone, usePlanLimits, useReference } from '../lib/plan.js';
import { dayLabel } from '../lib/charts.js';
import { dayStamp, useAsOf } from '../lib/asof.js';
import { movers } from '../lib/bridge.js';
import { QUALITY } from '../lib/quality.js';
import { etTime, pct, usd } from '../lib/format.js';
import { EmptyState } from '../start/EmptyState.jsx';
import { FIRST_RUN } from '../lib/start.js';

const STATE_WORD = { open: 'Market open', pre: 'Pre-market', after: 'After hours', closed: 'Market closed' };
const HEAD_IDS = 'value.market,value.day_change,bm.excess,plan.drift_max,plan.single_stock,margin.debit,margin.cost_month,cash.ready,cash.pending,cash.pending_days,fi.progress';


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

// ---------- page ----------
export default function Bridge() {
  const ctx = useLive();
  const clock = useAsOf();
  const { openSymbol } = useSymbol();
  const live = ctx.live;
  const accounts = useAccounts(live);
  const m = useMetrics(HEAD_IDS);
  const plan = useMetrics('plan.*', 'scope=holding');
  const limits = usePlanLimits();
  const reference = useReference();
  const spark = useApi('/api/engine/value');
  const [drill, setDrill] = useState(null);
  const queue = useApi('/api/decisions/queue', { every: 120000 });
  const brief = useApi('/api/agents/brief', { every: 600000 });
  const steps = useApi('/api/decisions/plan-steps?days=14');
  const discounts = useApi('/api/engine/discounts');
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
        <EmptyState k="bridge.value" card icon="bridge" title="No holdings to show yet" why="They arrive with the first account pull and the numbers that follow it." action={FIRST_RUN} />
      </>
    );
  }

  const trading = LIVE_STATES.includes(live.state);
  const head = clock?.headline || { value: live.value, change: live.day_change, pct: live.day_change_pct, when: 'today', live: true };
  const up = head.change >= 0;
  const showMove = clock?.headline ? head.change != null : trading || ctx.symbols.some((r) => Math.abs(r.day_change) >= 0.5);
  const liveAt = live.as_of ? `${etTime(new Date(live.as_of))} ET` : live.holdings_date ? `close ${dayLabel(live.holdings_date)}` : null;
  const asOf = clock ? null : liveAt;
  const kick = clock?.liveWords || [STATE_WORD[live.state] || 'Market', asOf].filter(Boolean).join(' · ');
  const engineAsOf = dayStamp(m.asOf, clock);
  const n = clock?.numbers || null;
  const q = live.quality && live.quality !== 'ok' ? QUALITY[live.quality] : null;
  const closeDrill = (sym) => {
    setDrill(null);
    if (typeof sym === 'string') openSymbol(sym);
  };

  const ex = m.get('bm.excess', { scope: 'shadow', scopeId: 'plan_shadow', window: 'YTD' });
  const exSpx = m.get('bm.excess', { scope: 'shadow', scopeId: 'sp500_shadow', window: 'YTD' });
  const worst = funds.filter((f) => f.drift != null).sort((a, b) => Math.abs(b.drift) - Math.abs(a.drift))[0];
  const debit = m.get('margin.debit');
  const debitV = n ? n.margin_debit || 0 : (val(debit) ?? 0);
  const marginCost = n ? n.margin_cost_month : val(m.get('margin.cost_month'));
  const cash = m.get('cash.ready');
  const pending = m.get('cash.pending');
  const cashV = n ? n.cash_ready : (val(cash) ?? ctx.cash);
  const pendingV = n ? n.cash_pending : val(pending);
  const bookAsOf = n ? null : engineAsOf;
  const exV = val(ex);
  const exS = val(exSpx);
  const moved = showMove && head.live ? movers(ctx.symbols) : [];
  const sale = discounts.data?.rows?.length || 0;
  const hasDiscounts = discounts.error?.status !== 404;

  return (
    <>
      <Hero
        kicker={`Bridge · ${kick}`}
        title="Bridge"
        art="bridge"
        big={
          <>
            <b data-testid="bridge-value">{usd(head.value)}</b>
            {showMove ? (
              <span className={up ? 'up' : 'dn'} data-testid="bridge-change">
                {usd(head.change, { sign: true })}
                {head.pct != null ? ` · ${pct(head.pct / 100, 2, true)}` : ''} {head.when}
              </span>
            ) : (
              <span className="muted">at the last close</span>
            )}
          </>
        }
        foot={
          <>
            {q ? <span className="chip lilac">{q}</span> : null}
            {queue.data?.count ? (
              <Link className="btn sm" to="/decisions">
                <Icon name="check" />
                Clear the queue · {queue.data.count}
              </Link>
            ) : null}
            <button type="button" className="btn sm ghost" onClick={() => setDrill('holdings')} data-testid="open-holdings">
              <Icon name="layers" />
              Holdings · {ctx.symbols.length}
            </button>
            <button type="button" className={`btn sm ghost${worst && driftTone(reference, worst.drift, limits) ? ' heads-up' : ''}`} onClick={() => setDrill('mix')} data-testid="open-mix">
              <Icon name="gauge" />
              {worst ? `Mix · ${worst.symbol} ${worst.drift > 0 ? '+' : '−'}${Math.abs(worst.drift).toFixed(1)} pts` : 'Mix'}
            </button>
            {hasDiscounts ? (
              <button type="button" className="btn sm ghost" onClick={() => setDrill('discounts')} data-testid="open-discounts">
                <Icon name="bolt" />
                {sale ? `Discounts · ${sale}` : 'Discounts'}
              </button>
            ) : null}
          </>
        }
      />
      <section className="kpis kpis-4" data-testid="bridge-kpis">
        <Kpi i={1} label="Market value" metric="value.market" value={usd(head.value)} line={showMove ? `${usd(head.change, { sign: true })} ${head.when}` : 'At the last close'} asOf={asOf} quality={live.quality} spark={sparkVals.length > 1 ? <Spark values={sparkVals} label="Last 30 days" /> : null} onOpen={() => setDrill('value')} />
        <Kpi i={2} label="Vs the safe mix" metric="bm.excess" value={exV == null ? '—' : usd(exV, { sign: true })} tone={exV == null ? undefined : exV >= 0 ? 'ok' : 'watch'} line={exS == null ? 'Year to date' : `YTD · S&P ${usd(exS, { sign: true })}`} quality={ex?.quality} asOf={engineAsOf} onOpen={() => setDrill('excess')} />
        <Kpi i={3} label="Cash ready" metric="cash.ready" value={usd(cashV)} line={pendingV ? `+${usd(pendingV)} on the way` : 'Nothing pending'} quality={pending?.quality === 'modelled' ? 'modelled' : cash?.quality} asOf={bookAsOf} onOpen={() => setDrill('cash')} />
        <Kpi i={4} label="Margin" metric="margin.debit" value={usd(debitV)} line={debitV ? `${usd(marginCost || 0)} a month` : 'Nothing borrowed'} quality={debit?.quality} asOf={bookAsOf} cream={!!debitV} onOpen={() => setDrill('cash')} />
      </section>
      <section className="grid">
        <TodayRun i={5} />
        <BriefCard brief={brief} i={6} tag="What changed" span="c5">
          {moved.length ? (
            <div className="movers" data-testid="movers">
              <span className="kicker">Movers today</span>
              {moved.map((r) => (
                <button type="button" className="chip chip-btn" key={r.symbol} data-sym={r.symbol}>
                  {r.symbol} <span className={r.day_change >= 0 ? 'up' : 'dn'}>{pct(r.change_pct, 2, true)}</span>
                </button>
              ))}
            </div>
          ) : null}
        </BriefCard>
        <StepsDue queue={queue} steps={steps} i={6} span="c7" />
      </section>
      <ValueDrawer open={drill === 'value'} onClose={closeDrill} accounts={accounts} total={live.value} symbols={ctx.symbols} />
      <ExcessDrawer open={drill === 'excess'} onClose={closeDrill} m={m} lastDay={live.holdings_date || m.asOf} />
      <HoldingsDrawer open={drill === 'holdings'} onClose={closeDrill} symbols={ctx.symbols} names={ctx.names} intraday={ctx.intraday} nav={trading} accounts={accounts} />
      <MixDrawer open={drill === 'mix'} onClose={closeDrill} funds={funds} limits={limits} values={values} m={m} reference={reference} />
      <DiscountsDrawer open={drill === 'discounts'} onClose={closeDrill} api={discounts} />
      <CashDrawer open={drill === 'cash'} onClose={closeDrill} m={m} accounts={accounts} />
    </>
  );
}

import { useSearchParams } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { PORTFOLIO_TABS } from '../lib/areas.js';
import { planCards, plansHead } from '../lib/stockPlans.js';
import { BareCard, PlanCard } from '../plan/PlanCard.jsx';
import { EmptyState, GapNote } from '../start/EmptyState.jsx';

export default function StockPlans() {
  const plans = useApi('/api/decisions/plans');
  const facts = useApi('/api/engine/planfacts');
  const [params] = useSearchParams();
  const focus = (params.get('symbol') || '').toUpperCase();
  const tabs = <Subtabs label="Portfolio views" tabs={PORTFOLIO_TABS} />;
  const d = plans.data;

  if (!d && plans.loading) return <Hero kicker="Portfolio · Stock plans" title="Stock plans" art="plan" big={<b>Checking…</b>} foot={tabs} />;

  if (!d) {
    const missing = plans.error?.status === 404;
    return (
      <>
        <Hero kicker="Portfolio · Stock plans" title="Stock plans" art="plan" big={<b>{missing ? 'Not yet' : 'No answer'}</b>} foot={tabs} />
        {missing ? (
          <section className="card soon" data-testid="plans-soon">
            <p className="muted">Stock plans switch on with the next desk update.</p>
          </section>
        ) : (
          <section className="card" role="alert">
            <div className="card-head">
              <span className="tag coral">The desk API didn&apos;t answer</span>
              <button className="btn sm" type="button" onClick={plans.reload}>
                <Icon name="swap" />
                Retry
              </button>
            </div>
            <p className="muted">Your plans come back as soon as it does.</p>
          </section>
        )}
      </>
    );
  }

  const { cards, bare } = planCards(d, facts.data);
  const head = plansHead(d, facts.data);
  const reload = () => {
    plans.reload();
    facts.reload();
  };

  return (
    <>
      <Hero
        kicker="Portfolio · Stock plans"
        title="Stock plans"
        art="plan"
        big={
          <>
            <b data-testid="plans-count">{head.big}</b>
            <span className="muted">{head.sub}</span>
          </>
        }
        foot={tabs}
        chips={facts.data?.as_of ? <span className="chip">Prices as of {dayLabel(facts.data.as_of)}</span> : null}
      />
      <section className="grid" data-testid="stock-plans" data-count={cards.length}>
        {!cards.length ? (
          <div className="card c12 es-card" style={{ '--i': 1 }} data-testid="plans-first">
            <EmptyState k="portfolio.stock_plans" icon="pin" title="No plans yet" why="The Plan desk writes a draft for each holding on its next run, weekdays at 6:40 PM.">
              <small>Nothing is in force until you approve it. You can also write one below right now.</small>
            </EmptyState>
          </div>
        ) : (
          <div className="c12 sp-gap">
            <GapNote k="portfolio.stock_plans" />
          </div>
        )}
        {cards.map((card, n) => (
          <PlanCard key={card.symbol} card={card} meta={d} focus={focus === card.symbol} i={n + 1} onChanged={reload} />
        ))}
        <BareCard rows={bare} i={cards.length + 2} onChanged={reload} />
      </section>
    </>
  );
}

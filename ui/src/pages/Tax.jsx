import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Kpi } from '../components/Kpi.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { TaxCalendar } from '../components/TaxCalendar.jsx';
import { Link } from 'react-router-dom';
import { PORTFOLIO_TABS } from '../lib/areas.js';
import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { plural, usd } from '../lib/format.js';
import { useMetrics, val } from '../lib/metrics.js';
import { mergeWindows, todayEt } from '../lib/tax.js';

const CELLS = [
  { id: 'tax.realized_st', window: 'YTD', label: 'Realized short term' },
  { id: 'tax.realized_lt', window: 'YTD', label: 'Realized long term' },
  { id: 'tax.unrealized_st', window: 'now', label: 'Unrealized short term' },
  { id: 'tax.unrealized_lt', window: 'now', label: 'Unrealized long term' },
];

// ---------- page ----------
export default function Tax() {
  const m = useMetrics('tax.*');
  const calendar = useApi('/api/decisions/calendar');
  const wash = useApi('/api/engine/wash');
  const tabs = <Subtabs label="Portfolio views" tabs={PORTFOLIO_TABS} />;
  const harvest = m.get('tax.harvestable');
  const harvestV = val(harvest);
  const engineAsOf = m.asOf ? `engine ${dayLabel(m.asOf)}` : null;
  const events = (calendar.data?.events || []).filter((e) => !e.kind || e.kind === 'tax');
  const windows = wash.data?.windows || [];
  const open = mergeWindows(windows).length;

  if (m.loading) return <Hero kicker="Portfolio · Tax" title="Tax" art="plan" big={<b>Checking…</b>} foot={tabs} />;

  if (m.error && calendar.error && wash.error) {
    return (
      <>
        <Hero kicker="Portfolio · Tax" title="Tax" art="plan" big={<b>No answer</b>} foot={tabs} />
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button
              className="btn sm"
              type="button"
              onClick={() => {
                m.reload();
                calendar.reload();
                wash.reload();
              }}
            >
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">The tax numbers come back as soon as it does.</p>
        </section>
      </>
    );
  }

  return (
    <>
      <Hero
        kicker="Portfolio · Tax"
        title="Tax"
        art="plan"
        big={
          <>
            <b>{harvestV == null ? 'Not yet' : usd(harvestV)}</b>
            <span className="muted">{harvestV == null ? 'harvestable losses need a lot export' : 'in losses past your harvest threshold'}</span>
          </>
        }
        foot={
          <>
            {tabs}
            <span className={`chip${open ? ' watch' : ''}`} data-testid="wash-open">{open ? `${plural(open, 'wash window')} open` : 'No wash windows open'}</span>
          </>
        }
      />
      <section className="kpis kpis-4">
        {CELLS.map((c, i) => {
          const row = m.get(c.id, { window: c.window });
          const v = val(row);
          return <Kpi key={c.id} i={i + 1} label={c.label} metric={c.id} value={v == null ? '—' : usd(v, { sign: true })} line={v == null ? 'Needs a lot export' : c.window === 'YTD' ? 'This year' : 'If sold today'} quality={v == null ? undefined : row?.quality} asOf={v == null ? null : engineAsOf} />;
        })}
      </section>
      <section className="grid">
        <div className="card c12" style={{ '--i': 5 }} data-testid="tax-calendar">
          <div className="card-head">
            <span className="tag mustard">Tax calendar</span>
            <span className="acts">
              {wash.data?.as_of ? <span className="chip">Wash windows as of {dayLabel(wash.data.as_of)}</span> : null}
              <Link className="link" to="/portfolio/stocks">
                Planned harvests
              </Link>
            </span>
          </div>
          {calendar.error && wash.error ? <p className="empty-hint">The tax calendar didn&apos;t load. It comes back with the desk API.</p> : <TaxCalendar events={events} windows={windows} today={todayEt()} />}
        </div>
      </section>
    </>
  );
}

import { useMemo } from 'react';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Kpi } from '../components/Kpi.jsx';
import { DriftRows } from '../components/DriftRows.jsx';
import { TaxCalendar } from '../components/TaxCalendar.jsx';
import { FiPath } from '../plan/FiPath.jsx';
import { todayEt } from '../lib/tax.js';
import { useLive } from '../live/context.js';
import { useApi } from '../lib/api.js';
import { fundsFromMetrics, useMetrics, val } from '../lib/metrics.js';
import { planLimits } from '../lib/plan.js';
import { dayLabel } from '../lib/charts.js';
import { QUALITY } from '../lib/quality.js';
import { plural, usd } from '../lib/format.js';
import { emptyText, moneyIn, rhythmText, seenText } from '../lib/deposits.js';

const HEAD_IDS = 'plan.drift_max,plan.in_mix,plan.single_stock,plan.rules,tax.harvestable';
const TILT = { growth: 'Growth tilt', balanced: 'Balanced', income: 'Income tilt' };
const fmtPts = (v) => (v == null ? '—' : `${v < 0 ? '−' : v > 0 ? '+' : ''}${Math.abs(v).toFixed(1)} pts`);

// ---------- cards ----------
function Rules({ rules, m, version }) {
  return (
    <div className="card c5" style={{ '--i': 8 }}>
      <div className="card-head">
        <span className="tag coral">Rules</span>
        <span className="acts">{version != null ? <span className="chip">desk.yaml rules v{version}</span> : null}</span>
      </div>
      {rules.length ? (
        rules.map((r) => {
          const pass = val(m.get('plan.rules', { scope: 'rule', scopeId: r.id }));
          const on = r.enabled !== false;
          const tone = !on ? '' : pass == null ? 'info' : pass >= 1 ? 'ok' : 'watch';
          const word = !on ? 'Off' : pass == null ? 'Not checked' : pass >= 1 ? 'Passing' : 'Heads up';
          return (
            <div className="rule" key={r.id}>
              <span style={{ color: `var(--${tone || 'ink-3'})` }}>
                <Icon name={pass >= 1 ? 'check' : 'flag'} />
              </span>
              <span>
                <b>{r.label || r.id}</b>
              </span>
              <span className={`chip ${tone}`}>{word}</span>
            </div>
          );
        })
      ) : (
        <p className="empty-hint">No rules in desk.yaml yet.</p>
      )}
      <div className="note" style={{ marginTop: 8 }}>
        <Icon name="info" />
        <span>Rules are checked by Preflight before every proposal. Changing one makes a new desk.yaml version and is logged like a decision.</span>
      </div>
    </div>
  );
}

function Funds({ funds, live, names }) {
  const maxW = Math.max(1, ...funds.map((f) => Math.max(f.weight ?? 0, f.target ?? 0)));
  return (
    <div className="card c7" style={{ '--i': 9 }}>
      <div className="card-head">
        <span className="tag sky">Funds</span>
        <span className="acts">
          <span className="muted" style={{ fontSize: 12 }}>
            Pick a fund for its symbol sheet
          </span>
        </span>
      </div>
      <div className="tscroll">
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Fund</th>
              <th scope="col" className="r">
                Value
              </th>
              <th scope="col">Weight</th>
              <th scope="col" className="r">
                Target
              </th>
              <th scope="col" className="r">
                Drift
              </th>
            </tr>
          </thead>
          <tbody>
            {funds.map((f) => {
              const row = live.find((s) => s.symbol === f.symbol);
              return (
                <tr key={f.symbol} data-sym={f.symbol} tabIndex={0}>
                  <td>
                    <span className="sym">
                      <i style={{ '--c': f.target != null ? 'var(--s1)' : 'var(--s2)' }} />
                      {f.symbol}
                      <small>{names[f.symbol] || ''}</small>
                    </span>
                  </td>
                  <td className="r">{row ? usd(row.value) : '—'}</td>
                  <td>
                    {f.weight != null ? `${f.weight.toFixed(1)}%` : '—'}
                    <span className="databar" aria-hidden="true">
                      <i style={{ width: `${((f.weight ?? 0) / maxW) * 100}%` }} />
                    </span>
                  </td>
                  <td className="r">{f.target != null ? `${f.target.toFixed(0)}%` : <span className="muted">Not in plan</span>}</td>
                  <td className={`r ${f.drift == null ? '' : Math.abs(f.drift) >= 5 ? 'dn' : ''}`}>{f.target != null ? fmtPts(f.drift) : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Deposits({ funds, deposits, mode, landed, deskValue }) {
  const split = funds.filter((f) => f.next != null && f.next > 0);
  const total = split.reduce((a, f) => a + f.next, 0);
  const after = (f) => (deskValue && f.weight != null && f.target != null ? (((f.weight / 100) * deskValue + f.next) / (deskValue + total)) * 100 - f.target : null);
  const modelled = funds.some((f) => f.next != null && f.quality === 'modelled');
  const auto = mode === 'auto';
  const money = moneyIn(landed);
  return (
    <div className="card c5" style={{ '--i': 10 }} data-testid="deposits" data-mode={mode || 'listed'}>
      <div className="card-head">
        <span className="tag mustard">Next deposit</span>
        <span className="acts">
          {auto ? <span className="chip">From your activity</span> : null}
          {modelled ? <span className="chip lilac">{QUALITY.modelled}</span> : null}
        </span>
      </div>
      {deposits.length ? (
        <div className="rows" style={{ marginBottom: 8 }} data-testid="rhythm">
          {deposits.map((d, i) => (
            <div className="rule" key={`${d.id || d.account || 'dep'}-${i}`}>
              <span style={{ color: 'var(--teal-ink)' }}>
                <Icon name="calendar" />
              </span>
              <span>
                <b>{d.label || d.name || d.id || 'Deposit'}</b>
                <small>{[rhythmText(d) || 'Scheduled', seenText(d)].filter(Boolean).join(' · ')}</small>
              </span>
              <span />
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-hint" style={{ marginBottom: 8 }} data-testid="rhythm-empty">
          {emptyText(mode)}
          {split.length ? ' The split below is modelled from the plan.' : ''}
        </p>
      )}
      {money.length ? (
        <div className="rows money-in" style={{ marginBottom: 8 }} data-testid="money-in">
          <span className="kicker">Money in</span>
          {money.map((d) => (
            <div className="row" key={d.key} data-status={d.status} data-scheduled={d.scheduled}>
              <span className="l">
                <span className={`mi-dot ${d.status}`} aria-hidden="true" />
                <span>
                  <b>{d.label}</b>
                  <small>{d.when}</small>
                </span>
              </span>
              <span className="v">{usd(d.amount)}</span>
            </div>
          ))}
        </div>
      ) : null}
      {split.length ? (
        <>
          <p className="muted" style={{ fontSize: 12.5, marginBottom: 6 }}>
            {usd(total)} split to pull every fund back toward its target.
          </p>
          <div className="rows" data-testid="split">
            {split.map((f) => (
              <div className="row" key={f.symbol} data-sym={f.symbol} tabIndex={0}>
                <span className="l">
                  <span className="sym">
                    <i style={{ '--c': 'var(--s1)' }} />
                    {f.symbol}
                  </span>
                  <span className="databar" style={{ width: 120 }} aria-hidden="true">
                    <i style={{ width: `${(f.next / total) * 100}%` }} />
                  </span>
                </span>
                <span className="v">
                  {usd(f.next)}
                  <small>
                    drift {fmtPts(f.drift)} → {fmtPts(after(f))}
                  </small>
                </span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <p className="empty-hint">Nothing to split yet.</p>
      )}
    </div>
  );
}

function Taxes({ m, calendar, wash }) {
  const cell = (id, window, label) => {
    const row = m.get(id, { window });
    const v = val(row);
    return (
      <div key={id}>
        <small>{label}</small>
        <b>{v == null ? '—' : usd(v, { sign: true })}</b>
        <span className="muted">{v == null ? 'Needs a lot export' : window === 'YTD' ? 'This year' : 'If sold today'}</span>
      </div>
    );
  };
  const events = (calendar.data?.events || []).filter((e) => !e.kind || e.kind === 'tax');
  return (
    <div className="card c12" style={{ '--i': 11 }} data-testid="tax-calendar">
      <div className="card-head">
        <span className="tag mustard">Tax calendar</span>
        <span className="acts">{wash.data?.as_of ? <span className="chip">Wash windows as of {dayLabel(wash.data.as_of)}</span> : null}</span>
      </div>
      <div className="mini-kpis four">
        {cell('tax.realized_st', 'YTD', 'Realized short term')}
        {cell('tax.realized_lt', 'YTD', 'Realized long term')}
        {cell('tax.unrealized_st', 'now', 'Unrealized short term')}
        {cell('tax.unrealized_lt', 'now', 'Unrealized long term')}
      </div>
      {calendar.error && wash.error ? (
        <p className="empty-hint">The tax calendar didn&apos;t load. It comes back with the desk API.</p>
      ) : (
        <TaxCalendar events={events} windows={wash.data?.windows || []} today={todayEt()} />
      )}
    </div>
  );
}

// ---------- page ----------
export default function Plan() {
  const ctx = useLive();
  const m = useMetrics(HEAD_IDS);
  const plan = useMetrics('plan.*', 'scope=holding');
  const profile = useApi('/api/decisions/profile');
  const rules = useApi('/api/decisions/rules');
  const tax = useMetrics('tax.*');
  const calendar = useApi('/api/decisions/calendar');
  const deposits = useApi('/api/decisions/deposits');
  const wash = useApi('/api/engine/wash');
  const limits = planLimits(profile.data, rules.data);
  const funds = useMemo(() => fundsFromMetrics(plan.rows), [plan.rows]);
  const values = useMemo(() => Object.fromEntries(ctx.symbols.map((s) => [s.symbol, s.value])), [ctx.symbols]);
  const p = profile.data?.profile || {};
  const ruleList = rules.data?.rules || p.rules || [];
  const engineAsOf = m.asOf ? `engine ${dayLabel(m.asOf)}` : null;

  if (m.loading || plan.loading) {
    return <Hero kicker="Plan" title="Plan" art="plan" big={<b>Checking…</b>} foot={<span className="chip">Reading the plan</span>} />;
  }

  if (m.error && plan.error) {
    return (
      <>
        <Hero kicker="Plan" title="Plan" art="plan" big={<b>No answer</b>} foot={<span className="chip watch">Desk API offline</span>} />
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button
              className="btn sm"
              type="button"
              onClick={() => {
                m.reload();
                plan.reload();
              }}
            >
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">The plan comes back as soon as it does.</p>
        </section>
      </>
    );
  }

  const drift = m.get('plan.drift_max');
  const inMix = m.get('plan.in_mix');
  const single = m.get('plan.single_stock');
  const harvest = m.get('tax.harvestable');
  const ruleRows = m.all('plan.rules', 'rule');
  const passing = ruleRows.filter((r) => r.value >= 1).length;
  const next = funds.reduce((a, f) => a + (f.next || 0), 0);
  const nextModelled = funds.some((f) => f.next != null && f.quality === 'modelled');
  const driftV = val(drift);
  const inMixV = val(inMix);
  const singleV = val(single);
  const harvestV = val(harvest);
  const inPlan = funds.filter((f) => f.target != null);

  return (
    <>
      <Hero
        kicker={`Plan · desk profile v${limits.version ?? '—'}`}
        title="Plan"
        art="plan"
        big={
          <>
            <b>{inMixV == null ? 'No plan yet' : `${inMixV.toFixed(1)}% in the mix`}</b>
            {driftV != null ? <span className="muted">largest drift {driftV.toFixed(1)} pts</span> : null}
          </>
        }
        foot={
          <>
            {p.risk_level != null ? <span className="chip">Risk {p.risk_level} of 5</span> : null}
            {p.growth?.tilt ? <span className="chip">{TILT[p.growth.tilt] || p.growth.tilt}</span> : null}
            {p.growth?.horizon_years ? <span className="chip">{p.growth.horizon_years}-year horizon</span> : null}
            {profile.data?.source === 'defaults' ? <span className="chip lilac">Default profile</span> : null}
          </>
        }
      />
      <section className="kpis kpis-6">
        <Kpi i={1} label="Largest drift" metric="plan.drift_max" value={driftV == null ? '—' : driftV.toFixed(1)} unit="pts" tone={driftV != null && driftV >= limits.driftPts ? 'watch' : undefined} line={`Rebalance at ${limits.driftPts}`} quality={drift?.quality} asOf={engineAsOf} />
        <Kpi i={2} label="Next deposit" metric="plan.next_deposit" value={next ? usd(next) : '—'} line={next ? `${plural(funds.filter((f) => f.next > 0).length, 'fund')} get some` : profile.data?.deposits_mode === 'auto' ? 'None on a steady rhythm' : 'Nothing scheduled'} quality={nextModelled ? 'modelled' : undefined} asOf={engineAsOf} />
        <Kpi i={3} label="Rules" metric="plan.rules" value={ruleRows.length ? `${passing} of ${ruleRows.length}` : '—'} tone={ruleRows.length && passing < ruleRows.length ? 'watch' : undefined} line={ruleRows.length && passing === ruleRows.length ? 'All passing' : 'Some need a look'} asOf={engineAsOf} />
        <Kpi i={4} label="In the mix" metric="plan.in_mix" value={inMixV == null ? '—' : inMixV.toFixed(1)} unit="%" line="Of the desk in plan funds" quality={inMix?.quality} asOf={engineAsOf} />
        <Kpi i={5} label="Single stocks" metric="plan.single_stock" value={singleV == null ? '—' : singleV.toFixed(1)} unit="%" line={`Cap ${limits.satelliteCap}%`} quality={single?.quality} asOf={engineAsOf} />
        <Kpi i={6} label="Harvestable" metric="tax.harvestable" value={harvestV == null ? 'Not yet' : usd(harvestV)} line={harvestV == null ? 'Needs a lot export' : 'Losses past the threshold'} quality={harvestV == null ? undefined : harvest?.quality} asOf={harvestV == null ? null : engineAsOf} />
      </section>
      <section className="grid">
        <div className="card c7" style={{ '--i': 7 }}>
          <div className="card-head">
            <span className="tag mint">Drift</span>
            <span className="acts">
              <span className="chip">{plural(inPlan.length, 'plan fund')}</span>
            </span>
          </div>
          {inPlan.length ? <DriftRows rows={inPlan} band={limits.driftPts} values={values} /> : <p className="empty-hint">The plan mix shows after the engine&apos;s first daily run.</p>}
        </div>
        <Rules rules={ruleList} m={m} version={limits.rulesVersion} />
        <Funds funds={funds} live={ctx.symbols} names={ctx.names} />
        <Deposits funds={funds} deposits={Array.isArray(p.deposits) ? p.deposits : []} mode={profile.data?.deposits_mode} landed={deposits.data?.deposits} deskValue={ctx.live?.value} />
        <Taxes m={tax} calendar={calendar} wash={wash} />
        <FiPath />
      </section>
    </>
  );
}

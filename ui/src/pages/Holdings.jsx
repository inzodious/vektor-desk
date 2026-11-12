import { useMemo } from 'react';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Kpi } from '../components/Kpi.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { Board } from '../components/Board.jsx';
import { PORTFOLIO_TABS } from '../lib/areas.js';
import { DriftRows } from '../components/DriftRows.jsx';
import { FiPath } from '../plan/FiPath.jsx';
import { LIVE_STATES, useLive } from '../live/context.js';
import { useApi } from '../lib/api.js';
import { fundsFromMetrics, useMetrics, val } from '../lib/metrics.js';
import { driftTone, driftWords, judgedRuleRows, planLimits, ruleState, useReference } from '../lib/plan.js';
import { dayStamp, useAsOf } from '../lib/asof.js';
import { QUALITY } from '../lib/quality.js';
import { plural, usd } from '../lib/format.js';
import { emptyText, moneyIn, rhythmText, seenText } from '../lib/deposits.js';
import { GapGate } from '../start/EmptyState.jsx';

const HEAD_IDS = 'plan.drift_max,plan.in_mix,plan.single_stock,plan.rules,fi.progress';
const TILT = { growth: 'Growth tilt', balanced: 'Balanced', income: 'Income tilt' };
const fmtPts = (v) => (v == null ? '—' : `${v < 0 ? '−' : v > 0 ? '+' : ''}${Math.abs(v).toFixed(1)} pts`);

// ---------- cards ----------
function Rules({ rules, m, version, reference }) {
  return (
    <div className="card c5" style={{ '--i': 8 }} data-testid="rules-card">
      <div className="card-head">
        <span className="tag coral">Rules</span>
        <span className="acts">{version != null ? <span className="chip">desk.yaml rules v{version}</span> : null}</span>
      </div>
      {rules.length ? (
        rules.map((r) => {
          const state = ruleState(r, val(m.get('plan.rules', { scope: 'rule', scopeId: r.id })), reference);
          return (
            <div className="rule" key={r.id} data-rule={r.id}>
              <span style={{ color: `var(--${state.tone || 'ink-3'})` }}>
                <Icon name={state.icon} />
              </span>
              <span>
                <b>{r.label || r.id}</b>
                {state.line ? <small>{state.line}</small> : null}
              </span>
              <span className={`chip ${state.tone}`}>{state.word}</span>
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

function Funds({ funds, live, names, words, tone }) {
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
                {words.target}
              </th>
              <th scope="col" className="r">
                {words.gap}
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
                  <td className="r">{f.target != null ? `${f.target.toFixed(0)}%` : <span className="muted">{words.judged ? 'No target' : 'Not in the mix'}</span>}</td>
                  <td className={`r ${tone(f.drift) ? 'dn' : ''}`}>{f.target != null ? fmtPts(f.drift) : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Deposits({ funds, deposits, mode, landed, deskValue, words }) {
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
          {split.length ? ' The split below is modelled from your targets.' : ''}
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
            {usd(total)} {words.split}
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
                    {words.step} {fmtPts(f.drift)} → {fmtPts(after(f))}
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

// ---------- page ----------
export default function Holdings() {
  const ctx = useLive();
  const m = useMetrics(HEAD_IDS);
  const clock = useAsOf();
  const plan = useMetrics('plan.*', 'scope=holding');
  const profile = useApi('/api/decisions/profile');
  const rules = useApi('/api/decisions/rules');
  const deposits = useApi('/api/decisions/deposits');
  const limits = planLimits(profile.data, rules.data);
  const reference = useReference();
  const words = driftWords(reference, limits);
  const funds = useMemo(() => fundsFromMetrics(plan.rows), [plan.rows]);
  const values = useMemo(() => Object.fromEntries(ctx.symbols.map((s) => [s.symbol, s.value])), [ctx.symbols]);
  const p = profile.data?.profile || {};
  const ruleList = rules.data?.rules || p.rules || [];
  const engineAsOf = dayStamp(m.asOf, clock);
  const tabs = <Subtabs label="Portfolio views" tabs={PORTFOLIO_TABS} />;

  if (m.loading || plan.loading) {
    return <Hero kicker="Portfolio · Holdings" title="Holdings" art="plan" big={<b>Checking…</b>} foot={tabs} />;
  }

  if (m.error && plan.error) {
    return (
      <>
        <Hero kicker="Portfolio · Holdings" title="Holdings" art="plan" big={<b>No answer</b>} foot={tabs} />
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
          <p className="muted">Holdings come back as soon as it does.</p>
        </section>
      </>
    );
  }

  const drift = m.get('plan.drift_max');
  const inMix = m.get('plan.in_mix');
  const single = m.get('plan.single_stock');
  const fi = m.get('fi.progress');
  const ruleRows = judgedRuleRows(m.all('plan.rules', 'rule'), ruleList, reference);
  const passing = ruleRows.filter((r) => r.value >= 1).length;
  const next = funds.reduce((a, f) => a + (f.next || 0), 0);
  const nextModelled = funds.some((f) => f.next != null && f.quality === 'modelled');
  const driftV = val(drift);
  const inMixV = val(inMix);
  const singleV = val(single);
  const fiV = val(fi);
  const live = ctx.live;
  const trading = LIVE_STATES.includes(live?.state);
  const inPlan = funds.filter((f) => f.target != null);

  return (
    <>
      <Hero
        kicker={`Portfolio · desk profile v${limits.version ?? '—'}`}
        title="Holdings"
        art="plan"
        big={
          <>
            <b>{live?.value != null ? usd(live.value) : inMixV == null ? 'No targets yet' : `${inMixV.toFixed(1)}% on target funds`}</b>
            <span className="muted">
              {plural(ctx.symbols.length, 'holding')}
              {driftV != null ? ` · ${words.hero(driftV)}` : ''}
            </span>
          </>
        }
        foot={
          <>
            {tabs}
            {p.risk_level != null ? <span className="chip">Risk {p.risk_level} of 5</span> : null}
            {p.growth?.tilt ? <span className="chip">{TILT[p.growth.tilt] || p.growth.tilt}</span> : null}
            {p.growth?.horizon_years ? <span className="chip">{p.growth.horizon_years}-year horizon</span> : null}
            {profile.data?.source === 'defaults' ? <span className="chip lilac">Default profile</span> : null}
          </>
        }
      />
      <GapGate k="portfolio.holdings" icon="portfolio" title="No holdings yet" hasData={ctx.symbols.length > 0 || funds.length > 0}>
        <section className="kpis kpis-6">
          <Kpi i={1} label={words.label} metric="plan.drift_max" value={driftV == null ? '—' : driftV.toFixed(1)} unit="pts" tone={driftTone(reference, driftV, limits)} line={words.line} quality={drift?.quality} asOf={engineAsOf} />
          <Kpi i={2} label="Next deposit" metric="plan.next_deposit" value={next ? usd(next) : '—'} line={next ? `${plural(funds.filter((f) => f.next > 0).length, 'fund')} get some` : profile.data?.deposits_mode === 'auto' ? 'None on a steady rhythm' : 'Nothing scheduled'} quality={nextModelled ? 'modelled' : undefined} asOf={engineAsOf} />
          <Kpi i={3} label="Rules" metric="plan.rules" value={ruleRows.length ? `${passing} of ${ruleRows.length}` : '—'} tone={ruleRows.length && passing < ruleRows.length ? 'watch' : undefined} line={ruleRows.length && passing === ruleRows.length ? 'All passing' : 'Some need a look'} asOf={engineAsOf} />
          <Kpi i={4} label="In the mix" metric="plan.in_mix" value={inMixV == null ? '—' : inMixV.toFixed(1)} unit="%" line={reference.judged ? 'Of the desk in funds with a target' : `Of the desk in funds ${reference.mix} holds`} quality={inMix?.quality} asOf={engineAsOf} />
          <Kpi i={5} label="Single stocks" metric="plan.single_stock" value={singleV == null ? '—' : singleV.toFixed(1)} unit="%" line={`Cap ${limits.satelliteCap}%`} quality={single?.quality} asOf={engineAsOf} />
          <Kpi i={6} label="FI progress" metric="fi.progress" value={fiV == null ? 'Not yet' : fiV.toFixed(1)} unit={fiV == null ? undefined : '%'} line={fiV == null ? 'Needs the FI path' : 'of the FI number'} quality={fiV == null ? undefined : fi?.quality} asOf={fiV == null ? null : engineAsOf} onOpen={() => document.querySelector('[data-testid="fi-path"]')?.scrollIntoView({ block: 'start' })} />
        </section>
        <section className="grid">
          {ctx.symbols.length ? (
            <div className="card c12" style={{ '--i': 7 }} data-testid="holdings-board">
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
          ) : null}
          <div className="card c7" style={{ '--i': 7 }} data-testid="drift-card" data-judged={reference.judged ? 'yes' : 'no'}>
            <div className="card-head">
              <span className="tag mint">{words.tag}</span>
              <span className="acts">
                <span className="chip">{reference.judged ? `${plural(inPlan.length, 'fund')} with a target` : `${plural(inPlan.length, 'fund')} in the mix`}</span>
              </span>
            </div>
            {inPlan.length ? <DriftRows rows={inPlan} band={limits.driftPts} values={values} judged={reference.judged} target={words.target} gap={words.gap} /> : <p className="empty-hint">Targets show after the engine&apos;s first daily run.</p>}
            {reference.note ? (
              <p className="note" style={{ marginTop: 10 }} data-testid="reference-note">
                <Icon name="info" />
                <span>{reference.note}</span>
              </p>
            ) : null}
          </div>
          <Rules rules={ruleList} m={m} version={limits.rulesVersion} reference={reference} />
          <Funds funds={funds} live={ctx.symbols} names={ctx.names} words={words} tone={(v) => driftTone(reference, v, limits)} />
          <Deposits funds={funds} deposits={Array.isArray(p.deposits) ? p.deposits : []} mode={profile.data?.deposits_mode} landed={deposits.data?.deposits} deskValue={ctx.live?.value} words={words} />
          <FiPath />
        </section>
      </GapGate>
    </>
  );
}

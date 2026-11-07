import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { HBars } from '../components/HBars.jsx';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { useApi } from '../lib/api.js';
import { LAMP_COLOR, LAMP_WORD } from '../lib/decisions.js';
import { px, usd } from '../lib/format.js';
import { LAB_TABS } from '../lib/lab.js';
import {
  PAPER_DAYS,
  RULE_WORD,
  FACTOR_LABEL,
  costItems,
  factorItems,
  dayOf,
  foldItems,
  horizonRows,
  mixText,
  paperProgress,
  paperSummary,
  paramText,
  regimeItems,
  ruleVariants,
  sensitivityItems,
  signedPct,
  signedPts,
  specLines,
  statusOf,
  verdictLamps,
  verdictOf,
} from '../lib/strategy.js';

// ---------- small parts ----------
function Lamps({ lamps }) {
  return (
    <div className="annun verdict" role="list" aria-label="Verdict bars">
      {lamps.map((l) => (
        <div className="lamp" role="listitem" key={l.id} style={{ '--c': LAMP_COLOR[l.status] }} title={l.detail} data-lamp={l.id} data-status={l.status}>
          <i aria-hidden="true" />
          <b>{l.label}</b>
          <small>
            <span className="sr-only">{LAMP_WORD[l.status]}. </span>
            {l.short}
          </small>
        </div>
      ))}
    </div>
  );
}

function Tiles({ items, cls = '' }) {
  return (
    <div className={`mini-kpis ${cls}`}>
      {items.map((t) => (
        <div key={t.k} data-tile={t.k}>
          <small>{t.k}</small>
          <b className={t.tone || ''}>{t.v}</b>
          {t.line ? <span className="tile-line">{t.line}</span> : null}
        </div>
      ))}
    </div>
  );
}

const tone = (v) => (v == null ? '' : v >= 0 ? 'up' : 'dn');

function Horizons({ rows, shareWord = 'of starts ahead' }) {
  if (!rows.length) return <p className="empty-hint">No horizons ran.</p>;
  const lo = Math.min(0, ...rows.map((r) => r.lo ?? 0));
  const hi = Math.max(0, ...rows.map((r) => r.hi ?? 0));
  const X = (v) => `${((v - lo) / (hi - lo || 1)) * 100}%`;
  return (
    <div className="tscroll">
      <table className="t hz-t">
        <thead>
          <tr>
            <th scope="col">Horizon</th>
            <th scope="col">Range, 5th to 95th</th>
            <th scope="col" className="r">
              Average
            </th>
            <th scope="col" className="r">
              Ahead
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.years} className="still" data-horizon={r.years}>
              <td>
                <b>{r.years} years</b>
                <small className="muted cell-sub">{r.starts} start dates</small>
              </td>
              <td className="hz-cell">
                <span className="hz" role="img" aria-label={`${signedPts(r.lo)} to ${signedPts(r.hi)}`}>
                  <b style={{ left: X(0) }} />
                  <span style={{ left: X(r.lo ?? 0), width: `calc(${X(r.hi ?? 0)} - ${X(r.lo ?? 0)})` }} />
                  {r.mean != null ? <i style={{ left: X(r.mean) }} /> : null}
                </span>
                <small className="muted">
                  {signedPts(r.lo)} to {signedPts(r.hi)}
                </small>
              </td>
              <td className={`r num ${tone(r.mean)}`}>{signedPts(r.mean)}</td>
              <td className="r num">
                {r.share == null ? '—' : `${Math.round(r.share * 100)}%`}
                <small className="muted cell-sub">{shareWord}</small>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Caveats({ list }) {
  if (!list?.length) return null;
  return (
    <section className="card" data-testid="caveats">
      <div className="card-head">
        <span className="tag lilac">Read with care</span>
      </div>
      <ul className="lamp-notes">
        {list.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </section>
  );
}

// ---------- strategy ----------
function PaperCard({ paper, trades }) {
  const [all, setAll] = useState(false);
  const prog = paperProgress(paper);
  const sum = paperSummary(paper);
  if (!paper)
    return (
      <div className="card c5" data-testid="paper">
        <div className="card-head">
          <span className="tag mustard">Paper trading</span>
        </div>
        <p className="empty-hint">Not on paper. A strategy trades fake money for six months only after it passes the lab.</p>
      </div>
    );
  const shown = all ? trades : trades.slice(0, 6);
  return (
    <div className="card c5" data-testid="paper">
      <div className="card-head">
        <span className="tag mustard">Paper trading</span>
        <span className={`chip ${statusOf(paper.status).tone}`}>{statusOf(paper.status).t}</span>
      </div>
      <div className="strat-prog big">
        <span className="meter" role="img" aria-label={`Day ${prog.days} of ${PAPER_DAYS}`}>
          <i style={{ width: `${prog.share * 100}%` }} />
        </span>
        <small>
          Day {prog.days} of {PAPER_DAYS} · started {dayOf(paper.started)}
          {prog.done ? '' : ` · ${prog.left} days to go`}
        </small>
      </div>
      <Tiles
        items={[
          { k: 'Fake money', v: usd(paper.value) },
          { k: 'Return', v: signedPct(paper.return_pct), tone: tone(paper.return_pct) },
          { k: 'Against its benchmark', v: signedPts(paper.excess_pts), tone: tone(paper.excess_pts) },
        ]}
      />
      {sum ? (
        <p className="empty-hint" style={{ marginTop: 8 }}>
          {sum.trades} trades, {usd(sum.costs_usd)} in costs, worst drop {signedPct(sum.mdd_pct)}.
        </p>
      ) : null}
      {trades.length ? (
        <>
          <div className="tscroll" style={{ marginTop: 8 }}>
            <table className="t" data-testid="paper-trades">
              <thead>
                <tr>
                  <th scope="col">Day</th>
                  <th scope="col">Trade</th>
                  <th scope="col" className="r">
                    Price
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((t) => (
                  <tr key={`${t.date}-${t.symbol}-${t.side}`} className="still">
                    <td>{dayOf(t.date).replace(/, \d{4}$/, '')}</td>
                    <td>
                      <span className={`chip ${t.side === 'buy' ? 'ok' : ''}`}>{t.side === 'buy' ? 'Buy' : 'Sell'}</span> {t.symbol}
                    </td>
                    <td className="r num">${px(t.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {trades.length > 6 ? (
            <button className="link" type="button" onClick={() => setAll(!all)}>
              {all ? 'Show fewer' : `Show all ${trades.length} trades`}
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function VerdictCard({ final, windows }) {
  if (!final)
    return (
      <div className="card c7" data-testid="verdict">
        <div className="card-head">
          <span className="tag">Verdict</span>
          <span className="chip">Sealed</span>
        </div>
        <p className="empty-hint">Not finalized yet. The holdout years{windows?.holdout_start ? ` from ${dayOf(windows.holdout_start)}` : ''} stay sealed until the desk asks for a verdict, once per version.</p>
      </div>
    );
  const v = verdictOf(final.verdict);
  const h = final.holdout;
  return (
    <div className="card c7" data-testid="verdict">
      <div className="card-head">
        <span className="tag">Verdict</span>
        <span className={`chip ${v.tone}`}>{v.t}</span>
      </div>
      <Lamps lamps={verdictLamps(final.bars)} />
      <p className="empty-hint" style={{ margin: '8px 0' }}>
        Picked settings: {paramText(final.params)}.
      </p>
      {h ? (
        <>
          <span className="kicker">
            Holdout, {dayOf(h.start)} to {dayOf(h.end)}
          </span>
          <Tiles
            items={[
              { k: 'Return', v: signedPct(h.return_pct), tone: tone(h.return_pct) },
              { k: 'Against the plan', v: signedPts(h.excess_vs_bench_pts), tone: tone(h.excess_vs_bench_pts) },
              { k: 'Worst drop', v: signedPct(h.mdd_pct) },
            ]}
          />
        </>
      ) : null}
      {final.post_cutoff ? (
        <p className="empty-hint" style={{ marginTop: 8 }} data-testid="post-cutoff">
          {final.post_cutoff.days
            ? `${final.post_cutoff.days} days after the model's training cutoff (${dayOf(final.post_cutoff.cutoff)}) were tested. The model could not have seen those.`
            : `The holdout ends before the model's training cutoff (${dayOf(final.post_cutoff.cutoff)}), so the model may have seen this period. Paper trading is the unseen test.`}
        </p>
      ) : null}
    </div>
  );
}

function StrategyView({ v }) {
  const t = v.tear_sheet;
  const wf = t?.walk_forward;
  const a = v.analyses || {};
  const sens = sensitivityItems(a.param_sensitivity);
  const regimes = regimeItems(a.regime_split);
  const costs = costItems(a.turnover_cost);
  const factor = v.final?.factor_check || t?.factor_check;
  return (
    <>
      {v.rejected?.length ? (
        <section className="card" data-testid="rejected">
          <div className="card-head">
            <span className="tag coral">Sent back</span>
            <span className="chip">The lab would not run it</span>
          </div>
          <ul className="lamp-notes">
            {v.rejected.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {v.spec ? (
        <section className="card" data-testid="spec">
          <div className="card-head">
            <span className="tag mint">The idea</span>
            {v.spec.predicted_effect ? <span className="chip">Predicted: {v.spec.predicted_effect}</span> : null}
          </div>
          {v.spec.hypothesis ? <p className="spec-line">{v.spec.hypothesis}</p> : null}
          <dl className="spec-rules">
            {specLines(v.spec).map((l) => (
              <div key={l.k}>
                <dt>{l.k}</dt>
                <dd>{l.v}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}
      {t || v.final || v.paper ? (
        <section className="grid">
          <VerdictCard final={v.final} windows={t?.windows} />
          <PaperCard paper={v.paper} trades={v.paper_trades || []} />
        </section>
      ) : null}
      {wf ? (
        <section className="card" data-testid="walk-forward">
          <div className="card-head">
            <span className="tag sky">Walk-forward record</span>
            <span className="chip">
              {dayOf(wf.start)} to {dayOf(wf.end)} · {t.variants} variants, {t.trials_family} in the family
            </span>
          </div>
          <Tiles
            cls="six"
            items={[
              { k: 'A year, averaged', v: signedPct(wf.ann_return_pct), tone: tone(wf.ann_return_pct) },
              { k: 'Against the plan', v: signedPts(wf.excess_pts), tone: tone(wf.excess_pts), line: 'a year' },
              { k: 'Sharpe', v: wf.sharpe == null ? '—' : wf.sharpe.toFixed(2) },
              { k: 'Worst drop', v: signedPct(wf.mdd_pct) },
              { k: 'Deflated Sharpe', v: t.deflated_sharpe == null ? '—' : t.deflated_sharpe.toFixed(2), line: 'chance the edge is real' },
              { k: 'Overfit odds', v: t.pbo == null ? '—' : `${Math.round(t.pbo * 100)}%`, line: 'lower is better', tone: t.pbo != null && t.pbo > 0.5 ? 'dn' : '' },
            ]}
          />
        </section>
      ) : null}
      {v.folds?.length || t?.horizons?.length ? (
        <section className="grid">
          <div className="card c6" data-testid="folds">
            <div className="card-head">
              <span className="tag">Each test year</span>
              <span className="chip">Against the plan</span>
            </div>
            <HBars items={foldItems(v.folds)} fmt={(x) => signedPts(x)} name="Against the plan" labelW={52} rowH={22} empty="No folds yet." />
            <p className="empty-hint" style={{ marginTop: 6 }}>
              Tuned on the three years before, then tested on a year it never saw.
            </p>
          </div>
          <div className="card c6" data-testid="horizons">
            <div className="card-head">
              <span className="tag mustard">Held for a while</span>
              <span className="chip">Every start date, a year a part</span>
            </div>
            <Horizons rows={horizonRows(t?.horizons)} />
          </div>
        </section>
      ) : null}
      {sens.length || regimes.length || costs.length ? (
        <section className="grid mult" data-testid="analyses">
          {sens.map((s) => (
            <div className="card c4" key={s.param} data-analysis={`param-${s.param}`}>
              <div className="card-head">
                <span className="tag sky">Setting: {s.param.replace(/_/g, ' ')}</span>
                <span className="chip">Average Sharpe</span>
              </div>
              <HBars items={s.items} fmt={(x) => x.toFixed(2)} name="Average Sharpe" labelW={120} table={false} />
            </div>
          ))}
          {regimes.length ? (
            <div className="card c4" data-analysis="regimes">
              <div className="card-head">
                <span className="tag mint">By market</span>
                <span className="chip">Against the plan, a year</span>
              </div>
              <HBars items={regimes} fmt={(x) => signedPts(x)} name="Against the plan" labelW={120} table={false} />
            </div>
          ) : null}
          {costs.length ? (
            <div className="card c4" data-analysis="costs">
              <div className="card-head">
                <span className="tag coral">If trading cost more</span>
              </div>
              <HBars items={costs} fmt={(x) => signedPts(x)} name="Against the plan" labelW={96} table={false} />
            </div>
          ) : null}
          {factor ? (
            <div className="card c4" data-analysis="factor">
              <div className="card-head">
                <span className="tag lilac">Factor check</span>
                <span className={`chip ${factor.label === 'alpha' ? 'ok' : ''}`}>{FACTOR_LABEL[factor.label] || 'Not run'}</span>
              </div>
              {factor.status === 'ok' ? (
                <>
                  <HBars items={factorItems(factor.loadings)} fmt={(x) => x.toFixed(2)} name="Loading" labelW={96} table={false} />
                  <p className="empty-hint" style={{ marginTop: 6 }}>
                    Alpha {signedPct(factor.alpha_ann_pct)} a year, t {factor.alpha_t ?? '—'}. A t of 2 or more passes.
                  </p>
                </>
              ) : (
                <p className="empty-hint">{factor.note || 'Alpha after the six French factors.'}</p>
              )}
            </div>
          ) : null}
        </section>
      ) : null}
      <Caveats list={t?.caveats} />
    </>
  );
}

// ---------- rule ----------
function RuleView({ v }) {
  const r = v.rule || {};
  const rows = ruleVariants(r);
  const base = r.baseline?.full;
  const best = rows.find((x) => x.best) || rows[0];
  return (
    <>
      {v.rejected?.length ? (
        <section className="card" data-testid="rejected">
          <div className="card-head">
            <span className="tag coral">Sent back</span>
          </div>
          <ul className="lamp-notes">
            {v.rejected.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <section className="card" data-testid="setup">
        <div className="card-head">
          <span className="tag mint">The setup</span>
          <span className="chip">{r.taxable ? 'Taxable account' : 'Sheltered account'}</span>
        </div>
        <div className="chips-row">
          {r.mix ? <span className="chip">Mix: {mixText(r.mix)}</span> : null}
          {r.start_value != null ? <span className="chip">Starts with {usd(r.start_value)}</span> : null}
          {r.deposit_monthly != null ? <span className="chip">{usd(r.deposit_monthly)} a month</span> : null}
          {r.windows ? (
            <span className="chip">
              {dayOf(r.windows.start)} to {dayOf(r.windows.last || r.windows.end)}
            </span>
          ) : null}
        </div>
      </section>
      <section className="grid">
        <div className="card c7" data-testid="variants">
          <div className="card-head">
            <span className="tag">Against never selling</span>
            <span className="chip">A year, whole period</span>
          </div>
          <HBars items={rows.map((x) => ({ label: x.label, value: x.full }))} fmt={(x) => signedPts(x, 2)} name="Against never selling" labelW={170} empty="No variants ran." />
          <p className="empty-hint" style={{ marginTop: 6 }}>
            The baseline splits every deposit across the mix and never sells.{best ? ` Best setting: ${best.label}.` : ''}
          </p>
        </div>
        <div className="card c5" data-testid="baseline">
          <div className="card-head">
            <span className="tag sky">Never selling</span>
            <span className="chip">Baseline</span>
          </div>
          {base ? (
            <Tiles
              items={[
                { k: 'Put in', v: usd(base.contributed) },
                { k: 'Ends with, after tax', v: usd(base.after_liquidation) },
                { k: 'A year, time-weighted', v: signedPct(base.twr_ann_pct), tone: tone(base.twr_ann_pct) },
                { k: 'Worst drop', v: signedPct(base.mdd_pct) },
                { k: 'Taxes', v: usd(base.taxes) },
                { k: 'Costs', v: usd(base.costs) },
              ]}
            />
          ) : (
            <p className="empty-hint">No baseline in this result.</p>
          )}
        </div>
      </section>
      <section className="card" data-testid="variant-table">
        <div className="card-head">
          <span className="tag">Every setting</span>
          <span className="chip">{rows.length === 1 ? '1 setting' : `${rows.length} settings`}</span>
        </div>
        <div className="tscroll">
          <table className="t">
            <thead>
              <tr>
                <th scope="col">Setting</th>
                <th scope="col" className="r">
                  Whole period
                </th>
                <th scope="col" className="r">
                  Holdout
                </th>
                <th scope="col" className="r">
                  Ends with
                </th>
                <th scope="col" className="r">
                  Taxes
                </th>
                {rows.some((x) => x.interest) ? (
                  <th scope="col" className="r">
                    Interest
                  </th>
                ) : null}
                {rows.some((x) => x.calls) ? (
                  <th scope="col" className="r">
                    Margin calls
                  </th>
                ) : null}
                <th scope="col">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.label} className="still" data-variant={x.label}>
                  <td>
                    <b>{x.label}</b>
                    {x.best ? <small className="muted cell-sub">Best</small> : null}
                  </td>
                  <td className={`r num ${tone(x.full)}`}>{signedPts(x.full, 2)}</td>
                  <td className={`r num ${tone(x.holdout)}`}>{signedPts(x.holdout, 2)}</td>
                  <td className="r num">{usd(x.end)}</td>
                  <td className="r num">{usd(x.taxes)}</td>
                  {rows.some((y) => y.interest) ? <td className="r num">{usd(x.interest)}</td> : null}
                  {rows.some((y) => y.calls) ? <td className="r num">{x.calls}</td> : null}
                  <td>
                    <span className={`chip ${verdictOf(x.verdict).tone}`}>{verdictOf(x.verdict).t}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {best?.horizons?.length ? (
        <section className="card" data-testid="horizons">
          <div className="card-head">
            <span className="tag mustard">Held for a while, best setting</span>
            <span className="chip">Against never selling</span>
          </div>
          <Horizons rows={best.horizons} shareWord="of starts better" />
        </section>
      ) : null}
      <Caveats list={r.caveats} />
    </>
  );
}

// ---------- page ----------
function heroLine(v) {
  if (v.kind === 'rule') return `${(v.rule?.trials ?? ruleVariants(v.rule).length) || 0} settings replayed on your plan mix`;
  if (v.paper && v.status === 'paper') {
    const p = paperProgress(v.paper);
    return `day ${p.days} of ${PAPER_DAYS} · ${signedPts(v.paper.excess_pts)} against its benchmark`;
  }
  if (v.final) return `final verdict: ${verdictOf(v.final.verdict).t.toLowerCase()}`;
  if (v.status === 'rejected') return 'the lab sent the spec back';
  if (v.tear_sheet) return `${v.tear_sheet.variants} variants tried, holdout still sealed`;
  return '';
}

export default function Strategy() {
  const { id } = useParams();
  const api = useApi(`/api/lab/strategies/${encodeURIComponent(id)}`);
  const list = useApi('/api/lab/strategies');
  const v = api.data;
  const row = list.data?.strategies?.find((s) => s.id === id);
  const isRule = v?.kind === 'rule';
  const title = isRule ? RULE_WORD[v.rule?.rule] || v.rule?.rule || id : v?.spec?.title || row?.title || id;
  const word = isRule ? verdictOf(v.status) : statusOf(v?.status);
  const foot = (
    <>
      <Subtabs label="Lab views" tabs={LAB_TABS} />
      <Link className="btn sm ghost" to="/lab/strategies">
        <Icon name="right" className="mirror" />
        All strategies
      </Link>
    </>
  );

  if (api.error && !v)
    return (
      <>
        <Hero kicker="Lab · Strategy" title={id} art="lab" foot={foot} />
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">{api.error.status === 404 ? 'Nothing in the lab by that name' : "The desk API didn't answer"}</span>
            {api.error.status === 404 ? null : (
              <button className="btn sm" type="button" onClick={api.reload}>
                <Icon name="swap" />
                Retry
              </button>
            )}
          </div>
          <p className="muted">{api.error.status === 404 ? api.error.message : 'The result comes back as soon as it does.'}</p>
        </section>
      </>
    );

  return (
    <>
      <Hero
        kicker={isRule ? 'Lab · Rule test' : 'Lab · Strategy'}
        title={title}
        art="lab"
        big={
          v ? (
            <>
              <b>{word.t}</b>
              <span className="muted">{heroLine(v)}</span>
            </>
          ) : (
            <b>Checking…</b>
          )
        }
        sub={v ? `${isRule ? id : `${id} · v${v.version}`}${v.spec_hash ? ` · frozen ${v.spec_hash.slice(0, 8)}` : ''}` : null}
        foot={foot}
      />
      {v ? isRule ? <RuleView v={v} /> : <StrategyView v={v} /> : null}
    </>
  );
}

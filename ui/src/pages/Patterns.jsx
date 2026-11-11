import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Combo } from '../components/Combo.jsx';
import { HBars } from '../components/HBars.jsx';
import { Heatmap } from '../components/Heatmap.jsx';
import { Icon } from '../components/Icon.jsx';
import { LabHero } from '../lab/parts.jsx';
import { RuleTests } from '../lab/RuleTests.jsx';
import { useApi } from '../lib/api.js';
import { dayLabel, divergingColor } from '../lib/charts.js';
import { baseRateText, fundingItems, patternValue, seasonGrid, setupItems } from '../lib/flight.js';
import { pct, usd } from '../lib/format.js';
import { headline } from '../lib/replay.js';
import { GapGate } from '../start/EmptyState.jsx';

const signedUsd = (v) => (v == null ? '—' : usd(v, { sign: true }));

// ---------- parts ----------
function PatternTile({ p }) {
  const rate = baseRateText(p);
  return (
    <div className="pat" data-pattern={p.id} data-scope={p.scope_id}>
      <small>{p.label}</small>
      <b>{patternValue(p)}</b>
      {p.bucket ? <span className="chip">{p.bucket}</span> : null}
      {rate ? <p className={p.n ? '' : 'muted'}>{rate}</p> : null}
      {p.what_it_is_not ? <p className="pat-not">{p.what_it_is_not}</p> : null}
    </div>
  );
}

function Holdings({ holdings }) {
  const syms = Object.keys(holdings).filter((s) => holdings[s]?.length);
  const [pick, setPick] = useState(null);
  const sym = syms.includes(pick) ? pick : syms[0];
  if (!sym) return <p className="empty-hint">No holding has enough price history for base rates yet.</p>;
  return (
    <>
      <div className="chart-tools">
        <Combo label="Holding" options={syms.map((s) => ({ v: s, t: s }))} value={sym} onChange={setPick} />
        <span />
      </div>
      <div className="pats">
        {holdings[sym].map((p) => (
          <PatternTile p={p} key={`${p.id}-${p.scope_id}`} />
        ))}
      </div>
    </>
  );
}

function Drawdowns({ rows }) {
  const seen = new Set();
  const list = rows.filter((r) => (seen.has(r.symbol) ? false : seen.add(r.symbol)));
  if (!list.length) return <p className="empty-hint">No drawdown history yet.</p>;
  return (
    <div className="tscroll">
      <table className="t">
        <thead>
          <tr>
            <th scope="col">Holding</th>
            <th scope="col" className="r">
              Below its high
            </th>
            <th scope="col" className="r">
              Past drops this deep
            </th>
            <th scope="col" className="r">
              Typical way back
            </th>
            <th scope="col" className="r">
              Longest
            </th>
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.symbol} className="still" data-dd={r.symbol}>
              <td>
                <b>{r.symbol}</b>
                <small className="muted cell-sub">History since {dayLabel(r.since, true)}</small>
              </td>
              <td className={`r num ${r.drawdown_pct < 0 ? 'dn' : ''}`}>{pct(r.drawdown_pct / 100, 1)}</td>
              <td className="r num">{r.episodes ? r.episodes : <span className="muted">None yet</span>}</td>
              <td className="r num">{r.median_days_to_recover == null ? '—' : `${r.median_days_to_recover} days`}</td>
              <td className="r num">{r.longest_days_to_recover == null ? '—' : `${r.longest_days_to_recover} days`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReplayTease() {
  const api = useApi('/api/engine/replay');
  const head = api.data?.variants?.length ? headline(api.data) : null;
  return (
    <section className="card replay-tease" data-testid="replay-tease">
      <span className="tag coral">You versus the capped you</span>
      <span className="rt-copy">
        {head ? <b className={head.tone}>{head.value}</b> : null}
        <span>{head ? `${head.line}, replaying your own trades` : 'Your trades replayed under a size cap, an exit rule, no margin and a longer hold'}</span>
      </span>
      <Link className="btn sm" to="/strategies/habits/replay">
        <Icon name="swap" />
        {head ? 'Open the replay' : 'See the replay'}
      </Link>
    </section>
  );
}

// ---------- page ----------
export default function Patterns() {
  const api = useApi('/api/engine/patterns');
  const d = api.data;
  const mkt = d?.market || [];
  const dd = mkt.find((p) => p.id === 'pat.mkt_drawdown');
  const season = seasonGrid(d?.seasonality);
  const b = d?.behavior;
  const setups = setupItems(b?.buys_by_setup);
  const funding = fundingItems(b?.funding);

  const big = dd ? (
    <>
      <b>{patternValue(dd)}</b>
      <span className="muted">S&amp;P 500 below its high · {dd.bucket}</span>
    </>
  ) : (
    <b>{api.loading ? 'Checking…' : '—'}</b>
  );

  return (
    <>
      <LabHero kicker="My habits" title="My habits" big={big} board="My habits" />
      {api.error && !d ? (
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button className="btn sm" type="button" onClick={api.reload}>
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">Patterns come back as soon as it does.</p>
        </section>
      ) : (
        <GapGate k="strategies.habits" icon="user" title="No habits to read yet" hasData={Boolean(mkt.length || d?.drawdowns?.length || Object.keys(d?.holdings || {}).length || Object.keys(b || {}).length)}>
          <>
            <ReplayTease />
            <RuleTests />
            <section className="card" data-testid="market">
              <div className="card-head">
                <span className="tag">The market today</span>
                <span className="chip">{d?.as_of ? `As of ${dayLabel(d.as_of)}` : 'Market context'}</span>
              </div>
              {mkt.length ? (
                <div className="pats four">
                  {mkt.map((p) => (
                    <PatternTile p={p} key={p.id} />
                  ))}
                </div>
              ) : (
                <p className="empty-hint">{api.loading ? 'Reading the tape…' : 'No market context yet. It runs with the nightly engine.'}</p>
              )}
            </section>
            <section className="grid">
              <div className="card c6" data-testid="holdings">
                <div className="card-head">
                  <span className="tag mint">Your holdings</span>
                  <span className="chip">Where each sits against its own past</span>
                </div>
                <Holdings holdings={d?.holdings || {}} />
              </div>
              <div className="card c6" data-testid="drawdowns">
                <div className="card-head">
                  <span className="tag mustard">Drawdown base rates</span>
                </div>
                <Drawdowns rows={d?.drawdowns || []} />
                <p className="empty-hint" style={{ marginTop: 6 }}>
                  Trading days from an old high back to it, for past drops at least this deep. A base rate, not a call.
                </p>
              </div>
            </section>
            <section className="grid">
              <div className="card c7" data-testid="seasonality">
                <div className="card-head">
                  <span className="tag sky">Month by month, on average</span>
                  <span className="chip">{d?.seasonality_note || 'Description, never a signal'}</span>
                </div>
                {season.rows.length ? (
                  <Heatmap
                    rows={season.rows}
                    cols={season.cols}
                    values={season.values}
                    color={(v) => divergingColor(v, 0.08)}
                    fmt={(v) => pct(v, 1, true)}
                    name="Average month"
                    label="Average return by calendar month"
                    cellH={28}
                    tipHead={(i, j) => `${season.rows[i]} · ${season.cols[j]}`}
                    scale={
                      <div className="scale">
                        Down
                        <i className="div" />
                        Up
                      </div>
                    }
                  />
                ) : (
                  <p className="empty-hint">Not enough months yet.</p>
                )}
              </div>
              <div className="card c5" data-testid="corr-shifts">
                <div className="card-head">
                  <span className="tag lilac">Moving together more</span>
                </div>
                {d?.corr_shifts?.length ? (
                  <HBars items={d.corr_shifts.map((c) => ({ label: c.symbol, value: c.shift, hint: `${c.n} days` }))} fmt={(v) => v.toFixed(2)} name="Change in correlation" labelW={80} />
                ) : (
                  <p className="empty-hint">No holding changed how it moves with the rest by enough to notice. Shifts of 0.3 or more show here.</p>
                )}
              </div>
            </section>
            <section className="card" data-testid="behavior">
              <div className="card-head">
                <span className="tag coral">Your own habits</span>
                <span className="chip">Your buys against the safe mix, 90 days</span>
              </div>
              <div className="mini-kpis">
                <div>
                  <small>Trades a month</small>
                  <b>{b?.trades_per_month ?? '—'}</b>
                  <span className="tile-line">over the last year</span>
                </div>
                <div>
                  <small>Single stocks held</small>
                  <b>{b?.single_stock_hold_days_median == null ? '—' : `${b.single_stock_hold_days_median} days`}</b>
                  <span className="tile-line">{b?.single_stock_sales ? `median over ${b.single_stock_sales} sales` : 'no single-stock sales yet'}</span>
                </div>
                <div>
                  <small>Buys scored</small>
                  <b>{Object.values(b?.buys_by_setup || {}).reduce((a, x) => a + (x.n || 0), 0)}</b>
                  <span className="tile-line">yours, not the desks&apos;</span>
                </div>
              </div>
              <div className="grid hab">
                <div className="c6">
                  <span className="kicker">By what the stock did the month before</span>
                  <HBars items={setups} fmt={signedUsd} name="Average against the safe mix" labelW={140} table={false} empty="No scored buys of your own yet." />
                </div>
                <div className="c6">
                  <span className="kicker">By how you paid</span>
                  <HBars items={funding} fmt={signedUsd} name="Average against the safe mix" labelW={160} table={false} empty="Nothing to split yet." />
                </div>
              </div>
              {b?.note ? <p className="empty-hint">{b.note}</p> : null}
            </section>
            {d?.left_out ? (
              <p className="note" role="note">
                <Icon name="info" />
                <span>Left out on purpose: {d.left_out}</span>
              </p>
            ) : null}
          </>
        </GapGate>
      )}
    </>
  );
}

import { useState } from 'react';
import { Combo } from '../components/Combo.jsx';
import { HBars } from '../components/HBars.jsx';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { DECISION_TABS, SCORE_WINDOWS, kindName, originName } from '../lib/decisions.js';
import { GROUP_BY, calibrationPoints, chipOf, decisionRows, groupItems, intervalGeo, scoredCount, totalRecord } from '../lib/flight.js';
import { usd } from '../lib/format.js';

const tone = (v) => (v == null ? '' : v >= 0 ? 'up' : 'dn');
const signed = (v) => (v == null ? '—' : usd(v, { sign: true }));

// ---------- parts ----------
function Interval({ s }) {
  const g = intervalGeo(s?.ci_low, s?.ci_high, s?.mean_usd);
  if (!g) return <small className="muted">No interval yet</small>;
  return (
    <span className="ci" role="img" aria-label={`Average ${signed(s.mean_usd)}, 90% interval ${signed(s.ci_low)} to ${signed(s.ci_high)}`}>
      <span className="ci-bar">
        <b style={{ left: `${g.zero}%` }} />
        <span className={g.straddles ? 'mixed' : s.mean_usd >= 0 ? 'pos' : 'neg'} style={{ left: `${g.lo}%`, width: `${g.hi - g.lo}%` }} />
        {g.mean != null ? <i style={{ left: `${g.mean}%` }} /> : null}
      </span>
      <small className="muted">
        {signed(s.ci_low)} to {signed(s.ci_high)} a call
      </small>
    </span>
  );
}

function DeskCard({ d, i }) {
  const c = chipOf(d.chip);
  const s = d.summary_90 || {};
  return (
    <div className="card c3 desk-card" data-desk={d.desk} style={{ '--i': i }}>
      <div className="card-head">
        <span className="tag">{originName(d.desk)}</span>
        <span className={`chip ${c.tone}`} title={c.line}>
          {c.t}
        </span>
      </div>
      <b className={`desk-rec ${d.scored_90 ? tone(d.record_usd) : ''}`}>{d.scored_90 ? signed(d.record_usd) : '—'}</b>
      <small className="muted">{d.scored_90 ? `against the safe mix over ${d.scored_90} scored ${d.scored_90 === 1 ? 'call' : 'calls'}, 90 days each` : 'No calls old enough to score yet'}</small>
      <Interval s={s} />
      <dl className="desk-facts">
        <div>
          <dt>Calls</dt>
          <dd>{d.proposals}</dd>
        </div>
        <div>
          <dt>Taken</dt>
          <dd>{d.approved}</dd>
        </div>
        <div>
          <dt>Hits</dt>
          <dd>{s.hit_rate == null ? '—' : `${Math.round(s.hit_rate * 100)}%`}</dd>
        </div>
        <div>
          <dt>Days</dt>
          <dd>{d.days_on}</dd>
        </div>
      </dl>
    </div>
  );
}

function Calibration({ desks }) {
  const withBins = desks.filter((d) => d.calibration?.bins?.length);
  const [pick, setPick] = useState(null);
  const desk = withBins.find((d) => d.desk === pick) || withBins[0];
  if (!desk) return <p className="empty-hint">Calibration needs 30 scored calls with a stated confidence. It fills in as the desks build a record.</p>;
  const pts = calibrationPoints(desk.calibration);
  const W = 280;
  const H = 200;
  const P = 30;
  const X = (v) => P + v * (W - P - 22);
  const Y = (v) => H - P + 6 - v * (H - P - 6);
  const maxN = Math.max(...pts.map((p) => p.n), 1);
  return (
    <>
      <div className="chart-tools">
        <Combo label="Desk" options={withBins.map((d) => ({ v: d.desk, t: originName(d.desk) }))} value={desk.desk} onChange={setPick} />
        <span className="chip">Brier {desk.calibration.brier == null ? '—' : desk.calibration.brier.toFixed(2)}</span>
      </div>
      <div className="calib">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Said against happened for ${originName(desk.desk)}`}>
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line className="gridl" x1={X(0)} x2={X(1)} y1={Y(t)} y2={Y(t)} />
              <text x={X(0) - 6} y={Y(t) + 4} textAnchor="end">
                {Math.round(t * 100)}%
              </text>
              <text x={X(t)} y={H - 8} textAnchor="middle">
                {Math.round(t * 100)}%
              </text>
            </g>
          ))}
          <line className="ref" x1={X(0)} y1={Y(0)} x2={X(1)} y2={Y(1)} />
          {pts.map((p) => (
            <circle key={p.low} cx={X(p.said)} cy={Y(p.happened)} r={3 + 5 * Math.sqrt(p.n / maxN)} fill="var(--s1)" stroke="var(--card)" strokeWidth="2" data-bin={p.low} />
          ))}
        </svg>
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Said</th>
              <th scope="col" className="r">
                Happened
              </th>
              <th scope="col" className="r">
                Calls
              </th>
            </tr>
          </thead>
          <tbody>
            {pts.map((p) => (
              <tr key={p.low} className="still">
                <td>{Math.round(p.said * 100)}%</td>
                <td className="r num">{Math.round(p.happened * 100)}%</td>
                <td className="r num">{p.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="empty-hint" style={{ marginTop: 6 }}>
        Dots on the dashed line mean a desk&apos;s confidence matches how often it beat the safe mix. Lower Brier is better; 0.25 is a coin flip.
      </p>
    </>
  );
}

function Groups({ groups }) {
  const [by, setBy] = useState('kind');
  const [win, setWin] = useState('90D');
  const items = groupItems(groups, by, win);
  return (
    <>
      <div className="chart-tools">
        <Combo label="Group" options={GROUP_BY} value={by} onChange={setBy} />
        <Combo label="Window" options={SCORE_WINDOWS} value={win} onChange={setWin} />
      </div>
      <HBars items={items} fmt={signed} name="Against the safe mix" labelW={120} empty="Nothing scored at this window yet." />
    </>
  );
}

function Ledger({ rows }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, 10);
  return (
    <>
      <div className="tscroll">
        <table className="t" data-testid="scored-table">
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col">Call</th>
              <th scope="col">Desk</th>
              <th scope="col" className="r">
                Size
              </th>
              <th scope="col" className="r">
                30 days
              </th>
              <th scope="col" className="r">
                90 days
              </th>
              <th scope="col" className="r">
                A year
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className="still" data-call={r.id}>
                <td>{dayLabel(r.start)}</td>
                <td>
                  <b>
                    {kindName(r.kind)} {r.symbol}
                  </b>
                  <small className="muted cell-sub">{r.taken ? 'Taken' : 'Not taken'}</small>
                </td>
                <td>{originName(r.origin)}</td>
                <td className="r num">{usd(r.amount)}</td>
                <td className={`r num ${tone(r.s30)}`}>{signed(r.s30)}</td>
                <td className={`r num ${tone(r.s90)}`}>{signed(r.s90)}</td>
                <td className={`r num ${tone(r.s365)}`}>{signed(r.s365)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 10 ? (
        <button className="link" type="button" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${rows.length}`}
        </button>
      ) : null}
    </>
  );
}

// ---------- page ----------
export default function Flight() {
  const api = useApi('/api/engine/scorecard');
  const d = api.data;
  const desks = d?.desks || [];
  const total = totalRecord(desks);
  const n = scoredCount(desks);
  const tabs = <Subtabs label="Decisions views" tabs={DECISION_TABS} />;
  const rows = decisionRows(d?.decisions || [], { limit: 200 });
  const gap = d?.offplan_gap;

  const big =
    total == null || !n ? (
      <b>{api.loading ? 'Checking…' : 'No record yet'}</b>
    ) : (
      <>
        <b className={tone(total)}>{signed(total)}</b>
        <span className="muted">
          against the safe mix, {n} desk calls scored at 90 days
        </span>
      </>
    );

  if (api.error && !d)
    return (
      <>
        <Hero kicker="Decisions · Flight record" title="Flight record" art="decisions" big={<b>No answer</b>} foot={tabs} />
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button className="btn sm" type="button" onClick={api.reload}>
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">The record comes back as soon as it does.</p>
        </section>
      </>
    );

  return (
    <>
      <Hero kicker="Decisions · Flight record" title="Flight record" art="decisions" big={big} sub={d?.method} foot={tabs} />
      {desks.length ? (
        <section className="grid" data-testid="desks">
          {desks.map((x, k) => (
            <DeskCard d={x} i={k + 1} key={x.desk} />
          ))}
        </section>
      ) : (
        <section className="card">
          <p className="empty-hint">{api.loading ? 'Opening the record…' : 'No desk has a decided call yet. Every approve, dismiss and pass gets scored against the safe mix after 30, 90 and 365 days.'}</p>
        </section>
      )}
      <section className="grid">
        <div className="card c6" data-testid="calibration">
          <div className="card-head">
            <span className="tag lilac">Calibration</span>
            <span className="chip">Confidence against 90-day hits</span>
          </div>
          <Calibration desks={desks} />
        </div>
        <div className="stack c6">
          <div className="card" data-testid="groups">
            <div className="card-head">
              <span className="tag sky">Where the dollars came from</span>
            </div>
            <Groups groups={d?.groups || []} />
          </div>
          <div className="card" data-testid="saves">
            <div className="mini-kpis">
              <div>
                <small>Saves</small>
                <b className={d?.saves?.usd ? 'up' : ''}>{d?.saves ? usd(d.saves.usd) : '—'}</b>
                <span className="tile-line">{d?.saves?.n ? `${d.saves.n} times saying no or holding off beat buying` : 'None scored yet'}</span>
              </div>
              <div>
                <small>Off-mix gap</small>
                <b className={tone(gap?.total_usd)}>{gap?.n ? signed(gap.total_usd) : '—'}</b>
                <span className="tile-line">{gap?.n ? `${gap.n} calls outside the safe mix` : 'No off-mix calls scored'}</span>
              </div>
              <div>
                <small>Decided calls</small>
                <b>{rows.length}</b>
                <span className="tile-line">desks and you, all windows</span>
              </div>
            </div>
          </div>
        </div>
      </section>
      <section className="card" data-testid="scored">
        <div className="card-head">
          <span className="tag">Every decided call</span>
          <span className="chip">Same dollars into the safe mix instead</span>
        </div>
        {rows.length ? <Ledger rows={rows} /> : <p className="empty-hint">Calls score after the next close and fill in at 30, 90 and 365 days.</p>}
      </section>
    </>
  );
}

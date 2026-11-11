import { useMemo, useState } from 'react';
import { HBars } from '../components/HBars.jsx';
import { Heatmap } from '../components/Heatmap.jsx';
import { Kpi } from '../components/Kpi.jsx';
import { LineChart } from '../components/LineChart.jsx';
import { Panel } from '../components/Panel.jsx';
import { Scatter } from '../components/Scatter.jsx';
import { Factors } from '../lab/Factors.jsx';
import { LabHero } from '../lab/parts.jsx';
import { useLive } from '../live/context.js';
import { useApi } from '../lib/api.js';
import { dayLabel, divergingColor, periodStart } from '../lib/charts.js';
import { pct, usd } from '../lib/format.js';
import { QUALITY } from '../lib/quality.js';
import { useMetrics, val } from '../lib/metrics.js';
import { useJsonMany } from '../lib/useResearch.js';
import { todayEt } from '../lib/tax.js';
import { alignSeries, chunkIds, drawdown, monthGrid, pairMatrix, scenarioItems } from '../lib/lab.js';
import { GapGate } from '../start/EmptyState.jsx';

const P = (v, d = 1, sign = false) => pct(v / 100, d, sign);

const ABOUT = {
  'risk.vol': ['Volatility', 'How much daily returns swing, scaled to a year. Higher means a bumpier ride, not a worse one.'],
  'risk.sharpe': ['Sharpe ratio', 'Return above T-bills per unit of volatility. Uses actual returns only, never a short window stretched to a year.'],
  'risk.beta': ['Beta', 'How much the portfolio moves when the S&P 500 moves 1%.'],
  'risk.eff_n': ['Effective holdings', 'One over the sum of squared weights. Five equal holdings score 5; one big one and four crumbs score near 1.'],
  'risk.lookthrough': ['Look-through', 'Weights after opening each fund to its N-PORT holdings and adding direct stocks.'],
  'risk.var95': ['Bad month', 'A 1-in-20 historical loss. Expected shortfall is the average of the worse cases.'],
};

const WIN_WORD = { '1D': '1 day', '1M': '1 month', '63D': '3 months', '252D': '1 year', '1Y': '1 year', ITD: 'Since start', now: 'Now', top10: 'Top 10' };

const METRIC_WORD = {
  'risk.vol': 'Volatility',
  'risk.downside_dev': 'Downside swing',
  'risk.sharpe': 'Sharpe',
  'risk.sortino': 'Sortino',
  'risk.beta': 'Beta',
  'risk.eff_n': 'Effective holdings',
  'risk.top1': 'Biggest holding',
  'risk.top5': 'Top 5 holdings',
  'risk.lookthrough': 'Top 10 look-through',
  'risk.lookthrough_coverage': 'Value seen through',
  'risk.var95': 'Value at risk, 1 in 20',
  'risk.cvar95': 'Average of worse cases',
};

function MetricDrawer({ id, rows, onClose }) {
  const about = ABOUT[id] || [id, ''];
  const ids = id === 'risk.var95' ? ['risk.var95', 'risk.cvar95'] : id === 'risk.sharpe' ? ['risk.sharpe', 'risk.sortino'] : id === 'risk.vol' ? ['risk.vol', 'risk.downside_dev'] : id === 'risk.lookthrough' ? ['risk.lookthrough', 'risk.lookthrough_coverage'] : id === 'risk.eff_n' ? ['risk.eff_n', 'risk.top1', 'risk.top5'] : [id];
  const shown = rows.filter((m) => ids.includes(m.metric_id) && m.scope === 'portfolio').sort((a, b) => ids.indexOf(a.metric_id) - ids.indexOf(b.metric_id));
  return (
    <Panel open={!!id} onClose={onClose} title={about[0]} sub={about[1]} crumbs={[{ label: 'Portfolio · Risk', go: onClose }]}>
      <div className="tscroll">
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">Window</th>
              <th scope="col" className="r">
                Value
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((m) => (
              <tr key={`${m.metric_id}-${m.window}`} className="still">
                <td>{METRIC_WORD[m.metric_id] || m.metric_id}</td>
                <td>{WIN_WORD[m.window] || m.window}</td>
                <td className="r">
                  {m.value == null ? '—' : m.unit === 'pct' ? P(m.value) : m.unit === 'days' ? `${Math.round(m.value)} days` : m.value.toFixed(2)}
                  {m.quality && m.quality !== 'ok' ? <span className="chip lilac kpi-q">{QUALITY[m.quality] || m.quality}</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown[0]?.as_of ? <p className="muted" style={{ fontSize: 12.5 }}>Engine numbers as of {dayLabel(shown[0].as_of, true)}.</p> : null}
    </Panel>
  );
}

// ---------- return against risk ----------
function RiskReturn({ held }) {
  const ids = [...held, 'portfolio', 'shadow:plan_shadow'];
  const paths = chunkIds(ids).map((c) => `/api/compare?ids=${encodeURIComponent(c.join(','))}&window=1Y`);
  const many = useJsonMany(paths);
  const table = Object.values(many.data).flatMap((d) => d?.table || []);
  const pts = table.map((r) => ({
    label: r.id === 'portfolio' ? 'You' : r.id === 'shadow:plan_shadow' ? 'Safe mix' : r.id,
    sym: r.kind === 'symbol' ? r.id : undefined,
    x: r.vol_pct,
    y: r.return_pct,
    color: r.id === 'portfolio' ? 'var(--s2)' : r.id === 'shadow:plan_shadow' ? 'var(--s3)' : 'var(--s1)',
    r: r.kind === 'symbol' ? 6 : 8,
  }));
  return (
    <div className="card c6" data-testid="risk-return">
      <div className="card-head">
        <span className="tag">Return against risk</span>
        <span className="chip">1 year</span>
      </div>
      {pts.length ? (
        <Scatter
          points={pts}
          xName="Volatility"
          yName="Return, 1 year"
          fmtX={(v) => P(v, 0)}
          fmtY={(v) => P(v, 0)}
          legend={
            <div className="legend">
              <span>
                <i className="dot" style={{ '--c': 'var(--s1)' }} />
                Holdings
              </span>
              <span>
                <i className="dot" style={{ '--c': 'var(--s2)' }} />
                You
              </span>
              <span>
                <i className="dot" style={{ '--c': 'var(--s3)' }} />
                Safe mix shadow
              </span>
            </div>
          }
        />
      ) : (
        <p className="empty-hint">{many.loading ? 'Measuring each holding…' : 'Needs a year of prices for at least two holdings.'}</p>
      )}
    </div>
  );
}

// ---------- drawdowns ----------
function Drawdowns({ start }) {
  const mine = useApi(`/api/engine/series?id=value&scope=portfolio&scope_id=all&start=${start}`);
  const plan = useApi(`/api/engine/series?id=value&scope=shadow&scope_id=plan_shadow&start=${start}`);
  const a = useMemo(() => alignSeries(mine.data?.rows?.filter((r) => r.date >= start), plan.data?.rows?.filter((r) => r.date >= start)), [mine.data, plan.data, start]);
  return (
    <div className="card c6" data-testid="drawdowns">
      <div className="card-head">
        <span className="tag mustard">Drawdown from the high</span>
        <span className="chip">1 year</span>
      </div>
      {a.x.length > 1 ? (
        <LineChart
          label="Drawdown from the high, you and the safe mix shadow"
          height={220}
          x={a.x}
          series={[
            { name: 'You', color: 'var(--s1)', values: drawdown(a.a) },
            { name: 'Safe mix shadow', color: 'var(--s2)', values: drawdown(a.b) },
          ]}
          fmtY={(v) => P(v, 0)}
          fmtTip={(v) => P(v, 1)}
          zero
        />
      ) : (
        <p className="empty-hint">{mine.loading ? 'Loading the value history…' : 'No value history yet.'}</p>
      )}
      <p className="empty-hint" style={{ marginTop: 6 }}>
        Value includes deposits, so a deposit can hide part of a drop.
      </p>
    </div>
  );
}

// ---------- month by month ----------
function Months({ held, start }) {
  const paths = held.map((s) => `/api/engine/prices?symbol=${encodeURIComponent(s)}&start=${start}`);
  const many = useJsonMany(paths);
  const grid = monthGrid(Object.fromEntries(held.map((s, k) => [s, many.data[paths[k]]?.rows || []]).filter(([, r]) => r.length)));
  return (
    <div className="card c6" data-testid="months">
      <div className="card-head">
        <span className="tag mint">Month by month</span>
        <span className="chip">Price return by holding</span>
      </div>
      {grid.rows.length && grid.cols.length ? (
        <Heatmap rows={grid.rows} cols={grid.labels} values={grid.values} color={(v) => divergingColor(v, 0.12)} fmt={(v) => pct(v, 1, true)} name="Month return" cellH={28} tipHead={(i, j) => `${grid.rows[i]} · ${grid.cols[j]}`} scale={<div className="scale">Down<i className="div" />Up</div>} />
      ) : (
        <p className="empty-hint">{many.loading ? 'Reading prices…' : 'No monthly prices yet.'}</p>
      )}
    </div>
  );
}

// ---------- page ----------
export default function Risk() {
  const m = useMetrics('*');
  const look = useApi('/api/engine/lookthrough?limit=8');
  const { symbols } = useLive();
  const [open, setOpen] = useState(null);
  const today = todayEt();
  const start = periodStart('1Y', today);
  const held = useMemo(() => symbols.map((s) => s.symbol), [symbols]);
  const g = (id, window = 'now') => m.get(id, { window });
  const value = val(g('value.market'));
  const vol = g('risk.vol', '252D');
  const var1m = g('risk.var95', '1M');
  const cvar1m = g('risk.cvar95', '1M');
  const sharpe = g('risk.sharpe', '1Y');
  const lt = g('risk.lookthrough', 'top10');
  const cover = val(g('risk.lookthrough_coverage'));
  const ddNow = val(g('risk.dd_now'));
  const mdd = g('risk.mdd', 'ITD');
  const corr = useMemo(() => pairMatrix(m.rows), [m.rows]);
  const shocks = scenarioItems(m.rows);
  const topLook = (look.data?.rows || []).slice(0, 8);
  const asOf = m.asOf ? dayLabel(m.asOf) : null;

  const kpis = [
    { id: 'risk.vol', label: 'Volatility', v: vol ? P(vol.value) : '—', line: `1 year, annualized${val(g('risk.vol', '63D')) != null ? ` · 3 months ${P(g('risk.vol', '63D').value)}` : ''}`, q: vol?.quality },
    { id: 'risk.sharpe', label: 'Sharpe', v: sharpe?.value != null ? sharpe.value.toFixed(2) : '—', line: `1 year${val(g('risk.sharpe', 'ITD')) != null ? ` · since start ${g('risk.sharpe', 'ITD').value.toFixed(2)}` : ''}`, q: sharpe?.quality },
    { id: 'risk.beta', label: 'Beta', v: val(g('risk.beta', '252D')) != null ? g('risk.beta', '252D').value.toFixed(2) : '—', line: 'To the S&P 500, 1 year', q: g('risk.beta', '252D')?.quality },
    { id: 'risk.eff_n', label: 'Effective holdings', v: val(g('risk.eff_n')) != null ? g('risk.eff_n').value.toFixed(1) : '—', line: `Of ${held.length} positions${val(g('risk.top1')) != null ? ` · top ${P(g('risk.top1').value, 0)}` : ''}`, q: g('risk.eff_n')?.quality },
    { id: 'risk.lookthrough', label: 'Top 10 look-through', v: lt?.value != null ? P(lt.value) : '—', line: cover != null ? `Sees through ${P(cover, 0)} of value` : 'Coverage unknown', q: lt?.quality },
    { id: 'risk.var95', label: 'Bad month', v: var1m?.value != null && value != null ? usd(-(var1m.value / 100) * value) : '—', line: `1 in 20, historical${cvar1m?.value != null && value != null ? ` · worse ones average ${usd(-(cvar1m.value / 100) * value)}` : ''}`, q: var1m?.quality, tone: 'watch' },
  ];

  return (
    <>
      <LabHero
        area="portfolio"
        kicker="Risk and statistics"
        title="Risk"
        board="Risk overview"
        big={
          ddNow == null ? (
            <b>{m.loading ? 'Checking…' : '—'}</b>
          ) : (
            <>
              <b>{P(ddNow)}</b>
              <span className="muted">
                below the high today{mdd?.value != null ? ` · worst drop ${P(mdd.value)}` : ''}
              </span>
            </>
          )
        }
      />
      <GapGate k="portfolio.risk" icon="shield" title="Risk has nothing to measure yet" hasData={m.rows.length > 0}>
        <section className="kpis kpis-6" data-testid="risk-kpis">
          {kpis.map((k, i) => (
            <Kpi key={k.id} metric={k.id} label={k.label} value={k.v} line={k.line} quality={k.q} asOf={asOf} i={i + 1} tone={k.tone} onOpen={() => setOpen(k.id)} />
          ))}
        </section>
        <section className="grid">
          <RiskReturn held={held} />
          <div className="card c6" data-testid="correlation">
            <div className="card-head">
              <span className="tag coral">How they move together</span>
              <span className="chip">Daily returns, 1 year</span>
            </div>
            {corr.syms.length > 1 ? (
              <Heatmap rows={corr.syms} cols={corr.syms} values={corr.values} name="Correlation" tipHead={(i, j) => `${corr.syms[i]} and ${corr.syms[j]}`} scale={<div className="scale">Opposite<i className="div" />Together</div>} />
            ) : (
              <p className="empty-hint">Needs a year of prices for two or more holdings.</p>
            )}
          </div>
          <Drawdowns start={start} />
          <div className="card c6" data-testid="scenarios">
            <div className="card-head">
              <span className="tag sky">Scenario shocks</span>
              <span className="chip">Today&apos;s positions</span>
            </div>
            <HBars items={shocks} fmt={(v) => usd(v)} name="Change in value" labelW={132} empty="No scenarios yet. They run with the nightly engine." />
            <p className="empty-hint" style={{ marginTop: 6 }}>
              Dollars lost if it happened again tomorrow. Replays need prices from back then; set shocks are modelled from beta and rate sensitivity.
            </p>
          </div>
          <div className="card c6" data-testid="lookthrough">
            <div className="card-head">
              <span className="tag lilac">What you really own</span>
              <span className="chip">{look.data?.as_of ? `Look-through · ${dayLabel(look.data.as_of)}` : 'Look-through'}</span>
            </div>
            <HBars
              items={topLook.map((r) => ({ label: r.holding, value: r.weight, color: r.direct ? 'var(--s1)' : 'var(--s-other)', hint: r.name && r.name !== r.holding ? r.name : undefined }))}
              fmt={(v) => P(v)}
              name="Share of value"
              tone="item"
              labelW={70}
              empty="No look-through yet. It needs N-PORT holdings for your funds."
              legend={
                <div className="legend">
                  <span>
                    <i className="dot" style={{ '--c': 'var(--s1)' }} />
                    Held directly
                  </span>
                  <span>
                    <i className="dot" style={{ '--c': 'var(--s-other)' }} />
                    Only inside funds
                  </span>
                </div>
              }
            />
            {look.data?.sectors?.length ? (
              <>
                <span className="kicker" style={{ marginTop: 10, display: 'block' }}>
                  By sector
                </span>
                <HBars items={look.data.sectors.map((s) => ({ label: s.sector, value: s.weight, color: 'var(--s5)' }))} fmt={(v) => P(v)} name="Share of value" tone="item" labelW={150} table={false} />
              </>
            ) : null}
          </div>
          <Months held={held} start={start} />
          <Factors />
        </section>
      </GapGate>
      <MetricDrawer id={open} rows={m.rows} onClose={() => setOpen(null)} />
    </>
  );
}

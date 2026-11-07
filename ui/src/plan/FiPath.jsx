import { LineChart } from '../components/LineChart.jsx';
import { useApi } from '../lib/api.js';
import { fiChart, fiHeadline, fiRange, fiState, monthYear, onTimeText, shortUsd, yearTicks } from '../lib/fi.js';
import { pct, usd } from '../lib/format.js';

export function FiPath() {
  const api = useApi('/api/engine/fi');
  const v = api.data;
  const state = fiState(v);
  const chart = fiChart(v);
  const head = fiHeadline(v);
  const range = fiRange(v);
  const progress = v?.fi_number && v?.start_value != null ? v.start_value / v.fi_number : null;

  return (
    <div className="card c12" style={{ '--i': 12 }} data-testid="fi-path" data-state={api.loading ? 'loading' : state}>
      <div className="card-head">
        <span className="tag mint">FI path</span>
        <span className="acts">
          {v?.paths ? <span className="chip">{v.paths.toLocaleString('en-US')} paths</span> : null}
          {v?.real ? <span className="chip">In today&apos;s dollars</span> : null}
        </span>
      </div>
      {api.loading && !v ? (
        <p className="empty-hint">Running the paths…</p>
      ) : api.error && !v ? (
        <p className="empty-hint">The desk API didn&apos;t answer. The FI path comes back as soon as it does.</p>
      ) : state === 'no_goal' ? (
        <p className="empty-hint">No FI goal yet. Set yearly spend and a target age in Escape Vektor; the desk draws the path on its next engine run.</p>
      ) : (
        <>
          <div className="mini-kpis fi-kpis">
            <div data-fi="number">
              <small>FI number</small>
              <b>{usd(v.fi_number)}</b>
              <span>{progress == null ? 'Start value unknown' : `${pct(progress, 1)} of the way`}</span>
            </div>
            <div data-fi="target">
              <small>Target</small>
              <b>{monthYear(v.target_date) || 'None set'}</b>
              <span>{v.required_return_pct == null ? 'No target date' : `needs ${v.required_return_pct.toFixed(1)}% a year on plan deposits`}</span>
            </div>
            <div data-fi="on-time">
              <small>By the target</small>
              <b className={v.on_time_share == null ? '' : v.on_time_share >= 0.5 ? 'up' : 'dn'}>{v.on_time_share == null ? '—' : pct(v.on_time_share, 0)}</b>
              <span>{onTimeText(v.on_time_share) || 'Waits on market history'}</span>
            </div>
            <div data-fi="date">
              <small>FI date</small>
              <b>{state === 'ok' ? head.big : '—'}</b>
              <span>{state === 'ok' ? head.line : 'Waits on market history'}</span>
            </div>
          </div>
          {state === 'ok' ? (
            <>
              <LineChart
                label={`Ten thousand market paths toward ${usd(v.fi_number)}`}
                height={260}
                x={chart.x}
                series={chart.series}
                refs={[{ y: v.fi_number, label: `FI ${shortUsd(v.fi_number)}`, start: true }]}
                vrefs={chart.target ? [{ i: chart.target, label: 'Target' }] : []}
                ticksX={yearTicks}
                tipHeadFmt={monthYear}
                fmtY={shortUsd}
                fmtTip={(x) => usd(x)}
                endLabels
              />
              <p className="legend fi-range" data-testid="fi-range">
                <span>
                  <i className="dash" style={{ '--c': 'var(--s5)' }} />
                  Fast 10% of paths <b>{range.fast}</b>
                </span>
                <span>
                  <i className="dash" style={{ '--c': 'var(--s4)' }} />
                  Slow 10% <b>{range.slow}</b>
                </span>
                <span className="muted">
                  {usd(v.monthly_deposit)} a month · {pct(v.mix?.equity, 0)} stocks · fees {v.fee_pct.toFixed(2)}%
                </span>
              </p>
              <details className="fi-notes">
                <summary>How the paths are drawn</summary>
                <ul className="lamp-notes">
                  <li>{v.method}. Not a forecast: a spread of what history allows.</li>
                  {(v.caveats || []).map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </details>
            </>
          ) : (
            <p className="empty-hint">{v?.note || 'The paths draw once the market history is in.'}</p>
          )}
        </>
      )}
    </div>
  );
}

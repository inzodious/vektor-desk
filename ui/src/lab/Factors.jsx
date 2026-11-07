import { HBars } from '../components/HBars.jsx';
import { Heatmap } from '../components/Heatmap.jsx';
import { useApi } from '../lib/api.js';
import { divergingColor } from '../lib/charts.js';
import { factorBars, holdingGrid, leanSummary } from '../lib/fi.js';
import { pct } from '../lib/format.js';

const beta = (v) => (v == null ? '—' : `${v.toFixed(2) < 0 ? '−' : ''}${Math.abs(v).toFixed(2)}`);

export function Factors() {
  const api = useApi('/api/engine/factors');
  const v = api.data;
  const bars = factorBars(v?.portfolio);
  const grid = holdingGrid(v?.holdings);
  const left = v ? 100 - (v.coverage_pct || 0) : null;

  return (
    <div className="card c12" data-testid="factors">
      <div className="card-head">
        <span className="tag mustard">What drives it</span>
        <span className="chip">{v?.window ? `Factor exposure · ${v.window.start.slice(0, 4)} to ${v.window.end.slice(0, 4)}` : 'Factor exposure · 3 years'}</span>
      </div>
      {bars.length ? (
        <>
          <p className="fi-lean" data-testid="lean">
            <b>{leanSummary(v.portfolio)}</b>
            <span className="muted">
              {' '}
              · covers {pct(v.coverage_pct / 100, 0)} of value{left >= 1 ? `; the rest has under three years of prices` : ''}
            </span>
          </p>
          <div className="grid hab">
            <div className="c6">
              <span className="kicker">Whole portfolio, weighted</span>
              <HBars items={bars} fmt={beta} name="Loading" labelW={104} />
            </div>
            <div className="c6">
              <span className="kicker">Each holding</span>
              <Heatmap
                rows={grid.rows}
                cols={grid.cols}
                colsShort={grid.short}
                values={grid.values}
                color={(x) => divergingColor(x, 1.2)}
                fmt={beta}
                name="Loading"
                label="Factor loadings by holding"
                cellH={28}
                tipHead={(i, j) => `${grid.rows[i]} · ${grid.cols[j]}`}
                scale={
                  <div className="scale">
                    Against
                    <i className="div" />
                    Toward
                  </div>
                }
              />
            </div>
          </div>
          <p className="empty-hint">Market 1.00 moves one for one with US stocks. Other bars near zero mean no lean; past ±0.15 is a lean. A description of the last three years, not a forecast.</p>
        </>
      ) : (
        <p className="empty-hint">{api.loading ? 'Reading the factors…' : v?.note || 'No factor exposure yet.'} It runs with the nightly engine once the French factor library is in.</p>
      )}
    </div>
  );
}

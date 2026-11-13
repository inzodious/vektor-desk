import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Combo } from '../components/Combo.jsx';
import { HBars } from '../components/HBars.jsx';
import { Icon } from '../components/Icon.jsx';
import { LineChart } from '../components/LineChart.jsx';
import { LabHero, Slots } from '../lab/parts.jsx';
import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { COMPARE_METRICS, DEFAULT_IDS, SLOT_COLORS, TABLE_COLS, WINDOWS, idLabel, isSymbol, parseIds, seriesRows } from '../lib/lab.js';
import { About } from '../components/About.jsx';

function useCompareState() {
  const [params, setParams] = useSearchParams();
  const ids = params.has('ids') ? parseIds(params.get('ids')) : DEFAULT_IDS;
  const win = WINDOWS.some((w) => w.v === params.get('w')) ? params.get('w') : '1Y';
  const set = (next) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        if (next.ids) n.set('ids', next.ids.join(','));
        if (next.w) n.set('w', next.w);
        return n;
      },
      { replace: true },
    );
  return { ids, win, set };
}

// ---------- side by side ----------
function SideTable({ table, colorOf }) {
  const cols = TABLE_COLS.filter((c) => table.some((r) => r[c.key] != null));
  return (
    <div className="tscroll">
      <table className="t compare-t">
        <thead>
          <tr>
            <th scope="col">Item</th>
            {cols.map((c) => (
              <th scope="col" className="r" key={c.key}>
                {c.t}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.map((r) => (
            <tr key={r.id} className="still" data-row={r.id}>
              <td>
                <span className="sym">
                  <i style={{ '--c': colorOf(r.id) }} />
                  {idLabel(r.id)}
                </span>
                <small className="muted cell-sub">Since {dayLabel(r.first, true)}</small>
              </td>
              {cols.map((c) => (
                <td className="r num" key={c.key}>
                  {r[c.key] == null ? <span className="muted">{c.none || '—'}</span> : c.fmt(r[c.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- page ----------
export default function Compare() {
  const { ids, win, set } = useCompareState();
  const api = useApi(ids.length >= 2 ? `/api/compare?ids=${encodeURIComponent(ids.join(','))}&window=${win}` : null);
  const d = api.data;
  const shown = d?.ids || [];
  const colorOf = (id) => SLOT_COLORS[Math.max(0, ids.indexOf(id))] || 'var(--s-other)';
  const rows = useMemo(() => seriesRows(d), [d]);
  const series = shown.map((id, k) => ({ name: idLabel(id), short: idLabel(id).replace(' shadow', ''), color: colorOf(id), values: rows.values[k] }));
  const winName = WINDOWS.find((w) => w.v === win)?.t || win;
  const best = d?.table?.length ? [...d.table].filter((r) => r.return_pct != null).sort((a, b) => b.return_pct - a.return_pct)[0] : null;
  const overlap = (d?.table || []).slice(1).filter((r) => r.overlap_pct != null);
  const funds = ids.filter(isSymbol).length >= 2;

  const big =
    ids.length < 2 ? (
      <>
        <b>{ids.length}</b>
        <span className="muted">item · add one more to compare</span>
      </>
    ) : best ? (
      <>
        <b>{idLabel(best.id)}</b>
        <span className="muted">
          led over {winName.toLowerCase()}, {COMPARE_METRICS[0].fmt(best.return_pct)}
        </span>
      </>
    ) : (
      <b>{api.loading ? 'Checking…' : '—'}</b>
    );

  return (
    <>
      <LabHero area="research" kicker="Compare" title="Compare" big={big} board={`Compare ${ids.map(idLabel).join(', ')} · ${win}`} />
      <section className="lab-bar">
        <Slots ids={ids} onRemove={(id) => set({ ids: ids.filter((x) => x !== id) })} onAdd={(id) => set({ ids: [...ids, id] })} />
        <Combo label="Window" options={WINDOWS} value={win} onChange={(w) => set({ w })} />
      </section>
      {d?.note ? (
        <p className="note" role="status">
          <Icon name="info" />
          <span>{d.note}</span>
        </p>
      ) : null}
      {ids.length < 2 ? (
        <section className="card">
          <p className="empty-hint">Compare needs two to five items. Add a fund, a stock, your portfolio or a shadow.</p>
        </section>
      ) : api.error && !d ? (
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">{api.error.status === 400 ? "Can't compare that" : "The desk API didn't answer"}</span>
            {api.error.status === 400 ? null : (
              <button className="btn sm" type="button" onClick={api.reload}>
                <Icon name="swap" />
                Retry
              </button>
            )}
          </div>
          <p className="muted">{api.error.status === 400 ? api.error.message : 'The comparison comes back as soon as it does.'}</p>
        </section>
      ) : (
        <>
          <section className="grid">
            <div className={`card ${funds ? 'c8' : 'c12'}`} data-testid="growth">
              <div className="card-head">
                <span className="tag">Growth of 100</span>
                <span className="chip">{d ? `${dayLabel(d.start, true)} to ${dayLabel(d.end, true)} · total return` : 'Total return'}</span>
              </div>
              {d && rows.x.length > 1 ? (
                <LineChart label={`Growth of 100 over ${winName}`} height={270} x={rows.x} series={series} refs={[{ y: 100 }]} fmtY={(v) => v.toFixed(0)} fmtTip={(v) => v.toFixed(1)} endLabels />
              ) : (
                <p className="empty-hint">{api.loading ? 'Lining up the histories…' : 'Not enough shared history in this window.'}</p>
              )}
            </div>
            {funds ? (
              <div className="card c4" data-testid="overlap">
                <div className="card-head">
                  <span className="tag mustard">Overlap with {shown[0] ? idLabel(shown[0]) : 'the first'}</span>
                  <span className="chip">Look-through, N-PORT</span>
                </div>
                {overlap.length ? (
                  <HBars items={overlap.map((r) => ({ label: idLabel(r.id), value: r.overlap_pct, color: colorOf(r.id) }))} fmt={(v) => `${Math.round(v)}%`} name="Overlap" labelW={96} />
                ) : (
                  <p className="empty-hint">No look-through yet. Overlap shows once the engine has N-PORT holdings for these funds.</p>
                )}
                <p className="empty-hint" style={{ marginTop: 6 }}>
                  Share of each fund that the first item also holds.
                </p>
              </div>
            ) : null}
          </section>
          {d?.table?.length ? (
            <>
              <section className="grid mult" data-testid="multiples">
                {COMPARE_METRICS.filter((m) => d.table.some((r) => r[m.key] != null)).map((m) => (
                  <div className="card c4" key={m.key} data-metric={m.key}>
                    <div className="card-head">
                      <span className={`tag ${m.tag}`}>{m.key === 'return_pct' ? `Return, ${winName.toLowerCase()}` : m.t}</span>
                    </div>
                    <HBars
                      items={d.table.map((r) => ({ label: idLabel(r.id).replace(' shadow', ''), value: r[m.key], color: m.tone === 'item' ? colorOf(r.id) : undefined, note: m.none }))}
                      fmt={m.fmt}
                      name={m.t}
                      tone={m.tone}
                      labelW={96}
                      table={false}
                      empty={m.none ? `${m.none} for these.` : 'No values.'}
                    />
                  </div>
                ))}
              </section>
              <section className="card" data-testid="side-by-side">
                <div className="card-head">
                  <span className="tag">Side by side</span>
                  <span className="chip">Table view of every chart above</span>
                </div>
                <SideTable table={d.table} colorOf={colorOf} />
                <About testid="compare-about">
                  <p>
                    Averaged yearly returns only show for a year or more. Correlation and beta are against {idLabel(shown[0])}.{shown.some(isSymbol) ? ' Click a symbol for its sheet.' : ''}
                  </p>
                </About>
              </section>
            </>
          ) : null}
        </>
      )}
    </>
  );
}

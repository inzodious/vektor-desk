import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Panel } from '../components/Panel.jsx';
import { Icon } from '../components/Icon.jsx';
import { LineChart } from '../components/LineChart.jsx';
import { accountLabel, priceStatus, useLive } from './context.js';
import { useApi } from '../lib/api.js';
import { count, etStamp, pct, px, usd } from '../lib/format.js';
import { dayLabel, periodStart } from '../lib/charts.js';
import { useConsole } from '../research/consoleContext.js';
import { filingChip, freshness, verdictOf } from '../lib/research.js';
import { PlanBlock, RoleChip, VersionChip } from '../plan/PlanParts.jsx';

function PriceHistory({ symbol, row, lots }) {
  const last = new Date().toISOString().slice(0, 10);
  const start = periodStart('1Y', last);
  const prices = useApi(`/api/engine/prices?symbol=${encodeURIComponent(symbol)}&start=${start}`);
  const pts = useMemo(() => (Array.isArray(prices.data?.rows) ? prices.data.rows.filter((p) => p.close != null) : []), [prices.data]);
  const avg = row && row.shares && row.cost ? row.cost / row.shares : null;
  const markers = useMemo(() => {
    if (!pts.length) return [];
    return lots
      .filter((l) => l.acquired)
      .map((l) => {
        const i = pts.findIndex((p) => p.date >= l.acquired.slice(0, 10));
        return i < 0 ? null : { i, label: `Bought ${count(Math.round(l.shares * 1000) / 1000)} sh, ${accountLabel(l.account)}` };
      })
      .filter(Boolean);
  }, [pts, lots]);

  if (prices.loading) return <p className="empty-hint">Loading price history…</p>;
  if (!pts.length) return <p className="empty-hint">No price history for {symbol} yet. It fills in after the nightly backfill.</p>;
  return (
    <LineChart
      label={`${symbol} price, one year`}
      height={200}
      x={pts.map((p) => p.date)}
      series={[{ name: symbol, color: 'var(--s1)', values: pts.map((p) => p.close) }]}
      fmtY={(v) => (v >= 100 ? `$${Math.round(v)}` : `$${px(v)}`)}
      fmtTip={(v) => `$${px(v)}`}
      refs={avg ? [{ y: avg, label: `Your average $${px(avg)}` }] : []}
      markers={markers}
    />
  );
}

// ---------- dossier ----------
function FilingBit({ symbol }) {
  const api = useApi(`/api/engine/research?symbol=${encodeURIComponent(symbol)}`);
  const f = filingChip(api.data);
  if (!f) return null;
  return (
    <div data-testid="sheet-filing" data-direction={f.direction} data-lane={f.lane_open ? 'open' : 'none'}>
      <div className="card-head" style={{ marginBottom: 4 }}>
        <span className="kicker">Latest filing read</span>
        <span className="acts">
          <span className={`chip ${f.dir.tone}`} data-testid="filing-chip">
            {f.dir.t}
            {f.sure ? ` · ${f.sure}` : ''}
          </span>
          {f.lane_open ? (
            <span className="chip lilac" data-testid="filing-lane">
              On the filings lane’s paper book
            </span>
          ) : null}
        </span>
      </div>
      <div className="sheet-filing">
        <b>
          {f.form}
          {f.event ? ` · ${f.event}` : ''}
        </b>
        {f.rationale ? <span>{f.rationale}</span> : null}
        <small className="muted">
          Filed {f.filed_at ? dayLabel(f.filed_at.slice(0, 10), true) : '—'}
          {f.horizon_days ? ` · read over ${f.horizon_days} days` : ''}
          {f.more > 0 ? ` · ${f.more} earlier ${f.more === 1 ? 'read' : 'reads'} in Research` : ''}
        </small>
      </div>
    </div>
  );
}

function DossierBit({ symbol, onClose }) {
  const api = useApi(`/api/agents/dossiers/${encodeURIComponent(symbol)}`);
  const { openConsole } = useConsole();
  const entry = api.data?.dossier ? api.data : null;
  const v = verdictOf(entry);
  const f = entry ? freshness(entry.created_at) : null;
  return (
    <div data-testid="sheet-dossier">
      <div className="card-head" style={{ marginBottom: 4 }}>
        <span className="kicker">Dossier</span>
        <span className="acts">
          {v ? <span className={`chip ${v.tone}`}>{v.t}</span> : null}
          {f ? <span className={`chip ${f.tone}`}>{f.t}</span> : null}
        </span>
      </div>
      {entry ? (
        <div className="bb">
          <div className="bull">
            <b>Thesis</b>
            {entry.dossier.thesis}
          </div>
          <div className="bear">
            <b>Bear case</b>
            {entry.dossier.bear_case}
          </div>
        </div>
      ) : (
        <p className="empty-hint">{api.loading ? 'Looking for a dossier…' : `No dossier on ${symbol} yet.`}</p>
      )}
      <div className="sheet-acts">
        {entry ? (
          <Link className="btn sm ghost" to={`/research?s=${encodeURIComponent(symbol)}`} onClick={onClose}>
            <Icon name="book" />
            Open the dossier
          </Link>
        ) : null}
        <button
          className="btn sm ghost"
          type="button"
          onClick={() => {
            onClose();
            openConsole({ desk: 'research', symbol, question: entry ? `Refresh the ${symbol} dossier` : `Deep dive on ${symbol}` });
          }}
        >
          <Icon name="telescope" />
          {entry ? 'Ask for a refresh' : 'Request a deep dive'}
        </button>
      </div>
    </div>
  );
}

// ---------- stock plan ----------
function PlanBit({ symbol, onClose }) {
  const api = useApi(`/api/decisions/plans/${encodeURIComponent(symbol)}`);
  const facts = useApi(`/api/engine/planfacts?symbol=${encodeURIComponent(symbol)}`);
  const meta = useApi('/api/decisions/plans');
  const plan = api.data?.plan?.symbol === symbol ? api.data.plan : null;
  const fact = (facts.data?.rows || []).find((r) => r.symbol === symbol) || null;
  if (!plan && !fact) return null;
  return (
    <div data-testid="sheet-plan" data-status={plan?.status || 'none'}>
      <div className="card-head" style={{ marginBottom: 4 }}>
        <span className="kicker">Stock plan</span>
        <span className="acts">
          <RoleChip plan={plan} />
          <VersionChip plan={plan} />
        </span>
      </div>
      <PlanBlock symbol={symbol} plan={plan} fact={fact} lotMethods={meta.data?.lot_methods} showNext />
      {!plan ? <p className="empty-hint">No plan for {symbol} yet. The zones above are a starting point from its monthly swing.</p> : null}
      <div className="sheet-acts">
        <Link className="btn sm ghost" to={`/portfolio/stocks?symbol=${encodeURIComponent(symbol)}`} onClick={onClose}>
          <Icon name="plan" />
          {plan ? 'Open the plan' : 'Write a plan'}
        </Link>
      </div>
    </div>
  );
}

function SheetBody({ symbol, onClose }) {
  const ctx = useLive();
  const row = ctx.symbols.find((s) => s.symbol === symbol);
  const cost = ctx.cost[symbol];
  const lotsApi = useApi(`/api/engine/lots?symbol=${encodeURIComponent(symbol)}`);
  const lots = lotsApi.data?.lots || [];
  const status = priceStatus(ctx.live, row);
  const gain = row && cost ? row.value - cost : null;
  const held = { ...row, cost };

  if (!row) {
    return (
      <>
        <div className="note">
          <Icon name="eye" />
          <span>
            <b style={{ color: 'var(--ink)' }}>Not held.</b> {symbol} isn&apos;t in the latest holdings, so this shows closes and research only.
          </span>
        </div>
        <div>
          <span className="kicker">Price, 1 year</span>
          <PriceHistory symbol={symbol} row={null} lots={[]} />
        </div>
        <PlanBit symbol={symbol} onClose={onClose} />
        <FilingBit symbol={symbol} />
        <DossierBit symbol={symbol} onClose={onClose} />
      </>
    );
  }

  return (
    <>
      <div className="sheet-price">
        <b className="num" data-live={symbol}>
          ${px(row.price)}
        </b>
        <span className={row.day_change >= 0 ? 'up' : 'dn'} style={{ fontWeight: 800 }}>
          {usd(row.price - row.prev_close, { cents: true, sign: true })} · {pct(row.change_pct, 2, true)} today
        </span>
        {status ? (
          <span className={`chip ${status.tone}`}>
            {status.pulse ? <i className="pulse" style={{ width: 6, height: 6 }} /> : null}
            {status.text}
          </span>
        ) : null}
      </div>
      <div>
        <div className="card-head" style={{ marginBottom: 4 }}>
          <span className="kicker">Price, 1 year</span>
          <span className="muted" style={{ fontSize: 11.5 }}>
            Dots are your buys · dashed line is your average cost
          </span>
        </div>
        <PriceHistory symbol={symbol} row={held} lots={lots} />
      </div>
      <div className="mini-kpis">
        <div>
          <small>Position</small>
          <b>{usd(row.value)}</b>
        </div>
        <div>
          <small>Gain</small>
          <b className={gain == null ? '' : gain >= 0 ? 'up' : 'dn'}>{gain == null ? '—' : usd(gain, { sign: true })}</b>
        </div>
        <div>
          <small>Today</small>
          <b className={row.day_change >= 0 ? 'up' : 'dn'}>{usd(row.day_change, { sign: true })}</b>
        </div>
      </div>
      <PlanBit symbol={symbol} onClose={onClose} />
      <div>
        <span className="kicker">By account</span>
        <div className="tscroll">
          <table className="t">
            <thead>
              <tr>
                <th scope="col">Account</th>
                <th scope="col" className="r">
                  Shares
                </th>
                <th scope="col" className="r">
                  Value
                </th>
                <th scope="col" className="r">
                  Today
                </th>
              </tr>
            </thead>
            <tbody>
              {row.accounts.map((a) => (
                <tr key={a.account} className="still">
                  <td>{accountLabel(a.account)}</td>
                  <td className="r">{count(Math.round(a.shares * 1000) / 1000)}</td>
                  <td className="r">{usd(a.value)}</td>
                  <td className={`r ${a.day_change >= 0 ? 'up' : 'dn'}`}>{usd(a.day_change, { sign: true })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div>
        <div className="card-head" style={{ marginBottom: 2 }}>
          <span className="kicker">Lots</span>
          {lotsApi.data?.files?.[0]?.as_of ? <span className="muted" style={{ fontSize: 11.5 }}>From the {dayLabel(lotsApi.data.files[0].as_of.slice(0, 10))} export</span> : null}
        </div>
        {lots.length ? (
          <div className="tscroll">
            <table className="t">
              <thead>
                <tr>
                  <th scope="col">Acquired</th>
                  <th scope="col">Account</th>
                  <th scope="col" className="r">
                    Shares
                  </th>
                  <th scope="col" className="r">
                    Cost
                  </th>
                  <th scope="col" className="r">
                    Gain
                  </th>
                  <th scope="col">Term</th>
                </tr>
              </thead>
              <tbody>
                {lots.map((l) => {
                  const cps = l.cost_per_share ?? (l.cost && l.shares ? l.cost / l.shares : null);
                  const g = cps != null ? l.shares * (row.price - cps) : null;
                  return (
                    <tr key={l.id} className="still">
                      <td>{l.acquired ? dayLabel(l.acquired.slice(0, 10), true) : '—'}</td>
                      <td>{accountLabel(l.account)}</td>
                      <td className="r">{count(Math.round(l.shares * 1000) / 1000)}</td>
                      <td className="r">{cps != null ? `$${px(cps)}` : '—'}</td>
                      <td className={`r ${g == null ? '' : g >= 0 ? 'up' : 'dn'}`}>{g == null ? '—' : usd(g, { sign: true })}</td>
                      <td>{l.term ? l.term.charAt(0).toUpperCase() + l.term.slice(1) : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-hint">No lot export yet. Drop one in the desk inbox and lots show here.</p>
        )}
      </div>
      <FilingBit symbol={symbol} />
      <DossierBit symbol={symbol} onClose={onClose} />
      {ctx.live?.as_of ? <p className="muted" style={{ fontSize: 11.5 }}>Quotes as of {etStamp(ctx.live.as_of)}</p> : null}
    </>
  );
}

export function SymbolSheet({ symbol, onClose }) {
  const ctx = useLive();
  const row = ctx.symbols.find((s) => s.symbol === symbol);
  const name = ctx.names[symbol];
  const head = (
    <span className="sym" style={{ fontSize: 20 }}>
      <i style={{ '--c': 'var(--s1)' }} />
      {symbol}
    </span>
  );
  return (
    <Panel
      open={!!symbol}
      onClose={onClose}
      kind="sheet"
      label={`${symbol} symbol sheet`}
      title={head}
      sub={name}
      crumbs={[{ label: row ? 'Holding' : 'Symbol' }, ...(row ? [{ label: row.accounts.map((a) => accountLabel(a.account)).join(' + ') }] : [])]}
    >
      {symbol ? <SheetBody symbol={symbol} onClose={onClose} /> : null}
    </Panel>
  );
}

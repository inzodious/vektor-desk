import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Combo } from '../components/Combo.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { accountLabel } from '../live/context.js';
import { postJson, useApi } from '../lib/api.js';
import { DECISION_TABS, STATUS, journalPage, kindName, latestScore, originName, reasonOf, scoreOf, scoresOn } from '../lib/decisions.js';
import { parseDay } from '../lib/charts.js';
import { plural, usd } from '../lib/format.js';
import { GapNote } from '../start/EmptyState.jsx';
import { About } from '../components/About.jsx';

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const SHOW_UNMATCHED = 5;
const LIMIT = 500;
const FILTERS = ['origin', 'status', 'kind', 'symbol'];

function stampOf(day) {
  const d = parseDay(day);
  return `${MON[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

function statusWord(d) {
  if (d.override && ['approved', 'placed', 'filled', 'done'].includes(d.status)) return { t: 'Override', tone: 'watch' };
  return STATUS[d.status] || { t: d.status, tone: '' };
}

// ---------- ledger ----------
function Ledger({ days, filtered }) {
  if (!days.length) return <p className="empty-hint">{filtered ? 'Nothing matches those filters.' : 'Nothing logged yet. Every approve, dismiss and pass lands here.'}</p>;
  return days.map((g) => (
    <div className="ledger-day" key={g.day}>
      <span className="stamp-day">{stampOf(g.day)}</span>
      <div className="rows">
        {g.items.map((d) => {
          const st = statusWord(d);
          const last = latestScore(d);
          const why = reasonOf(d);
          const amount = d.amount_usd ?? d.fill?.amount ?? null;
          return (
            <div className={`row ledger-row${d.symbol ? '' : ' still'}`} key={d.id} data-sym={d.symbol || undefined} tabIndex={d.symbol ? 0 : undefined} data-status={d.status}>
              <span className="l">
                <span className="sym">
                  <i style={{ '--c': d.symbol ? 'var(--s1)' : 'var(--ink-3)' }} />
                  {d.symbol || kindName(d.kind)}
                </span>
                <small>{d.symbol ? kindName(d.kind) : d.title}</small>
              </span>
              <span>
                <span className={`chip ${st.tone}`}>{st.t}</span>
                {why ? <small className="why">“{why}”</small> : null}
              </span>
              <span className="origin">{originName(d.origin)}</span>
              <span className="v">
                {amount != null ? usd(amount) : '—'}
                <small className={last == null ? '' : last.v >= 0 ? 'up' : 'dn'} data-score={last?.w}>
                  {last == null ? (amount != null ? `Scores ${scoresOn(d)}` : '') : `${usd(last.v, { sign: true })} vs the safe mix, ${last.t}`}
                </small>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  ));
}

// ---------- unmatched ----------
function Unmatched({ trades, onLogged }) {
  const [open, setOpen] = useState(null);
  const [why, setWhy] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [all, setAll] = useState(false);
  const shown = all ? trades : trades.slice(0, SHOW_UNMATCHED);
  const save = async (t) => {
    setBusy(true);
    setErr(null);
    try {
      await postJson(`/api/decisions/unmatched/${t.activity_id}/log`, { thesis: why.trim() || null, reason: why.trim() || null });
      setOpen(null);
      setWhy('');
      onLogged();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card" data-testid="unmatched">
      <div className="card-head">
        <span className="tag sky">Unmatched trades</span>
        {trades.length ? <span className="chip watch">{trades.length}</span> : <span className="chip ok">None</span>}
      </div>
      {trades.length ? (
        <>
          <div className="rows">
            {shown.map((t) => {
              const d = parseDay(t.date);
              const isOpen = open === t.activity_id;
              return (
                <div key={t.activity_id} className="um">
                  <div className="row still">
                    <span className="l">
                      <span className="datebox">
                        <small>{MON[d.getUTCMonth()]}</small>
                        <b>{d.getUTCDate()}</b>
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <b>
                          {t.kind === 'sell' ? 'Sold' : 'Bought'} {t.quantity != null ? Number(t.quantity.toFixed(4)) : ''} {t.symbol}
                        </b>
                        <small>
                          {accountLabel(t.accountKey)} · {usd(Math.abs(t.amount || 0), { cents: true })}
                        </small>
                      </span>
                    </span>
                    <button className="btn sm ghost" type="button" aria-expanded={isOpen} onClick={() => { setOpen(isOpen ? null : t.activity_id); setWhy(''); setErr(null); }}>
                      {isOpen ? 'Cancel' : 'Log it'}
                    </button>
                  </div>
                  {isOpen ? (
                    <div className="override-row um-form">
                      <div className="field" style={{ flex: 1, minWidth: 160 }}>
                        <input aria-label={`Why you ${t.kind === 'sell' ? 'sold' : 'bought'} ${t.symbol}`} placeholder="One line on why" value={why} maxLength={300} onChange={(e) => setWhy(e.target.value)} />
                      </div>
                      <button className="btn sm" type="button" disabled={busy} onClick={() => save(t)}>
                        <Icon name="check" />
                        Save to the journal
                      </button>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
          {trades.length > SHOW_UNMATCHED ? (
            <button className="btn sm ghost" type="button" style={{ marginTop: 8 }} onClick={() => setAll(!all)}>
              {all ? 'Show fewer' : `Show ${trades.length - SHOW_UNMATCHED} more`}
            </button>
          ) : null}
          {err ? (
            <p className="act-err" role="alert">
              {err}
            </p>
          ) : null}
          <About label="What counts as unlogged" testid="unlogged-about">
            <p>Fidelity trades with no decision record. Logging one after the fact counts, but it shows as logged late.</p>
          </About>
        </>
      ) : (
        <p className="empty-hint">Every Fidelity trade in the last 90 days has a decision record.</p>
      )}
    </div>
  );
}

// ---------- page ----------
export default function Journal() {
  const journal = useApi(`/api/decisions/journal?limit=${LIMIT}`);
  const [params, setParams] = useSearchParams();
  const summary = useApi('/api/decisions/summary');
  const unmatched = useApi('/api/decisions/unmatched');
  const origin = params.get('origin') || 'all';
  const status = params.get('status') || 'all';
  const kind = params.get('kind') || 'all';
  const sym = params.get('symbol') || 'all';
  const filtered = FILTERS.some((k) => params.get(k));
  const set = (next) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        Object.entries(next).forEach(([k, v]) => (v == null || v === 'all' || v === 1 ? n.delete(k) : n.set(k, String(v))));
        if (!('page' in next)) n.delete('page');
        return n;
      },
      { replace: true },
    );
  const days = useMemo(() => journal.data?.days || [], [journal.data]);
  const items = useMemo(() => days.flatMap((g) => g.items), [days]);
  const origins = useMemo(() => [{ v: 'all', t: 'Everyone' }, ...[...new Set(items.map((d) => d.origin))].map((o) => ({ v: o, t: originName(o) }))], [items]);
  const statuses = useMemo(() => [{ v: 'all', t: 'Any status' }, ...[...new Set(items.map((d) => statusWord(d).t))].map((t) => ({ v: t, t }))], [items]);
  const kinds = useMemo(() => [{ v: 'all', t: 'Any kind' }, ...[...new Set(items.map((d) => d.kind).filter(Boolean))].map((k) => ({ v: k, t: kindName(k) }))], [items]);
  const symbols = useMemo(() => [{ v: 'all', t: 'Any symbol' }, ...[...new Set(items.map((d) => d.symbol).filter(Boolean))].sort().map((x) => ({ v: x, t: x }))], [items]);
  const shown = useMemo(
    () =>
      days
        .map((g) => ({
          ...g,
          items: g.items.filter((d) => (origin === 'all' || d.origin === origin) && (status === 'all' || statusWord(d).t === status) && (kind === 'all' || d.kind === kind) && (sym === 'all' || d.symbol === sym)),
        }))
        .filter((g) => g.items.length),
    [days, origin, status, kind, sym],
  );
  const pg = journalPage(shown, params.get('page'));
  const turn = (to) => {
    set({ page: to });
    document.querySelector('[data-testid="journal"]')?.scrollIntoView({ block: 'start' });
  };
  const s = summary.data;
  const scored = (o) => items.filter((d) => !!d.override === o && scoreOf(d) != null).map((d) => scoreOf(d));
  const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
  const ovAvg = avg(scored(true));
  const clAvg = avg(scored(false));
  const tabs = <Subtabs label="Decisions views" tabs={DECISION_TABS} />;
  const cover = s?.coverage;

  if (journal.loading) return <Hero kicker="Decisions · Journal" title="Journal" art="decisions" big={<b>Checking…</b>} foot={tabs} />;

  if (journal.error && !journal.data) {
    return (
      <>
        <Hero kicker="Decisions · Journal" title="Journal" art="decisions" big={<b>No answer</b>} foot={tabs} />
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button className="btn sm" type="button" onClick={journal.reload}>
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">The journal comes back as soon as it does.</p>
        </section>
      </>
    );
  }

  return (
    <>
      <Hero
        kicker="Decisions · Journal"
        title="Journal"
        art="decisions"
        big={
          cover == null ? (
            <>
              <b>{plural(items.length, 'entry', 'entries')}</b>
              <span className="muted">no Fidelity trades to match yet</span>
            </>
          ) : (
            <>
              <b>{Math.round(cover * 100)}%</b>
              <span className="muted">of Fidelity trades in {s.coverage_window_days} days have a decision record</span>
            </>
          )
        }
        foot={tabs}
      />
      <GapNote k="decisions.journal" />
      <section className="grid">
        <div className="card c8 top" style={{ '--i': 1 }} data-testid="journal" data-page={pg.page} data-pages={pg.pages} data-total={pg.total}>
          <div className="card-head">
            <span className="tag coral">Decision journal</span>
            <span className="acts">
              <span className="chip" data-testid="journal-count">
                {filtered ? `${pg.total} of ${plural(items.length, 'entry', 'entries')}` : plural(items.length, 'entry', 'entries')}
              </span>
              {filtered ? (
                <button className="link" type="button" onClick={() => set({ origin: null, status: null, kind: null, symbol: null })} data-testid="journal-clear">
                  Clear filters
                </button>
              ) : null}
            </span>
          </div>
          <div className="journal-filters" data-testid="journal-filters">
            <Combo label="Origin" options={origins} value={origin} onChange={(v) => set({ origin: v })} />
            <Combo label="Status" options={statuses} value={status} onChange={(v) => set({ status: v })} />
            <Combo label="Kind" options={kinds} value={kind} onChange={(v) => set({ kind: v })} />
            <Combo label="Symbol" options={symbols} value={sym} onChange={(v) => set({ symbol: v })} />
          </div>
          <Ledger days={pg.days} filtered={filtered} />
          {pg.pages > 1 ? (
            <nav className="pager" aria-label="Journal pages" data-testid="journal-pager">
              <button className="btn sm ghost" type="button" disabled={pg.page <= 1} onClick={() => turn(pg.page - 1)}>
                <Icon name="right" className="mirror" />
                Newer
              </button>
              <span className="muted" aria-live="polite">
                {pg.from}–{pg.to} of {pg.total} · page {pg.page} of {pg.pages}
              </span>
              <button className="btn sm ghost" type="button" disabled={pg.page >= pg.pages} onClick={() => turn(pg.page + 1)}>
                Older
                <Icon name="right" />
              </button>
            </nav>
          ) : null}
          {journal.data?.count >= LIMIT ? <p className="empty-hint">Showing the latest {LIMIT} entries.</p> : null}
        </div>
        <div className="stack c4">
          <div className="card" data-testid="streak">
            <div className="card-head">
              <span className="tag mint">Discipline streak</span>
            </div>
            {s ? (
              <>
                <div className="streak">
                  <b>{s.streak_days}</b>
                  <span className="muted">{s.streak_days === 1 ? 'day' : 'days'} without an unlogged trade</span>
                </div>
                <About label="What resets it" testid="streak-about">
                  <p>An unmatched Fidelity trade or one logged late resets it. Overrides with a reason never do.</p>
                </About>
              </>
            ) : (
              <p className="empty-hint">Counting…</p>
            )}
          </div>
          <div className="card" data-testid="overrides">
            <div className="card-head">
              <span className="tag mustard">Overrides against clean</span>
            </div>
            {s ? (
              <div className="mini-kpis two">
                <div>
                  <small>Clean</small>
                  <b>{s.clean}</b>
                  <span className={clAvg == null ? 'muted' : clAvg >= 0 ? 'up' : 'dn'}>{clAvg == null ? 'Not scored yet' : `${usd(clAvg, { sign: true })} avg vs the safe mix`}</span>
                </div>
                <div>
                  <small>Overrides</small>
                  <b>{s.overrides}</b>
                  <span className={ovAvg == null ? 'muted' : ovAvg >= 0 ? 'up' : 'dn'}>{ovAvg == null ? 'Not scored yet' : `${usd(ovAvg, { sign: true })} avg vs the safe mix`}</span>
                </div>
              </div>
            ) : (
              <p className="empty-hint">Counting…</p>
            )}
            <p className="empty-hint" style={{ marginTop: 6 }}>
              Scores compare each call against the safe mix 30 days later.
            </p>
          </div>
          <Unmatched
            trades={unmatched.data?.trades || []}
            onLogged={() => {
              unmatched.reload();
              journal.reload();
              summary.reload();
            }}
          />
        </div>
      </section>
    </>
  );
}

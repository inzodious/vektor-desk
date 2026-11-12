import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { dayLabel, dayWords } from '../lib/charts.js';
import { etStamp, usd } from '../lib/format.js';
import { statusWord } from '../lib/convictions.js';
import { accountName, bandLine, debriefState, decisionRows, diffText, eventWord, kpis, ledger, moverLine, moverRows, riskFacts, scoreLine, versusLine, versusRows, versusScale } from '../lib/results.js';
import { signedPct } from '../lib/strategy.js';
import { EmptyState } from '../start/EmptyState.jsx';

const SHOW = 8;

function Sym({ symbol }) {
  if (!symbol) return null;
  return (
    <button type="button" className="sym sym-btn" data-sym={symbol}>
      {symbol}
    </button>
  );
}

// ---------- numbers strip ----------
export function Numbers({ pack, i }) {
  return (
    <div className="card c12 rs-kpis" style={{ '--i': i }} data-testid="rs-kpis">
      {kpis(pack).map((k) => (
        <div key={k.id} data-kpi={k.id}>
          <small>{k.label}</small>
          <b className={k.tone || undefined}>{k.value}</b>
          {k.sub ? <span>{k.sub}</span> : null}
        </div>
      ))}
    </div>
  );
}

// ---------- debrief ----------
export function Debrief({ review }) {
  const d = review.debrief;
  const st = debriefState(review);
  return (
    <div className="card rs-debrief" data-testid="rs-debrief" data-state={st.state}>
      <div className="card-head">
        <span className="tag coral">Debrief</span>
        <span className="acts">
          {d?.written_at ? (
            <span className="chip" data-testid="rs-written">
              {review.kind === 'day' && dayWords(review.end) ? `About ${dayWords(review.end)} · written ` : 'Written '}
              {etStamp(d.written_at)}
            </span>
          ) : null}
        </span>
      </div>
      {d ? (
        <>
          <p className="rs-headline">{d.headline}</p>
          {st.hint ? (
            <p className="rs-stale" role="note">
              <span className="chip watch">Heads up</span> {st.hint}
            </p>
          ) : null}
          <dl className="rs-words">
            {d.what_happened ? (
              <div>
                <dt>What happened</dt>
                <dd>{d.what_happened}</dd>
              </div>
            ) : null}
            {d.why ? (
              <div>
                <dt>Why</dt>
                <dd>{d.why}</dd>
              </div>
            ) : null}
            {d.against_decisions ? (
              <div>
                <dt>Against your decisions</dt>
                <dd>{d.against_decisions}</dd>
              </div>
            ) : null}
            {d.watch?.length ? (
              <div>
                <dt>Watch</dt>
                <dd>
                  <ul>
                    {d.watch.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </dd>
              </div>
            ) : null}
          </dl>
        </>
      ) : (
        <div data-testid="rs-debrief-wait">
          <EmptyState k="results.debrief" slim icon="clock" why={`${st.hint} The numbers on this page are already final enough to read.`} />
        </div>
      )}
    </div>
  );
}

export function NextSteps({ review }) {
  const steps = review.debrief?.next_steps || [];
  return (
    <div className="card rs-steps" data-testid="rs-steps" data-count={steps.length}>
      <div className="card-head">
        <span className="tag mint">Next steps</span>
        <span className="acts">
          <Link className="link" to="/decisions">
            Open the queue
          </Link>
        </span>
      </div>
      {steps.length ? (
        <ol className="rs-step-list">
          {steps.map((s, n) => (
            <li key={s.text}>
              <span className="rs-step-n" aria-hidden="true">
                {n + 1}
              </span>
              <span className="rs-step-text">{s.text}</span>
              <Sym symbol={s.symbol} />
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty-hint">{review.debrief ? 'Nothing to do. Stay the course.' : 'Next steps come with the debrief.'}</p>
      )}
      <p className="muted rs-foot">Suggestions only. Orders still go through the queue and Preflight.</p>
    </div>
  );
}

// ---------- versus ----------
export function Versus({ pack }) {
  const rows = versusRows(pack);
  const scale = versusScale(rows);
  const line = versusLine(pack);
  return (
    <div className="card rs-versus" data-testid="rs-versus" data-count={rows.length}>
      <div className="card-head">
        <span className="tag sky">Versus</span>
        <span className="acts">{line ? <span className="chip">{line}</span> : null}</span>
      </div>
      {rows.length > 1 ? (
        <>
          <ul className="rs-vs">
            {rows.map((r) => (
              <li key={r.id} data-vs={r.id} data-kind={r.kind}>
                <span className="rs-vs-name">
                  <b>{r.name}</b>
                  <small>{diffText(r)}</small>
                </span>
                <span className="rs-vs-track" role="img" aria-label={`${r.name} ${signedPct(r.return_pct, 2)}`} style={{ '--zero': `${scale.zero}%` }}>
                  <i className={r.return_pct >= 0 ? 'pos' : 'neg'} style={{ width: `${Math.max(1, scale.width(r.return_pct))}%` }} />
                </span>
                <b className="rs-vs-num">{signedPct(r.return_pct, 2)}</b>
              </li>
            ))}
          </ul>
          <p className="muted rs-foot">Same starting dollars and the same deposits on the same days.</p>
        </>
      ) : (
        <p className="empty-hint">The S&amp;P 500 and the mixes show here once their prices are in for this period.</p>
      )}
    </div>
  );
}

// ---------- movers ----------
export function Movers({ pack }) {
  const rows = moverRows(pack.movers);
  return (
    <div className="card rs-movers" data-testid="rs-movers" data-count={rows.length}>
      <div className="card-head">
        <span className="tag mustard">What moved it</span>
        <span className="acts">{pack.movers?.count ? <span className="chip">{pack.movers.count} holdings</span> : null}</span>
      </div>
      {rows.length ? (
        <ul className="rs-mv">
          {rows.map((m) => (
            <li key={m.symbol || 'other'} data-mover={m.symbol || 'other'} data-tone={m.tone}>
              <span className="rs-mv-name">
                {m.symbol ? <Sym symbol={m.symbol} /> : <b>Everything else</b>}
                <small>{m.symbol ? moverLine(m) : m.name}</small>
              </span>
              <span className="rs-mv-track" aria-hidden="true">
                <i className={m.tone} style={{ width: `${Math.max(2, m.share)}%` }} />
              </span>
              <b className={`rs-mv-num ${m.tone}`}>{usd(m.contribution_usd, { sign: true })}</b>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-hint">Nothing moved. A flat period.</p>
      )}
    </div>
  );
}

// ---------- flows and trades ----------
function LedgerRow({ r }) {
  const [mon, day] = dayLabel(r.date).split(' ');
  return (
    <li className="rs-lg-row" data-type={r.type}>
      <span className="disc-stamp" aria-hidden="true">
        <b>{day}</b>
        <small>{mon}</small>
      </span>
      <span className="rs-lg-main">
        <span>
          <b>{r.title}</b> <Sym symbol={r.symbol} />
        </span>
        <small>{[r.detail, accountName(r.account)].filter(Boolean).join(' · ')}</small>
      </span>
      <b className={`rs-lg-amt${r.type === 'flow' && r.amount > 0 ? ' up' : ''}`}>{usd(r.amount, { sign: true, cents: Math.abs(r.amount) < 1000 })}</b>
    </li>
  );
}

export function Ledger({ pack, i }) {
  const rows = ledger(pack);
  const more = Math.max(0, (pack.trade_count || 0) - (pack.trades || []).length);
  return (
    <div className="card c7 rs-ledger" style={{ '--i': i }} data-testid="rs-ledger" data-count={rows.length}>
      <div className="card-head">
        <span className="tag mint">Money in and trades</span>
        <span className="acts">{rows.length ? <span className="chip">{`${(pack.flows || []).length} cash · ${pack.trade_count ?? (pack.trades || []).length} trades`}</span> : null}</span>
      </div>
      {rows.length ? (
        <>
          <ul className="rs-lg">
            {rows.slice(0, SHOW).map((r) => (
              <LedgerRow key={r.key} r={r} />
            ))}
          </ul>
          {rows.length > SHOW ? (
            <details className="job-more">
              <summary>{rows.length - SHOW} more</summary>
              <ul className="rs-lg">
                {rows.slice(SHOW).map((r) => (
                  <LedgerRow key={r.key} r={r} />
                ))}
              </ul>
            </details>
          ) : null}
          {more ? <p className="muted rs-foot">{more} earlier trades are in the Journal.</p> : null}
        </>
      ) : (
        <p className="empty-hint">No deposits, withdrawals or trades in this period.</p>
      )}
    </div>
  );
}

// ---------- risk ----------
export function RiskCard({ pack, i }) {
  const facts = riskFacts(pack);
  const band = bandLine(pack.risk?.band);
  const holds = pack.risk?.convictions || [];
  return (
    <div className="card c5 rs-risk" style={{ '--i': i }} data-testid="rs-risk">
      <div className="card-head">
        <span className="tag lilac">Risk</span>
        <span className="acts">{band ? <span className={`chip ${band.tone}`}>{band.fit || band.chip}</span> : null}</span>
      </div>
      {facts.length ? (
        <div className="mini-kpis rs-risk-kpis">
          {facts.map((f) => (
            <div key={f.id}>
              <small>{f.label}</small>
              <b>{f.value}</b>
              <span className="mix-sub">{f.sub}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-hint">One day is too short for dips and swing. See the week.</p>
      )}
      {band ? (
        <p className="muted rs-foot">
          {band.chip}. {band.text}
        </p>
      ) : null}
      {holds.length ? (
        <ul className="rs-holds">
          {holds.map((c) => {
            const st = statusWord(c);
            return (
              <li key={c.symbol}>
                <Sym symbol={c.symbol} />
                <small>
                  {c.weight_pct != null ? `${c.weight_pct.toFixed(1)}%` : '—'} in a {c.band_min_pct}–{c.band_max_pct}% band
                </small>
                <span className={`chip ${st.tone}`}>{st.t}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

// ---------- decisions ----------
export function DecisionsCard({ pack, i }) {
  const { made, matured } = decisionRows(pack.decisions);
  return (
    <div className="card c6 rs-dec" style={{ '--i': i }} data-testid="rs-decisions" data-made={made.length} data-matured={matured.length}>
      <div className="card-head">
        <span className="tag coral">Decisions</span>
        <span className="acts">
          <Link className="link" to="/decisions/flight">
            Flight record
          </Link>
        </span>
      </div>
      {made.length || matured.length ? (
        <ul className="rs-list">
          {matured.map((m) => (
            <li key={m.key}>
              <span>
                <b>{m.title}</b>
                <small>
                  {m.who} · {scoreLine(m)}
                </small>
              </span>
              <b className={m.tone}>{usd(m.usd, { sign: true })}</b>
            </li>
          ))}
          {made.slice(0, 5).map((d) => (
            <li key={d.key}>
              <span>
                <b>{d.title}</b>
                <small>
                  {d.who} · {dayLabel(d.date)}
                </small>
              </span>
              <span className="chip">{d.status}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-hint">No decisions made and no scores came due.</p>
      )}
      {made.length > 5 ? <p className="muted rs-foot">{made.length - 5} more in the Journal.</p> : null}
    </div>
  );
}

// ---------- paper race ----------
export function PaperCard({ pack, i }) {
  const rows = pack.paper || [];
  return (
    <div className="card c6 rs-paper" style={{ '--i': i }} data-testid="rs-paper" data-count={rows.length}>
      <div className="card-head">
        <span className="tag sky">Paper race</span>
        <span className="acts">
          <Link className="link" to="/strategies">
            Leaderboard
          </Link>
        </span>
      </div>
      {rows.length ? (
        <ul className="rs-list">
          {rows.map((p) => (
            <li key={p.id}>
              <span>
                <b>{p.name}</b>
                <small>{p.value_end != null ? `${usd(p.value_end)} on paper` : 'On paper'}</small>
              </span>
              <b className={p.return_pct > 0 ? 'up' : p.return_pct < 0 ? 'dn' : undefined}>{signedPct(p.return_pct, 2)}</b>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty-hint">No paper strategies ran in this period.</p>
      )}
    </div>
  );
}

// ---------- accounts and events ----------
export function Accounts({ pack, i }) {
  const rows = pack.accounts || [];
  if (rows.length < 2) return null;
  return (
    <div className="card c6 rs-accounts" style={{ '--i': i }} data-testid="rs-accounts">
      <div className="card-head">
        <span className="tag mint">By account</span>
      </div>
      <ul className="rs-list">
        {rows.map((a) => (
          <li key={a.account}>
            <span>
              <b>{accountName(a.account)}</b>
              <small>
                {usd(a.start)} to {usd(a.end)}
                {Math.abs(a.net_flows || 0) >= 0.5 ? ` · ${usd(a.net_flows, { sign: true })} ${a.net_flows > 0 ? 'in' : 'out'}` : ''}
              </small>
            </span>
            <b className={a.change_pct > 0 ? 'up' : a.change_pct < 0 ? 'dn' : undefined}>{signedPct(a.change_pct, 2)}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Events({ pack, i }) {
  const rows = pack.events || [];
  if (!rows.length) return null;
  return (
    <div className="card c6 rs-events" style={{ '--i': i }} data-testid="rs-events" data-count={rows.length}>
      <div className="card-head">
        <span className="tag mustard">On the calendar</span>
      </div>
      <ul className="rs-list">
        {rows.slice(0, 6).map((e) => (
          <li key={`${e.date}-${e.type}-${e.symbol}`}>
            <span>
              <b>
                {eventWord(e)} <Sym symbol={e.symbol} />
              </b>
              <small>{e.detail}</small>
            </span>
            <span className="chip">{dayLabel(e.date)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

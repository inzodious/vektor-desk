import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { useApi } from '../lib/api.js';
import { QUALITY } from '../lib/quality.js';
import { KINDS, RESULT_TABS, changeText, firstRunNote, gainLine, periodPath, stateChip, stepper } from '../lib/results.js';
import { Accounts, Debrief, DecisionsCard, Events, Ledger, Movers, NextSteps, Numbers, PaperCard, RiskCard, Versus } from '../results/cards.jsx';
import { EmptyState, GapNote } from '../start/EmptyState.jsx';

const REVIEW_NOW = { kind: 'job', job: 'engine-review', label: 'Write it now' };

// ---------- stepper ----------
function Stepper({ kind, step }) {
  if (!step.current) return null;
  const latest = step.rows[0];
  return (
    <span className="rs-stepper" data-testid="rs-stepper">
      {step.older ? (
        <Link className="icon-btn rs-step-btn back" to={periodPath(kind, step.older, latest)} aria-label={`Earlier: ${step.older.label}`} title={step.older.label} data-testid="rs-older">
          <Icon name="chev" />
        </Link>
      ) : (
        <span className="icon-btn rs-step-btn back off" aria-hidden="true">
          <Icon name="chev" />
        </span>
      )}
      <b data-testid="rs-label">{step.current.label}</b>
      {step.newer ? (
        <Link className="icon-btn rs-step-btn" to={periodPath(kind, step.newer, latest)} aria-label={`Later: ${step.newer.label}`} title={step.newer.label} data-testid="rs-newer">
          <Icon name="chev" />
        </Link>
      ) : (
        <span className="icon-btn rs-step-btn off" aria-hidden="true">
          <Icon name="chev" />
        </span>
      )}
      {!step.latest ? (
        <Link className="link" to={`/results/${kind}`} data-testid="rs-latest">
          Latest
        </Link>
      ) : null}
    </span>
  );
}

// ---------- page ----------
export default function Results() {
  const { kind } = useParams();
  const [params] = useSearchParams();
  const end = params.get('end');
  const ok = KINDS.includes(kind);
  const index = useApi(ok ? '/api/engine/reviews/index' : null);
  const api = useApi(ok ? `/api/engine/reviews?kind=${kind}${end ? `&end=${encodeURIComponent(end)}` : ''}` : null);
  if (!ok) return <Navigate to="/results/day" replace />;
  const d = api.data && api.data.kind === kind ? api.data : null;
  const pack = d?.pack || null;
  const step = stepper(index.data, kind, end || d?.end);
  const change = changeText(pack?.value);
  const state = stateChip(d && pack ? d : null);
  const tabs = <Subtabs label="Results views" tabs={RESULT_TABS} />;
  const foot = (
    <>
      {tabs}
      <Stepper kind={kind} step={step} />
    </>
  );

  if (!d && api.loading) return <Hero kicker="Results" title="Results" art="bridge" big={<b>Checking…</b>} foot={tabs} />;

  if (!d) {
    const missing = api.error?.status === 404;
    return (
      <>
        <Hero kicker="Results" title="Results" art="bridge" big={<b>{missing ? 'Not yet' : 'No answer'}</b>} foot={tabs} />
        {missing ? (
          <EmptyState k={`results.${kind}`} card icon="telescope" title="No results yet" why="Results reviews switch on with the next desk update." />
        ) : (
          <section className="card" role="alert">
            <div className="card-head">
              <span className="tag coral">The desk API didn&apos;t answer</span>
              <button className="btn sm" type="button" onClick={api.reload}>
                <Icon name="swap" />
                Retry
              </button>
            </div>
            <p className="muted">The review comes back as soon as it does.</p>
          </section>
        )}
      </>
    );
  }

  if (!pack) {
    return (
      <>
        <Hero kicker="Results" title="Results" art="bridge" big={<b>Nothing to show yet</b>} foot={foot} />
        <EmptyState k={`results.${kind}`} card icon="telescope" title="No results yet" why={firstRunNote(index.data, d)} action={REVIEW_NOW} onFilled={api.reload} />
      </>
    );
  }

  return (
    <>
      <Hero
        kicker={`Results · ${pack.label}`}
        title="Results"
        art="bridge"
        big={
          <>
            <b data-testid="rs-change">{change.usd}</b>
            <span className={change.tone} data-testid="rs-pct">
              {change.pct}
            </span>
            <span className="muted">{gainLine(pack.value)}</span>
          </>
        }
        foot={foot}
        chips={
          <>
            {state ? (
              <span className={`chip ${state.tone}`} title={state.title} data-testid="rs-state">
                {state.t}
              </span>
            ) : null}
            {pack.quality && QUALITY[pack.quality] ? <span className="chip lilac">{QUALITY[pack.quality]}</span> : null}
          </>
        }
      />
      {end ? null : <GapNote k={`results.${kind}`} onFilled={api.reload} />}
      {pack.coverage && !pack.coverage.full ? (
        <p className="note rs-cover" role="note" data-testid="rs-cover">
          {pack.coverage.note || 'The desk’s history starts inside this period, so this covers what there is.'}
        </p>
      ) : null}
      <section className="grid" data-testid="results" data-kind={kind} data-end={d.end}>
        <Numbers pack={pack} i={1} />
        <div className="c7 rs-col" style={{ '--i': 2 }}>
          <Debrief review={d} />
          <Movers pack={pack} />
        </div>
        <div className="c5 rs-col" style={{ '--i': 3 }}>
          <NextSteps review={d} />
          <Versus pack={pack} />
        </div>
        <Ledger pack={pack} i={4} />
        <RiskCard pack={pack} i={5} />
        <DecisionsCard pack={pack} i={6} />
        <PaperCard pack={pack} i={7} />
        <Accounts pack={pack} i={8} />
        <Events pack={pack} i={8} />
      </section>
    </>
  );
}

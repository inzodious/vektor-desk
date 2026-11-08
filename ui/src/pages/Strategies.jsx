import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { LabHero } from '../lab/parts.jsx';
import { Leaderboard } from '../lab/Leaderboard.jsx';
import { useApi } from '../lib/api.js';
import { plural } from '../lib/format.js';
import { PAPER_DAYS, dayOf, RULE_WORD, STAGES, paperProgress, paramText, signedPts, splitStrategies, stageCounts, statusOf, verdictOf } from '../lib/strategy.js';

// ---------- stage rail ----------
function StageRail({ counts }) {
  return (
    <section className="card stages" data-testid="stages" aria-label="Strategy stages">
      {STAGES.map((s, k) => (
        <div className={`stage${counts[s.v] ? ' lit' : ''}`} key={s.v} data-stage={s.v} style={{ '--i': k }}>
          <i aria-hidden="true">{k + 1}</i>
          <span>
            <b>{counts[s.v]}</b> {s.t}
            <small>{s.line}</small>
          </span>
        </div>
      ))}
    </section>
  );
}

function StrategyRow({ s }) {
  const st = statusOf(s.status);
  const prog = paperProgress(s.paper);
  return (
    <Link className="row strat-row" to={`/lab/strategies/${encodeURIComponent(s.id)}`} data-strategy={s.id}>
      <span className="l">
        <span className="desk-ico sm">
          <Icon name="flag" />
        </span>
        <span style={{ minWidth: 0 }}>
          <b>{s.title || s.id}</b>
          <small>
            v{s.version} · {plural(s.trials || 0, 'variant')} tried · since {dayOf(s.registered_at)}
          </small>
          {s.hypothesis ? <small className="strat-hyp">{s.hypothesis}</small> : null}
          {prog && s.status === 'paper' ? (
            <span className="strat-prog">
              <span className="meter" role="img" aria-label={`Paper trading day ${prog.days} of ${PAPER_DAYS}`}>
                <i style={{ width: `${prog.share * 100}%` }} />
              </span>
              <small>
                Day {prog.days} of {PAPER_DAYS} · {signedPts(s.paper.excess_pts)} against its benchmark
              </small>
            </span>
          ) : null}
        </span>
      </span>
      <span className={`chip ${st.tone}`}>{st.t}</span>
    </Link>
  );
}

function RuleRow({ r }) {
  const v = verdictOf(r.verdict);
  return (
    <Link className="row strat-row" to={`/lab/strategies/${encodeURIComponent(r.id)}`} data-rule={r.id}>
      <span className="l">
        <span className="desk-ico sm">
          <Icon name="swap" />
        </span>
        <span style={{ minWidth: 0 }}>
          <b>{RULE_WORD[r.rule] || r.rule}</b>
          <small>
            {r.id} · best: {paramText(r.best)}
          </small>
        </span>
      </span>
      <span className={`chip ${v.tone}`}>{v.t}</span>
    </Link>
  );
}

// ---------- page ----------
export default function Strategies() {
  const api = useApi('/api/lab/strategies');
  const d = api.data;
  const list = splitStrategies(d);
  const rules = d?.rules || [];
  const counts = stageCounts(list);

  const big = d ? (
    <>
      <b>{counts.paper + counts.eligible}</b>
      <span className="muted">
        {counts.eligible ? `on paper or eligible · ${plural(list.length, 'strategy', 'strategies')}` : `on paper · ${plural(list.length, 'strategy', 'strategies')}, ${plural(rules.length, 'rule test')}`}
      </span>
    </>
  ) : (
    <b>{api.loading ? 'Checking…' : '—'}</b>
  );

  return (
    <>
      <LabHero kicker="Strategies" title="Strategy lab" big={big} />
      {api.error && !d ? (
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button className="btn sm" type="button" onClick={api.reload}>
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">The lab list comes back as soon as it does.</p>
        </section>
      ) : (
        <>
          <Leaderboard />
          <StageRail counts={counts} />
          <section className="grid">
            <div className="card c8 top" data-testid="strategies">
              <div className="card-head">
                <span className="tag">Strategies</span>
                <span className="chip">{counts.off ? `${counts.off} off the track` : 'Newest first by stage'}</span>
              </div>
              {list.length ? (
                <div className="rows">
                  {list.map((s) => (
                    <StrategyRow s={s} key={`${s.id}-${s.version}`} />
                  ))}
                </div>
              ) : (
                <p className="empty-hint">{api.loading ? 'Opening the ledger…' : 'Nothing in the lab yet. Ask the Strategy desk from the Console to turn a research idea into a spec.'}</p>
              )}
            </div>
            <div className="stack c4">
              <div className="card" data-testid="rules">
                <div className="card-head">
                  <span className="tag mustard">Rule tests</span>
                  <span className="chip">Your habits, replayed</span>
                </div>
                {rules.length ? (
                  <div className="rows">
                    {rules.map((r) => (
                      <RuleRow r={r} key={`${r.id}-${r.version}`} />
                    ))}
                  </div>
                ) : (
                  <p className="empty-hint">{api.loading ? 'Opening the ledger…' : 'No rule tests yet. Rebalance bands, steering deposits, harvesting and margin can each be replayed on your plan mix.'}</p>
                )}
              </div>
              <div className="card">
                <div className="card-head">
                  <span className="tag mint">How the lab stays honest</span>
                </div>
                <div className="rule">
                  <Icon name="book" />
                  <span>
                    <b>The model writes rules, never trades</b>
                    <small>The engine replays each rule day by day on data as it was known then.</small>
                  </span>
                  <span />
                </div>
                <div className="rule">
                  <Icon name="layers" />
                  <span>
                    <b>Every try counts</b>
                    <small>Each variant raises the bar, so tuning harder makes passing harder.</small>
                  </span>
                  <span />
                </div>
                <div className="rule">
                  <Icon name="clock" />
                  <span>
                    <b>Six months of fake money</b>
                    <small>Only trading after the spec was frozen is truly unseen. Real proposals wait for it.</small>
                  </span>
                  <span />
                </div>
              </div>
            </div>
          </section>
        </>
      )}
    </>
  );
}

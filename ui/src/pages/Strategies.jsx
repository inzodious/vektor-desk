import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { LabHero } from '../lab/parts.jsx';
import { Leaderboard } from '../lab/Leaderboard.jsx';
import { Library } from '../lab/Library.jsx';
import { useApi } from '../lib/api.js';
import { plural } from '../lib/format.js';
import { boardHead } from '../lib/leaderboard.js';
import { PAPER_DAYS, dayOf, STAGES, paperProgress, signedPts, splitStrategies, stageCounts, statusOf } from '../lib/strategy.js';
import { GapNote } from '../start/EmptyState.jsx';

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
    <Link className="row strat-row" to={`/strategies/${encodeURIComponent(s.id)}`} data-strategy={s.id}>
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

function StrategyList({ list, off, loading }) {
  return (
    <div className="card c8 top" data-testid="strategies">
      <div className="card-head">
        <span className="tag">Strategies</span>
        <span className="chip">{off ? `${off} off the track` : 'Newest first by stage'}</span>
      </div>
      {list.length ? (
        <div className="rows">
          {list.map((s) => (
            <StrategyRow s={s} key={`${s.id}-${s.version}`} />
          ))}
        </div>
      ) : (
        <p className="empty-hint">{loading ? 'Opening the ledger…' : 'Nothing in the lab yet. Ask the Strategy desk from the Console to turn a research idea into a spec.'}</p>
      )}
    </div>
  );
}

// ---------- page ----------
export default function Strategies() {
  const api = useApi('/api/lab/strategies');
  const lib = useApi('/api/lab/library', { every: 300000 });
  const board = useApi('/api/engine/lab/leaderboard');
  const d = api.data;
  const all = splitStrategies(d);
  const list = all.filter((s) => !(lib.data && s.library));
  const staged = stageCounts(all);
  const head = boardHead(board.data);
  const eligible = Math.max(staged.eligible, head.eligible);
  const paper = Math.max(staged.paper, head.racing - head.eligible);
  const counts = { ...staged, paper, eligible };
  const racing = paper + eligible;
  const shelf = lib.data?.counts?.total ? lib.data.counts : null;
  const onPaper = `${racing} ${eligible ? 'on paper or eligible' : 'racing on paper'}`;
  const bare = Boolean(shelf) && !list.length && !api.loading;

  const big = shelf ? (
    <>
      <b data-testid="strat-count">{shelf.tested || shelf.total}</b>
      <span className="muted">{shelf.tested ? `of ${shelf.total} tested overnight · ${shelf.held_up || 'none'} held up · ${onPaper}` : `on tonight’s list, waiting for their first run · ${onPaper}`}</span>
    </>
  ) : d ? (
    <>
      <b data-testid="strat-count">{racing}</b>
      <span className="muted">
        {eligible ? 'on paper or eligible' : 'on paper'} · {plural(Math.max(all.length, head.racing), 'strategy', 'strategies')}
      </span>
    </>
  ) : (
    <b>{api.loading ? 'Checking…' : '—'}</b>
  );

  return (
    <>
      <LabHero kicker="Race" title="Race" big={big} />
      {api.error && !d ? (
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button className="btn sm" type="button" onClick={api.reload}>
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">The race comes back as soon as it does.</p>
        </section>
      ) : (
        <>
          <GapNote k="strategies.race" />
          <GapNote k="settings.risk_check" />
          <Library api={lib} />
          <Leaderboard api={board} />
          <StageRail counts={counts} />
          <section className="grid">
            {bare ? null : <StrategyList list={list} off={counts.off} loading={api.loading} />}
            <div className={bare ? 'stack c12' : 'stack c4'}>
              <details className={bare ? 'card honest wide fold-card' : 'card honest fold-card'} data-testid="honest">
                <summary>
                  <b>How the lab stays honest</b>
                </summary>
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
              </details>
            </div>
          </section>
        </>
      )}
    </>
  );
}

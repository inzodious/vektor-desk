import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { boardHead, boardRows, boardStatus, edgeText, edgeTone, statLine, trackText } from '../lib/leaderboard.js';
import { plural } from '../lib/format.js';

function Rank({ r }) {
  if (r.rank == null) return <span className="lb-rank out" aria-label="Retired">—</span>;
  return (
    <span className={`lb-rank r${Math.min(r.rank, 4)}`} aria-label={`Rank ${r.rank}`}>
      {r.rank}
    </span>
  );
}

function Track({ r }) {
  const done = r.status === 'eligible';
  return (
    <span className={`lb-track${done ? ' done' : ''}${r.status === 'retired' ? ' out' : ''}`} role="img" aria-label={`${Math.round(r.share * 100)}% of the way to live-eligible`}>
      <i style={{ width: `${r.share * 100}%` }} />
      <b style={{ left: `${r.share * 100}%` }} aria-hidden="true">
        <Icon name={done ? 'flag' : 'send'} />
      </b>
    </span>
  );
}

function Row({ r, bench }) {
  const st = boardStatus(r.status);
  const name = (
    <>
      <b>{r.name || r.id}</b>
      {r.kind === 'lane' ? <span className="chip lilac">Lane</span> : null}
    </>
  );
  return (
    <div className={`lb-row ${r.status}`} data-row={r.id} data-status={r.status}>
      <Rank r={r} />
      <span className="lb-main">
        <span className="lb-name">{r.kind === 'strategy' ? <Link to={`/lab/strategies/${encodeURIComponent(r.id)}`}>{name}</Link> : name}</span>
        <Track r={r} />
        <small>{trackText(r)}</small>
      </span>
      <span className="lb-edge">
        <b className={edgeTone(r.excess_pts)}>{edgeText(r)}</b>
        <small>vs {bench}</small>
        <span className={`chip ${st.tone}`}>{st.t}</span>
      </span>
      <small className="lb-stats">{statLine(r, bench)}</small>
    </div>
  );
}

export function Leaderboard() {
  const api = useApi('/api/engine/lab/leaderboard');
  const d = api.data;
  const rows = boardRows(d);
  const head = boardHead(d);
  const bench = d?.benchmark || 'IWM';
  return (
    <section className="card leaderboard" data-testid="leaderboard">
      <div className="card-head">
        <span className="tag coral">Race to live</span>
        <span className="acts">
          {d?.as_of ? <span className="chip">As of {dayLabel(d.as_of)}</span> : null}
          <span className="chip">
            Live after {d?.gate_days || 182} days ahead of {bench}
          </span>
        </span>
      </div>
      {api.loading && !d ? (
        <p className="empty-hint">Lining up the racers…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">{api.error.status === 404 ? 'The leaderboard switches on with the next engine update.' : 'The board didn’t load. It comes back with the desk API.'}</p>
      ) : rows.length ? (
        <>
          <p className="lb-lede" data-testid="lb-lede">
            {head.leader ? (
              <>
                <b>{head.leader.name || head.leader.id}</b> leads at {edgeText(head.leader)} against {bench}.
              </>
            ) : (
              <>Everyone&apos;s just off the line.</>
            )}{' '}
            <span className="muted">
              {plural(head.racing, 'racer')} on paper{head.eligible ? `, ${head.eligible} ready to go live` : ''}. Paper money only; nothing trades for real.
            </span>
          </p>
          <div className="lb-rows">
            {rows.map((r) => (
              <Row key={`${r.id}-${r.version}`} r={r} bench={bench} />
            ))}
          </div>
        </>
      ) : (
        <p className="empty-hint" data-testid="lb-empty">
          {d?.note || 'No strategies are paper trading yet.'}
        </p>
      )}
    </section>
  );
}

import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { accountText, boardGroups, boardHead, boardStatus, edgeText, edgeTone, gateText, groupText, luckText, rankLabel, rewardLine, statLine, trackText } from '../lib/leaderboard.js';
import { plural } from '../lib/format.js';

function Rank({ r }) {
  if (r.rank == null) {
    return (
      <span className={`lb-rank ${r.status === 'retired' ? 'out' : 'wait'}`} aria-label={rankLabel(r)}>
        {r.status === 'retired' ? '—' : '·'}
      </span>
    );
  }
  return (
    <span className={`lb-rank r${Math.min(r.rank, 4)}`} aria-label={rankLabel(r)}>
      {r.rank}
    </span>
  );
}

function Track({ r }) {
  const done = r.status === 'eligible';
  return (
    <span className={`lb-track${done ? ' done' : ''}${r.status === 'retired' ? ' out' : ''}`} role="img" aria-label={done ? 'Passed its check' : `${Math.round(r.share * 100)}% of the way to its next check`}>
      <i style={{ width: `${r.share * 100}%` }} />
      <b style={{ left: `${r.share * 100}%` }} aria-hidden="true">
        <Icon name={done ? 'flag' : 'send'} />
      </b>
    </span>
  );
}

function Row({ r }) {
  const st = boardStatus(r.status);
  const luck = luckText(r);
  const fresh = r.young && r.status !== 'retired';
  const name = (
    <>
      <b>{r.name || r.id}</b>
      {r.kind === 'lane' ? <span className="chip lilac">Lane</span> : r.kind === 'mix' ? <span className="chip info">Mix</span> : null}
    </>
  );
  return (
    <div className={`lb-row ${r.status}${fresh ? ' young' : ''}`} data-row={r.id} data-status={r.status} data-young={fresh ? 'true' : undefined}>
      <Rank r={r} />
      <span className="lb-main">
        <span className="lb-name">{r.kind === 'strategy' ? <Link to={`/strategies/${encodeURIComponent(r.id)}`}>{name}</Link> : r.kind === 'mix' ? <Link to="/strategies/mixes">{name}</Link> : name}</span>
        <Track r={r} />
        <small>{trackText(r)}</small>
      </span>
      <span className="lb-edge">
        <b className={edgeTone(r.excess_pts)}>{edgeText(r)}</b>
        <small>vs {r.benchmark}</small>
        {luck ? (
          <small className="lb-luck" data-testid="lb-luck">
            {luck}
          </small>
        ) : null}
        <span className={`chip ${st.tone}`}>{fresh ? 'Too new to rank' : st.t}</span>
      </span>
      <small className="lb-stats">
        {statLine(r)}
        {rewardLine(r) ? (
          <span className="lb-acct" data-testid="lb-reward">
            {rewardLine(r)}
          </span>
        ) : null}
        {accountText(r) ? (
          <span className="lb-acct" data-testid="lb-account">
            {accountText(r)}
          </span>
        ) : null}
      </small>
    </div>
  );
}

export function Leaderboard() {
  const api = useApi('/api/engine/lab/leaderboard');
  const d = api.data;
  const groups = boardGroups(d);
  const head = boardHead(d);
  return (
    <section className="card leaderboard" data-testid="leaderboard">
      <div className="card-head">
        <span className="tag coral">Race to live</span>
        <span className="acts">
          {d?.as_of ? <span className="chip">As of {dayLabel(d.as_of)}</span> : null}
          <span className="chip">{gateText(d)}</span>
        </span>
      </div>
      {api.loading && !d ? (
        <p className="empty-hint">Lining up the racers…</p>
      ) : api.error && !d ? (
        <p className="empty-hint">{api.error.status === 404 ? 'The leaderboard switches on with the next engine update.' : 'The board didn’t load. It comes back with the desk API.'}</p>
      ) : groups.length ? (
        <>
          <p className="lb-lede" data-testid="lb-lede">
            {head.leader ? (
              <>
                <b>{head.leader.name || head.leader.id}</b> has the firmest lead: {edgeText(head.leader)} against {head.leader.benchmark}, {luckText(head.leader).toLowerCase()}.
              </>
            ) : (
              <>Everyone&apos;s just off the line.</>
            )}{' '}
            <span className="muted">
              {plural(head.racing, 'racer')} on paper{head.eligible ? `, ${head.eligible} ready to go live` : ''}. Ranked within each benchmark by lead against noise, after {d?.young_days || 60} days. Paper money only; nothing trades for real.
            </span>
          </p>
          {groups.map((g) => (
            <div className="lb-group" key={g.benchmark} data-group={g.benchmark}>
              <p className="kicker lb-bench">
                Against {g.benchmark} <small>{groupText(g)}</small>
              </p>
              <div className="lb-rows">
                {g.rows.map((r) => (
                  <Row key={`${r.id}-${r.version}`} r={r} />
                ))}
              </div>
            </div>
          ))}
        </>
      ) : (
        <p className="empty-hint" data-testid="lb-empty">
          {d?.note || 'No strategies are paper trading yet.'}
        </p>
      )}
    </section>
  );
}

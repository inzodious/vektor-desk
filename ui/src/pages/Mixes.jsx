import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { RangeBars } from '../components/RangeBars.jsx';
import { LabHero } from '../lab/parts.jsx';
import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { assumptions, backtestLine, bandAt, chanceText, fitBadge, mixLine, mixesHead, money, rankDots, rewardText } from '../lib/mixes.js';
import { signedPct } from '../lib/strategy.js';
import { trackText } from '../lib/leaderboard.js';

function Rank({ rank }) {
  return (
    <span className="mix-rank" role="img" aria-label={rank ? `Risk ${rank} of 5` : 'Risk not rated yet'}>
      {rankDots(rank).map((d) => (
        <i key={d.n} className={d.on ? `on r${rank}` : ''} />
      ))}
      <small>{rank ? `Risk ${rank} of 5` : 'Not rated'}</small>
    </span>
  );
}

function MixCard({ r, i, fi, profile, race }) {
  const fit = fitBadge(r.fit);
  const ten = bandAt(r, 10);
  const reward = rewardText(r);
  const chance = chanceText(r.chance_fi);
  if (r.status !== 'ok') {
    return (
      <div className="card c6 mix not-ready" style={{ '--i': i + 2 }} data-mix={r.id} data-status={r.status}>
        <div className="card-head">
          <span className="mix-name">
            <b>{r.name}</b>
          </span>
          <span className="chip">Not ready</span>
        </div>
        <p className="muted mix-line">{mixLine(r)}</p>
        <p className="empty-hint">{r.note || 'Needs more price history before the bands can be drawn.'}</p>
      </div>
    );
  }
  return (
    <div className="card c6 mix" style={{ '--i': i + 2 }} data-mix={r.id} data-fit={r.fit || 'none'} data-rank={r.risk_rank}>
      <div className="card-head">
        <span className="mix-name">
          <b>{r.name}</b>
          <Rank rank={r.risk_rank} />
        </span>
        <span className="acts">
          {fit ? (
            <span className={`chip ${fit.tone}`} data-testid="mix-fit">
              {fit.t}
            </span>
          ) : (
            <Link className="chip info" to="/settings/risk" data-testid="mix-fit">
              Take the risk check
            </Link>
          )}
        </span>
      </div>
      <p className="muted mix-line">{mixLine(r)}</p>
      <RangeBars bands={r.bands} fi={fi} label={`${r.name}: in 10 years the middle path is ${money(ten?.p50)}, with 1 in 10 below ${money(ten?.p10)} and 1 in 10 above ${money(ten?.p90)}`} />
      <div className="mini-kpis mix-kpis">
        <div>
          <small>In 10 years</small>
          <b>{money(ten?.p50)}</b>
          <span className="mix-sub">
            {money(ten?.p10)} to {money(ten?.p90)}
          </span>
        </div>
        <div>
          <small>Bad year, 1 in 10</small>
          <b className={r.worst_year_p10_pct < 0 ? 'dn' : 'up'}>{signedPct(r.worst_year_p10_pct)}</b>
          <span className="mix-sub">{profile ? `your band takes −${profile.worst_year_loss_pct}%` : 'vs your band'}</span>
        </div>
        <div>
          <small>Reward to risk</small>
          <b>{reward ? reward.v : '—'}</b>
          <span className="mix-sub">{reward ? `Sharpe, ${reward.word}` : 'Sharpe'}</span>
        </div>
        <div>
          <small>Chance of FI</small>
          <b data-testid="mix-chance">{chance || '—'}</b>
          <span className="mix-sub">{chance ? 'by your target date' : 'set an FI goal'}</span>
        </div>
      </div>
      <p className="muted mix-foot">
        {backtestLine(r.backtest)}
        {r.proxy_note ? ` · ${r.proxy_note}` : ''}
      </p>
      {race ? (
        <Link className="mix-race" to="/lab/strategies" data-testid="mix-race">
          <Icon name="flag" />
          On paper: {trackText(race)}
        </Link>
      ) : null}
    </div>
  );
}

export default function Mixes() {
  const api = useApi('/api/engine/bands');
  const board = useApi('/api/engine/lab/leaderboard');
  const d = api.data;
  const rows = d?.rows || [];
  const head = mixesHead(d);
  const races = Object.fromEntries((board.data?.rows || []).filter((r) => r.kind === 'mix').map((r) => [r.id, r]));
  const big = d?.status === 'ok' ? (
    <>
      <b>{head.ready === 1 ? '1 mix' : `${head.ready} mixes`}</b>
      <span className="muted">{d.profile ? `${head.fitting} fit band ${d.profile.band}, ${d.profile.label}` : 'safe to risky, no single target'}</span>
    </>
  ) : (
    <b>{api.loading && !d ? 'Checking…' : 'Warming up'}</b>
  );
  return (
    <>
      <LabHero kicker="Mixes" title="Mixes" big={big} />
      {api.loading && !d ? (
        <section className="card">
          <p className="empty-hint">Running the mixes through market history…</p>
        </section>
      ) : api.error && !d ? (
        <section className="card">
          <p className="empty-hint">{api.error.status === 404 ? 'Mixes switch on with the next engine update.' : 'The bands didn’t load. They come back with the desk API.'}</p>
        </section>
      ) : d?.status !== 'ok' || !rows.length ? (
        <section className="card" data-testid="mixes-empty">
          <p className="empty-hint">{d?.note || 'The bands are built with the daily numbers. They show here after the next run.'}</p>
        </section>
      ) : (
        <section className="grid" data-testid="mixes">
          <div className="card c12 mix-head" style={{ '--i': 1 }}>
            <div className="card-head">
              <span className="tag coral">Safe to risky</span>
              <span className="acts">
                {d.as_of ? <span className="chip">As of {dayLabel(d.as_of)}</span> : null}
                {!d.profile ? (
                  <Link className="chip info" to="/settings/risk">
                    Take the risk check for fit badges
                  </Link>
                ) : null}
              </span>
            </div>
            <p className="mix-assume" data-testid="mix-assume">
              {assumptions(d).join(' · ')}.
            </p>
            {head.best ? (
              <p className="muted mix-best">
                Best odds of FI: <b>{head.best.name}</b> at {chanceText(head.best.chance_fi)}.
              </p>
            ) : null}
          </div>
          {rows.map((r, i) => (
            <MixCard key={r.id} r={r} i={i} fi={d.fi_number} profile={d.profile} race={races[r.id]} />
          ))}
          <details className="card c12 mix-method" style={{ '--i': rows.length + 2 }}>
            <summary>How these are drawn</summary>
            <p className="muted">{d.method}.</p>
            <ul>
              {(d.caveats || []).map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </>
  );
}

import { Link, useSearchParams } from 'react-router-dom';
import { FiLadder } from '../components/FiLadder.jsx';
import { Icon } from '../components/Icon.jsx';
import { RangeBars } from '../components/RangeBars.jsx';
import { LabHero } from '../lab/parts.jsx';
import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { assumptions, backtestLine, bandAt, caseOf, chanceText, feeText, fiHeadline, fitBadge, mixLine, mixesHead, money, movesText, rankDots, rewardText, yearsText } from '../lib/mixes.js';
import { signedPct } from '../lib/strategy.js';
import { trackText } from '../lib/leaderboard.js';
import { EmptyState, GapNote } from '../start/EmptyState.jsx';

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

function FiHead({ d, lower, onLower }) {
  const head = fiHeadline(d, lower);
  const cut = d.premium_cut_pts;
  const year = d.target_date ? String(d.target_date).slice(0, 4) : null;
  const targetYears = d.target_date && d.as_of ? (new Date(d.target_date) - new Date(d.as_of)) / (365.25 * 864e5) : null;
  return (
    <div className="card c12 mix-head" style={{ '--i': 1 }} data-testid="fi-time" data-case={lower ? 'lower' : 'base'}>
      <div className="card-head">
        <span className="tag coral">Time to FI</span>
        <span className="acts">
          {cut != null ? (
            <label className="fi-switch">
              <button type="button" className="switch" role="switch" aria-checked={lower} aria-label={`Lower returns: stocks earn ${cut} points less a year`} onClick={() => onLower(!lower)} data-testid="lower-switch" />
              <span>
                Lower returns
                <small>stocks earn {cut} points less</small>
              </span>
            </label>
          ) : null}
          {d.as_of ? <span className="chip">As of {dayLabel(d.as_of)}</span> : null}
          {!d.profile ? (
            <Link className="chip info" to="/settings/risk">
              Take the risk check for fit badges
            </Link>
          ) : null}
        </span>
      </div>
      {head ? (
        <div className="fi-split">
          <div className="fi-say">
            <p className="fi-big" data-testid="fi-big">
              <b>{head.you.p50 == null ? `Over ${head.max} years` : `About ${yearsText(head.you.p50, head.max)}`}</b>
              <span>
                to {money(d.fi_number)} at {money(head.you.deposit)} a month{head.year ? `, around ${head.year}` : ''}
              </span>
            </p>
            <div className="mini-kpis two fi-moves">
              {head.deposit ? (
                <div data-testid="fi-deposit">
                  <small>The deposit moves it</small>
                  <b>{movesText(head.deposit.moves)}</b>
                  <span>
                    {money(head.deposit.low.deposit)} a month takes {yearsText(head.deposit.low.p50, head.max).replace(/ years?/, '')}, {money(head.deposit.high.deposit)} takes {yearsText(head.deposit.high.p50, head.max).replace(/ years?/, '')}
                  </span>
                </div>
              ) : null}
              {head.mix ? (
                <div data-testid="fi-mix">
                  <small>The mix moves it</small>
                  <b>{movesText(head.mix.moves)}</b>
                  <span>{head.mix.moves ? `${head.mix.fastest.name} first, ${head.mix.slowest.name} last` : `none gets there inside ${head.max} years`}</span>
                </div>
              ) : null}
              {head.other ? (
                <div data-testid="fi-other">
                  <small>{lower ? 'At normal returns' : 'At lower returns'}</small>
                  <b>{yearsText(head.other.years, head.max)}</b>
                  <span>{lower ? 'the long-run stock premium' : `if stocks earn ${cut} points less a year`}</span>
                </div>
              ) : null}
              {year ? (
                <div data-testid="fi-chance">
                  <small>By {year}</small>
                  <b>{chanceText(head.you.chance) || '—'}</b>
                  <span>of paths, {head.ladder.ref.name.toLowerCase()}</span>
                </div>
              ) : null}
            </div>
          </div>
          <FiLadder
            ladder={head.ladder}
            targetYears={targetYears}
            targetLabel={year}
            label={`Years to FI by monthly deposit: ${head.ladder.levels.map((l) => `${money(l.deposit)} a month, ${yearsText(l.p50, head.max)}`).join('; ')}`}
          />
        </div>
      ) : (
        <p className="empty-hint" data-testid="fi-none">
          Set an FI goal in Escape Vektor to see how long each monthly deposit takes to reach it.
        </p>
      )}
      <p className="mix-assume" data-testid="mix-assume">
        {assumptions(d).join(' · ')}.
      </p>
    </div>
  );
}

function Variant({ v, profile }) {
  const ten = bandAt(v, 10);
  return (
    <div className="mix-variant" data-testid="mix-variant" data-rank={v.risk_rank}>
      <small>{v.name}</small>
      <span>
        In 10 years <b>{money(ten?.p50)}</b>, {money(ten?.p10)} to {money(ten?.p90)} · bad year <b className={v.worst_year_p10_pct < 0 ? 'dn' : 'up'}>{signedPct(v.worst_year_p10_pct)}</b>
        {profile && -v.worst_year_p10_pct > profile.worst_year_loss_pct ? ', past your band' : ''} · risk {v.risk_rank} of 5
      </span>
    </div>
  );
}

function MixCard({ r, i, fi, profile, race, lower, max, year }) {
  const fit = fitBadge(r.fit);
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
  const c = caseOf(r, lower);
  const ten = bandAt(c, 10);
  const reward = rewardText(r);
  const chance = chanceText(c.chance_fi);
  const fee = feeText(r.fee_pct);
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
      <p className="muted mix-line">
        {mixLine(r)}
        {r.policy === 'hold' ? ` · left to drift, new money to ${r.new_money === 'safe-mix' ? 'the safe mix' : r.new_money === 'rest' ? 'your funds' : 'the US market'}` : ''}
      </p>
      <RangeBars bands={c.bands} fi={fi} label={`${r.name}: in 10 years the middle path is ${money(ten?.p50)}, with 1 in 10 below ${money(ten?.p10)} and 1 in 10 above ${money(ten?.p90)}`} />
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
          <b className={c.worst_year_p10_pct < 0 ? 'dn' : 'up'}>{signedPct(c.worst_year_p10_pct)}</b>
          <span className="mix-sub">{profile ? `your band takes −${profile.worst_year_loss_pct}%` : 'vs your band'}</span>
        </div>
        <div>
          <small>Reward to risk</small>
          <b>{reward ? reward.v : '—'}</b>
          <span className="mix-sub">{reward ? `Sharpe, ${reward.word}` : 'Sharpe'}</span>
        </div>
        <div>
          <small>FI in</small>
          <b data-testid="mix-fi">{c.fi_years ? yearsText(c.fi_years.p50, max) : '—'}</b>
          <span className="mix-sub" data-testid="mix-chance">
            {c.fi_years ? `${chance || '—'} by ${year || 'your date'}` : 'set an FI goal'}
          </span>
        </div>
      </div>
      {(r.variants || []).map((v) => (
        <Variant key={v.id} v={v} profile={profile} />
      ))}
      <p className="muted mix-foot">
        {[backtestLine(r.backtest), fee, r.proxy_note].filter(Boolean).join(' · ')}
      </p>
      {race ? (
        <Link className="mix-race" to="/strategies" data-testid="mix-race">
          <Icon name="flag" />
          On paper: {trackText(race)}
        </Link>
      ) : null}
    </div>
  );
}

function Policy({ p, symbol, fi, profile, scale }) {
  const ten = bandAt(p, 10);
  const share = ten?.weight_pct;
  return (
    <div className="policy" data-policy={p.id}>
      <div className="policy-head">
        <b>{p.name}</b>
        <Rank rank={p.risk_rank} />
      </div>
      <p className="muted policy-rule">{p.rule}</p>
      <RangeBars bands={p.bands} fi={fi} scale={scale} label={`${symbol}, ${p.name}: in 10 years the middle path is ${money(ten?.p50)}, with 1 in 10 below ${money(ten?.p10)} and 1 in 10 above ${money(ten?.p90)}`} />
      <div className="mini-kpis two policy-kpis">
        <div>
          <small>In 10 years</small>
          <b>{money(ten?.p50)}</b>
          <span className="mix-sub">
            {money(ten?.p10)} to {money(ten?.p90)}
          </span>
        </div>
        <div>
          <small>{symbol} share then</small>
          <b data-testid="policy-share">{share ? `${Math.round(share.p50)}%` : '—'}</b>
          <span className="mix-sub">{share ? (share.p10 === share.p90 ? 'held there' : `${Math.round(share.p10)}% to ${Math.round(share.p90)}%`) : ''}</span>
        </div>
        <div>
          <small>Bad year, 1 in 10</small>
          <b className={p.worst_year_p10_pct < 0 ? 'dn' : 'up'}>{signedPct(p.worst_year_p10_pct)}</b>
          <span className="mix-sub">{profile ? `your band takes −${profile.worst_year_loss_pct}%` : 'vs your band'}</span>
        </div>
        <div>
          <small>Worst dip, 10 years</small>
          <b className={p.max_drawdown_pct < 0 ? 'dn' : 'up'}>{signedPct(p.max_drawdown_pct)}</b>
          <span className="mix-sub">typical path</span>
        </div>
      </div>
    </div>
  );
}

function Conviction({ c, i, fi, profile }) {
  return (
    <div className="card c12 conviction" style={{ '--i': i }} data-conviction={c.symbol} data-status={c.status} data-testid="hold-or-trim">
      <div className="card-head">
        <span className="tag lilac">{c.symbol}: hold, rebalance or trim</span>
        <span className="acts">
          {c.weight_pct != null ? <span className="chip">{Number(c.weight_pct.toFixed(1))}% of the book</span> : null}
          <Link className="chip info" to="/settings/risk">
            Band {c.band_min_pct}–{c.band_max_pct}%
          </Link>
        </span>
      </div>
      {c.status === 'ok' ? (
        <>
          <p className="muted policy-lede">Same market paths and deposits in all three. Only the rule for {c.symbol} changes.</p>
          <div className="policies">
            {c.policies.map((p) => (
              <Policy key={p.id} p={p} symbol={c.symbol} fi={fi} profile={profile} scale={c.policies.flatMap((x) => x.bands)} />
            ))}
          </div>
        </>
      ) : (
        <p className="empty-hint">{c.note || 'Needs more price history before the three rules can be compared.'}</p>
      )}
    </div>
  );
}

export default function Mixes() {
  const api = useApi('/api/engine/bands');
  const board = useApi('/api/engine/lab/leaderboard');
  const [params, setParams] = useSearchParams();
  const d = api.data;
  const rows = d?.rows || [];
  const head = mixesHead(d);
  const lower = params.get('case') === 'lower' && d?.premium_cut_pts != null;
  const setLower = (on) => {
    const next = new URLSearchParams(params);
    if (on) next.set('case', 'lower');
    else next.delete('case');
    setParams(next, { replace: true });
  };
  const year = d?.target_date ? String(d.target_date).slice(0, 4) : null;
  const held = d?.convictions || [];
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
      {d?.status === 'ok' && rows.length ? <GapNote k="strategies.mixes" /> : null}
      {api.loading && !d ? (
        <section className="card">
          <p className="empty-hint">Running the mixes through market history…</p>
        </section>
      ) : api.error && !d ? (
        <section className="card">
          <p className="empty-hint">{api.error.status === 404 ? 'Mixes switch on with the next engine update.' : 'The bands didn’t load. They come back with the desk API.'}</p>
        </section>
      ) : d?.status !== 'ok' || !rows.length ? (
        <section className="card es-card" data-testid="mixes-empty">
          <EmptyState k="strategies.mixes" icon="layers" title="No mixes to compare yet" why={d?.note || 'The bands are built with the daily numbers. They show here after the next run.'} onFilled={api.reload} />
        </section>
      ) : (
        <section className="grid" data-testid="mixes">
          <FiHead d={d} lower={lower} onLower={setLower} />
          {rows.map((r, i) => (
            <MixCard key={r.id} r={r} i={i} fi={d.fi_number} profile={d.profile} race={races[r.id]} lower={lower} max={d.fi_years_max || 40} year={year} />
          ))}
          {held.map((c, i) => (
            <Conviction key={c.symbol} c={c} i={rows.length + 2 + i} fi={d.fi_number} profile={d.profile} />
          ))}
          <details className="card c12 mix-method" style={{ '--i': rows.length + held.length + 2 }}>
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

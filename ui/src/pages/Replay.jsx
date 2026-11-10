import { useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Combo } from '../components/Combo.jsx';
import { HBars } from '../components/HBars.jsx';
import { Icon } from '../components/Icon.jsx';
import { LineChart } from '../components/LineChart.jsx';
import { LabHero } from '../lab/parts.jsx';
import { useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { usd } from '../lib/format.js';
import { money } from '../lib/mixes.js';
import { QUALITY } from '../lib/quality.js';
import { actionLine, chartSeries, eventRows, familyOptions, firstOf, groups, headline, helpRead, levelOptions, pickRule, shortLabel, signed, sizingTiles, spanLabel, split, splitRead, symbolBars, taxRead, yearTicks } from '../lib/replay.js';

const tone = (v) => (v == null || v === 0 ? '' : v > 0 ? 'up' : 'dn');

// ---------- parts ----------
function Versus({ view, rule, onPick }) {
  const s = split(view, rule);
  const tax = taxRead(view, rule);
  const levels = levelOptions(view, rule.family);
  const house = rule.family === 'house';
  const read = splitRead(s);
  return (
    <section className="card replay-versus" data-testid="versus" data-rule={rule.id}>
      <div className="card-head">
        <span className="tag coral">{house ? 'You versus the capped you' : 'You versus the rule'}</span>
        <span className="acts">
          {view.quality && view.quality !== 'ok' ? <span className="chip watch">{QUALITY[view.quality] || view.quality}</span> : null}
          <span className="chip">{spanLabel(view)}</span>
        </span>
      </div>
      <div className="replay-pick">
        <Combo label="Rule" options={familyOptions(view)} value={rule.family} onChange={(f) => onPick(firstOf(view, f)?.id)} />
        {levels.length ? <Combo label="Level" options={levels} value={rule.id} onChange={onPick} /> : null}
        <span className="muted replay-rule" data-testid="rule-label">
          {rule.label}
        </span>
      </div>
      <div className="mini-kpis four replay-kpis">
        <div>
          <small>You</small>
          <b>{usd(view.you.end_value)}</b>
          <span className="tile-line">what you did</span>
        </div>
        <div data-testid="rule-end">
          <small>{house ? 'The capped you' : 'With the rule'}</small>
          <b>{usd(rule.end_value)}</b>
          <span className={`tile-line ${tone(rule.change_usd)}`}>{signed(rule.change_usd)} against you</span>
        </div>
        <div>
          <small>S&amp;P 500</small>
          <b>{usd(view.index_only.end_value)}</b>
          <span className="tile-line">same dollars, same dates</span>
        </div>
        {s ? (
          <div data-testid="rule-picks">
            <small>Your picks</small>
            <b className={tone(s.picks)}>{signed(s.picks)}</b>
            <span className="tile-line">against the S&amp;P at this size</span>
          </div>
        ) : tax ? (
          <div data-testid="rule-tax">
            <small>Tax</small>
            <b className={tax.tone}>{tax.value}</b>
            <span className="tile-line">{tax.line}</span>
          </div>
        ) : (
          <div data-testid="rule-acts">
            <small>Stepped in</small>
            <b>{rule.actions}</b>
            <span className="tile-line">{rule.actions ? `${usd(rule.moved_usd)} moved` : 'never needed'}</span>
          </div>
        )}
      </div>
      <LineChart
        series={chartSeries(view, rule)}
        x={view.dates}
        height={280}
        fmtY={money}
        fmtTip={(v) => usd(v)}
        endLabels
        ticksX={yearTicks}
        label={`Account value over time: you, ${shortLabel(rule).toLowerCase()} and the S&P 500 on the same dollars`}
      />
      {read ? (
        <p className="note" role="note" data-testid="split-read">
          <Icon name="info" />
          <span>{read}</span>
        </p>
      ) : tax ? (
        <p className="note" role="note" data-testid="tax-read">
          <Icon name="info" />
          <span>
            Before tax the rule changes the end value by {signed(rule.change_usd)}. Tax is estimated at {tax.rates}, on the stock sales only.
          </span>
        </p>
      ) : null}
    </section>
  );
}

function Effects({ rule }) {
  const rows = eventRows(rule);
  return (
    <section className="grid">
      <div className="card c7" data-testid="effects">
        <div className="card-head">
          <span className="tag mint">Where it helped and hurt</span>
          <span className="chip">End value against you, by name</span>
        </div>
        <HBars items={symbolBars(rule)} fmt={signed} name="Change in end value" labelW={120} empty="The rule changed nothing, so there is nothing to split." />
        <p className="empty-hint" style={{ marginTop: 6 }}>
          {helpRead(rule)}
        </p>
      </div>
      <div className="card c5" data-testid="events">
        <div className="card-head">
          <span className="tag mustard">What the rule did</span>
          <span className="chip">{actionLine(rule)}</span>
        </div>
        {rows.length ? (
          <div className="tscroll">
            <table className="t">
              <thead>
                <tr>
                  <th scope="col">Day</th>
                  <th scope="col">Name</th>
                  <th scope="col">What</th>
                  <th scope="col" className="r">
                    Dollars
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.key} className="still">
                    <td>{e.date}</td>
                    <td>
                      <b>{e.symbol}</b>
                    </td>
                    <td>{e.what}</td>
                    <td className="r num">
                      {e.usd}
                      <small className="muted cell-sub">{e.to}</small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-hint">Nothing you did broke this rule, so it never stepped in.</p>
        )}
        {rule.actions > rows.length ? <p className="empty-hint" style={{ marginTop: 6 }}>The {rows.length} largest of {rule.actions}.</p> : null}
      </div>
    </section>
  );
}

function Rules({ view, rule, onPick }) {
  const list = groups(view);
  return (
    <section className="card" data-testid="rules">
      <div className="card-head">
        <span className="tag sky">Every rule, side by side</span>
        <span className="chip">End value against you · tap a bar to replay it</span>
      </div>
      <div className="grid replay-groups">
        {list.map((g) => (
          <div className="c4 keep" key={g.key} data-group={g.key}>
            <span className="kicker">{g.title}</span>
            <p className="replay-ask">{g.ask}</p>
            <HBars items={g.items} fmt={signed} name="Against you" labelW={132} table={false} picked={shortLabel(rule)} onPick={(d) => onPick(d.id)} />
            {g.read ? <p className="empty-hint">{g.read}</p> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function Sizing({ view }) {
  const tiles = sizingTiles(view);
  if (!tiles.length) return null;
  return (
    <section className="card" data-testid="sizing">
      <div className="card-head">
        <span className="tag lilac">How you sized it</span>
        <span className="chip">Single names, against the whole account on the day</span>
      </div>
      <div className="mini-kpis six">
        {tiles.map((t) => (
          <div key={t.k}>
            <small>{t.k}</small>
            <b className={t.tone}>{t.v}</b>
            <span className="tile-line">{t.line}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------- page ----------
export default function Replay() {
  const api = useApi('/api/engine/replay');
  const [params, setParams] = useSearchParams();
  const top = useRef(null);
  const d = api.data;
  const ready = d && d.status !== 'not_ready' && d.variants?.length;
  const rule = ready ? pickRule(d, params.get('rule')) : null;
  const head = ready ? headline(d) : null;

  const pick = (id) => {
    if (!id) return;
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        n.set('rule', id);
        return n;
      },
      { replace: true },
    );
    const box = top.current?.getBoundingClientRect();
    if (box && (box.top < 0 || box.top > window.innerHeight * 0.6)) top.current.scrollIntoView({ block: 'start', behavior: 'smooth' });
  };

  const big = head ? (
    <>
      <b className={head.tone}>{head.value}</b>
      <span className="muted">{head.line}</span>
    </>
  ) : (
    <b>{api.loading && !d ? 'Replaying…' : 'Warming up'}</b>
  );

  return (
    <>
      <LabHero kicker="Patterns · Replay" title="Replay" big={big} board={ready ? 'Replay' : undefined} />
      {api.error && !d ? (
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button className="btn sm" type="button" onClick={api.reload}>
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">The replay comes back as soon as it does.</p>
        </section>
      ) : api.loading && !d ? (
        <section className="card">
          <p className="empty-hint">Replaying your trades under each rule…</p>
        </section>
      ) : !ready ? (
        <section className="card" data-testid="replay-empty">
          <div className="card-head">
            <span className="tag coral">You versus the capped you</span>
            <span className="chip">Not ready yet</span>
          </div>
          <p className="muted">{d?.reason || 'The replay runs with the nightly engine once your Fidelity history is in.'}</p>
          <p style={{ marginTop: 10 }}>
            <Link className="btn sm" to="/settings#inbox">
              <Icon name="pin" />
              Upload the history
            </Link>
          </p>
        </section>
      ) : (
        <>
          <div ref={top} className="replay-top" />
          <Versus view={d} rule={rule} onPick={pick} />
          <Effects rule={rule} />
          <Rules view={d} rule={rule} onPick={pick} />
          <Sizing view={d} />
          <p className="note" role="note" data-testid="replay-note">
            <Icon name="info" />
            <span>
              {d.note} {(d.notes || []).join(' ')} As of {dayLabel(d.as_of, true)}.
            </span>
          </p>
          <p className="replay-back">
            <Link className="link" to="/lab/patterns">
              Back to Patterns
            </Link>
          </p>
        </>
      )}
    </>
  );
}

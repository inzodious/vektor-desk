import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Gauge } from '../components/Gauge.jsx';
import { Panel } from '../components/Panel.jsx';
import { postJson, useApi } from '../lib/api.js';
import { dayLabel } from '../lib/charts.js';
import { usd } from '../lib/format.js';
import { ZONES, answeredCount, bandFacts, bandRows, byPart, limitText, riskRefusal, sameValue, savedText, startAnswers, worstDollars } from '../lib/risk.js';

const day = (iso) => (iso ? dayLabel(iso.slice(0, 10), true) : '—');

// ---------- result ----------
function Result({ c, inputs, msg, onRetake, onBands }) {
  const worst = worstDollars(c, inputs?.portfolio_value);
  return (
    <div className="card c12 risk-result" style={{ '--i': 1 }} data-testid="risk-result" data-band={c.band} data-limited={c.limited_by}>
      <div className="card-head">
        <span className="tag mint">Your band</span>
        <span className="acts">
          <span className="chip">
            Taken {day(c.answered_at || c.taken_at)} · version {c.version}
          </span>
        </span>
      </div>
      <div className="risk-body">
        <div className="gauges risk-gauge">
          <Gauge label={c.label} unit="BAND" value={c.band} min={0.5} max={5.5} zones={ZONES} reading={`Band ${c.band}`} note="Tap for all five" onOpen={onBands} />
        </div>
        <div className="risk-side">
          <p className="risk-lede" data-testid="risk-limit">
            {limitText(c)}
          </p>
          <div className="mini-kpis risk-facts">
            {bandFacts(c).map((f) => (
              <div key={f.k}>
                <small>{f.k}</small>
                <b>{f.v}</b>
              </div>
            ))}
          </div>
          <p className="muted risk-note">
            {worst ? `A worst year at today’s size is about −${usd(worst)}. ` : ''}Every strategy and brief is measured against this band.
          </p>
          {msg ? (
            <p className={`risk-msg ${msg.phase}`} role="status" data-testid="risk-msg">
              {msg.text}
            </p>
          ) : null}
          <div className="sheet-acts">
            <button className="btn sm" type="button" onClick={onRetake} data-testid="risk-retake">
              <Icon name="swap" />
              Retake the check
            </button>
            <button className="btn sm ghost" type="button" onClick={onBands}>
              <Icon name="layers" />
              See all five bands
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- quiz ----------
function Question({ q, value, onPick }) {
  return (
    <fieldset className="rq" data-q={q.id} data-answered={value != null ? 'true' : 'false'}>
      <legend>{q.prompt}</legend>
      <div className="rq-opts">
        {q.options.map((o) => {
          const on = value != null && sameValue(value, o.value);
          return (
            <label key={String(o.value)} className={`rq-opt${on ? ' on' : ''}`}>
              <input type="radio" name={q.id} value={String(o.value)} checked={on} onChange={() => onPick(q.id, o.value)} />
              <span className="rq-dot" aria-hidden="true" />
              <span>{o.label}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function Quiz({ questions, inputs, answers, setAnswers, busy, msg, onSave, onCancel }) {
  const total = questions.length;
  const done = answeredCount(questions, answers);
  const pick = (id, v) => setAnswers((a) => ({ ...a, [id]: v }));
  return (
    <form
      className="card c12 risk-quiz"
      style={{ '--i': 2 }}
      data-testid="risk-quiz"
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <div className="card-head">
        <span className="tag coral">{total === 8 ? 'Eight questions' : `${total} questions`}</span>
        <span className="acts">
          <span className={`chip ${done === total ? 'ok' : ''}`} data-testid="risk-count">
            {done} of {total} answered
          </span>
        </span>
      </div>
      <span className="lb-track fr-track" role="img" aria-label={`${done} of ${total} answered`}>
        <i style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
        <b style={{ left: `${total ? (done / total) * 100 : 0}%` }} aria-hidden="true">
          <Icon name={done === total ? 'flag' : 'send'} />
        </b>
      </span>
      {byPart(questions).map((p) => (
        <section key={p.id} className="rq-part" data-part={p.id}>
          <div className="rq-head">
            <span className="kicker">{p.title}</span>
            <small className="muted">{p.blurb}</small>
          </div>
          <div className="rq-grid">
            {p.questions.map((q) => (
              <Question key={q.id} q={q} value={answers[q.id]} onPick={pick} />
            ))}
          </div>
        </section>
      ))}
      {inputs?.savings_rate_pct != null || inputs?.fi_horizon_years != null ? (
        <p className="muted risk-note">
          {inputs.savings_rate_pct != null ? `Your savings rate (${Math.round(inputs.savings_rate_pct)}%) counts toward capacity too; the desk reads it from your activity. ` : ''}
          {inputs.fi_horizon_years != null ? `Your FI date, about ${Math.round(inputs.fi_horizon_years)} years out, sets the timeline.` : ''}
        </p>
      ) : null}
      {msg ? (
        <p className={`risk-msg ${msg.phase}`} role="status" data-testid="risk-msg">
          {msg.text}
        </p>
      ) : null}
      <div className="sheet-acts">
        <button className="btn" type="submit" disabled={busy || done < total} data-testid="risk-save">
          <Icon name="check" />
          {busy ? 'Saving…' : 'See my band'}
        </button>
        {onCancel ? (
          <button className="btn ghost" type="button" onClick={onCancel}>
            Keep my band
          </button>
        ) : null}
      </div>
    </form>
  );
}

// ---------- history and bands ----------
function History({ versions }) {
  if (!versions.length) return null;
  return (
    <div className="card c12" style={{ '--i': 3 }} data-testid="risk-history">
      <div className="card-head">
        <span className="tag sky">Past checks</span>
      </div>
      <div className="tscroll">
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">Taken</th>
              <th scope="col">Band</th>
              <th scope="col">Held by</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.version} className="still">
                <td>{v.version}</td>
                <td>{day(v.created_at)}</td>
                <td>
                  {v.band} · {v.label}
                </td>
                <td>{v.limited_by === 'capacity' ? 'Timeline and cushion' : v.limited_by === 'tolerance' ? 'Comfort' : 'Both agree'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Bands({ bands, current, open, onClose }) {
  return (
    <Panel open={open} onClose={onClose} title="The five bands" sub="What each band allows. Strategies and briefs get a fit badge against yours." crumbs={[{ label: 'Settings', go: onClose }, { label: 'Risk check', go: onClose }]}>
      <div className="tscroll" data-testid="risk-bands">
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Band</th>
              <th scope="col" className="r">
                Stocks
              </th>
              <th scope="col" className="r">
                Speculative
              </th>
              <th scope="col" className="r">
                One stock
              </th>
              <th scope="col" className="r">
                Worst year
              </th>
            </tr>
          </thead>
          <tbody>
            {bandRows(bands).map((b) => (
              <tr key={b.n} className={`still${current?.band === b.n ? ' on' : ''}`} data-band={b.n}>
                <td>
                  <b>{b.n}</b> {b.label}
                  {current?.band === b.n ? <span className="chip ok risk-you">You</span> : null}
                </td>
                <td className="r">
                  {b.equity_min_pct}–{b.equity_max_pct}%
                </td>
                <td className="r">{b.speculative_max_pct ? `${b.speculative_max_pct}%` : '—'}</td>
                <td className="r">{b.single_stock_max_pct}%</td>
                <td className="r">−{b.worst_year_loss_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

// ---------- page ----------
export default function RiskCheck() {
  const api = useApi('/api/decisions/risk');
  const hist = useApi('/api/decisions/risk/versions');
  const [answers, setAnswers] = useState(null);
  const [retake, setRetake] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [bandsOpen, setBandsOpen] = useState(false);
  const d = api.data;
  const c = d?.current || null;
  const questions = d?.questions || [];
  const versions = hist.data?.versions || [];
  const shown = answers ?? startAnswers(questions, versions);
  const quiz = d && (!c || retake);

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await postJson('/api/decisions/risk', { answers: shown }, { method: 'PUT' });
      setMsg({ phase: 'done', text: savedText(r) });
      setRetake(false);
      setAnswers(null);
      api.reload();
      hist.reload();
    } catch (e) {
      setMsg({ phase: 'refused', text: riskRefusal(e) });
    }
    setBusy(false);
  };

  return (
    <>
      <Hero
        kicker="Settings · Risk check"
        title="Risk check"
        art="settings"
        big={
          c ? (
            <>
              <b>Band {c.band}</b>
              <span className="muted">{c.label}</span>
            </>
          ) : (
            <>
              <b>{d ? 'Not taken' : api.loading ? 'Checking…' : 'No answer'}</b>
              <span className="muted">Eight questions, about two minutes</span>
            </>
          )
        }
        foot={
          <>
            {c ? <span className="chip ok">Stocks {c.equity_min_pct}–{c.equity_max_pct}%</span> : <span className="chip watch">Strategies wait for your band</span>}
            <Link className="chip info" to="/settings/first-run">
              First-run checklist
            </Link>
          </>
        }
      />
      <section className="grid">
        {api.loading && !d ? (
          <div className="card c12">
            <p className="empty-hint">Pulling up the questions…</p>
          </div>
        ) : api.error && !d ? (
          <div className="card c12">
            <p className="empty-hint">{riskRefusal(api.error)}</p>
          </div>
        ) : null}
        {c && !retake ? (
          <Result
            c={c}
            inputs={d.inputs}
            msg={msg}
            onRetake={() => {
              setMsg(null);
              setRetake(true);
            }}
            onBands={() => setBandsOpen(true)}
          />
        ) : null}
        {quiz ? (
          <Quiz
            questions={questions}
            inputs={d.inputs}
            answers={shown}
            setAnswers={(f) => setAnswers((a) => f(a ?? shown))}
            busy={busy}
            msg={msg}
            onSave={save}
            onCancel={c ? () => setRetake(false) : null}
          />
        ) : null}
        <History versions={versions} />
      </section>
      {d ? <Bands bands={d.bands} current={c} open={bandsOpen} onClose={() => setBandsOpen(false)} /> : null}
    </>
  );
}

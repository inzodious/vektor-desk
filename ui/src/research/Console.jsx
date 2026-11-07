import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Panel } from '../components/Panel.jsx';
import { Icon, Robot } from '../components/Icon.jsx';
import { Combo } from '../components/Combo.jsx';
import { ConsoleContext } from './consoleContext.js';
import { postJson, useApi } from '../lib/api.js';
import { ASK_DESKS, ASK_STATUS, SUGGESTED, cleanSymbol, deskTitle, overnightStart } from '../lib/research.js';
import { whenLabel } from '../lib/agents.js';

const SHOW = 6;

function stepLine(r, tonight) {
  const desk = deskTitle(r.desk);
  if (r.status === 'queued') return r.run_now ? `Queued for the ${desk} · runs at the next free slot` : `Queued for the ${desk} · tonight ${tonight}`;
  if (r.status === 'running') return `${desk} is working on it`;
  if (r.status === 'failed') return `${desk} didn't finish${r.note ? `: ${r.note}` : ''}`;
  return `Answered by the ${desk}${r.finished_at ? ` · ${whenLabel(r.finished_at)}` : ''}`;
}

// ---------- terminal ----------
function Term({ rows, tonight, loading, error }) {
  const end = useRef(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'nearest' });
  }, [rows.length]);
  return (
    <div className="term" data-testid="console-term" aria-live="polite">
      {rows.length ? (
        rows.map((r) => {
          const st = ASK_STATUS[r.status] || ASK_STATUS.queued;
          return (
            <div className="t-item" key={r.id} data-status={r.status}>
              <p className="t-hi">
                &gt; {r.question}
                {r.symbol ? <span className="t-sym"> · {r.symbol}</span> : null}
              </p>
              <p className="t-step">
                <Icon name={st.icon} />
                {stepLine(r, tonight)}
              </p>
              {r.answer ? <p className="t-ans">{r.answer}</p> : null}
            </div>
          );
        })
      ) : (
        <p className="t-step">
          <Icon name="info" />
          {error ? "The Console didn't answer. The desks may not be set up on this NAS yet." : loading ? 'Reading the Console…' : 'No questions yet. Ask one below.'}
        </p>
      )}
      <span ref={end} />
    </div>
  );
}

// ---------- body ----------
function ConsoleBody({ prefill }) {
  const list = useApi('/api/agents/console?limit=20', { every: (d) => (Array.isArray(d) && d.some((r) => r.status === 'queued' || r.status === 'running') ? 15000 : 0) });
  const profile = useApi('/api/decisions/profile');
  const tonight = overnightStart(profile.data);
  const [desk, setDesk] = useState(prefill?.desk || 'plan_keeper');
  const [symbol, setSymbol] = useState(prefill?.symbol || '');
  const [question, setQuestion] = useState(prefill?.question || '');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [note, setNote] = useState(null);
  const input = useRef(null);
  const preferNow = !!prefill?.now;
  const rows = useMemo(() => (Array.isArray(list.data) ? list.data.slice(0, SHOW).reverse() : []), [list.data]);

  const send = async (runNow) => {
    const q = question.trim();
    if (!q) {
      setErr('Type a question first.');
      input.current?.focus();
      return;
    }
    const sym = symbol.trim() ? cleanSymbol(symbol) : null;
    if (symbol.trim() && !sym) {
      setErr('That symbol looks off. Use letters, like FTEC.');
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const out = await postJson('/api/agents/console', { desk, question: q, symbol: sym, run_now: runNow });
      setQuestion('');
      setNote(runNow ? `Sent to the ${deskTitle(out?.desk || desk)} to run now.` : `Queued for the ${deskTitle(out?.desk || desk)} tonight at ${tonight}.`);
      list.reload();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="console-body">
      <Term rows={rows} tonight={tonight} loading={list.loading} error={list.error && !list.data} />
      <div className="console-chips" aria-label="Suggested questions">
        {SUGGESTED.map((s) => (
          <button
            key={s.q}
            type="button"
            className="chip ask-chip"
            onClick={() => {
              setDesk(s.desk);
              setQuestion(s.q);
              setSymbol('');
              input.current?.focus();
            }}
          >
            <Icon name="star" />
            {s.q}
          </button>
        ))}
      </div>
      <form
        className="console-form"
        onSubmit={(e) => {
          e.preventDefault();
          send(preferNow);
        }}
      >
        <div className="console-row">
          <Combo label="Desk" options={ASK_DESKS} value={desk} onChange={setDesk} />
          <div className="field console-sym">
            <input aria-label="Symbol, optional" placeholder="Symbol" value={symbol} maxLength={10} onChange={(e) => setSymbol(e.target.value.toUpperCase())} />
          </div>
        </div>
        <div className="console-row">
          <div className="field" style={{ flex: 1, minWidth: 0 }}>
            <input ref={input} data-autofocus aria-label="Ask a desk" placeholder="Ask a desk or request research" value={question} maxLength={2000} onChange={(e) => setQuestion(e.target.value)} />
          </div>
          <button className={preferNow ? 'btn ghost' : 'btn'} type={preferNow ? 'button' : 'submit'} disabled={busy} onClick={preferNow ? () => send(false) : undefined}>
            <Icon name="clock" />
            Tonight
          </button>
          <button className={preferNow ? 'btn' : 'btn ghost'} type={preferNow ? 'submit' : 'button'} disabled={busy} onClick={preferNow ? undefined : () => send(true)}>
            <Icon name="play" />
            Run now
          </button>
        </div>
      </form>
      {note && !err ? (
        <p className="act-note" role="status">
          <Icon name="check" />
          {note}
        </p>
      ) : null}
      {err ? (
        <p className="act-err" role="alert">
          {err}
        </p>
      ) : null}
      <p className="muted console-foot">Answers are advice from the desks. Numbers come from the engine, and nothing here can place a trade.</p>
    </div>
  );
}

// ---------- provider ----------
function wantsConsole() {
  try {
    return new URLSearchParams(window.location.search).get('open') === 'console';
  } catch {
    return false;
  }
}

export function ConsoleProvider({ children }) {
  const [state, setState] = useState(() => (wantsConsole() ? { open: true, prefill: null, n: 0 } : { open: false, prefill: null, n: 0 }));
  const openConsole = useCallback((prefill = null) => setState((s) => ({ open: true, prefill, n: s.n + 1 })), []);
  const close = useCallback(() => setState((s) => ({ ...s, open: false })), []);
  const value = useMemo(() => ({ openConsole }), [openConsole]);
  return (
    <ConsoleContext.Provider value={value}>
      {children}
      <Panel open={state.open} onClose={close} kind="console" title="Console" label="Console" head={<span className="console-bot"><Robot size={40} /></span>} sub="Ask a desk. Questions run tonight unless you press Run now.">
        <ConsoleBody key={state.n} prefill={state.prefill} />
      </Panel>
    </ConsoleContext.Provider>
  );
}

export function ConsoleButton() {
  return (
    <ConsoleContext.Consumer>
      {({ openConsole }) => (
        <button className="icon-btn robot-btn" type="button" aria-label="Open the Console" title="Console" data-testid="console-open" onClick={() => openConsole()}>
          <Robot size={24} />
        </button>
      )}
    </ConsoleContext.Consumer>
  );
}

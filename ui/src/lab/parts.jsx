import { useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Icon } from '../components/Icon.jsx';
import { Subtabs } from '../components/Subtabs.jsx';
import { useLive } from '../live/context.js';
import { useDismiss } from '../lib/useDismiss.js';
import { LAB_TABS, MAX_SLOTS, SLOT_COLORS, SPECIAL, addBoard, idLabel, isSymbol } from '../lib/lab.js';
import { cleanSymbol } from '../lib/research.js';

// ---------- save as a board ----------
export function SaveBoard({ name }) {
  const loc = useLocation();
  const [state, setState] = useState(null);
  const save = () => {
    const out = addBoard({ name, path: `${loc.pathname}${loc.search}` });
    setState(out ? 'saved' : 'failed');
  };
  return (
    <>
      <button className="btn sm ghost" type="button" onClick={save} data-testid="save-board">
        <Icon name={state === 'saved' ? 'check' : 'pin'} />
        {state === 'saved' ? 'Saved to boards' : 'Save as a board'}
      </button>
      {state === 'failed' ? (
        <span className="act-err" role="alert">
          This browser won&apos;t keep boards.
        </span>
      ) : null}
    </>
  );
}

export function LabHero({ kicker, title, big, board }) {
  return (
    <Hero
      kicker={`Lab · ${kicker}`}
      title={title}
      art="lab"
      big={big}
      foot={
        <>
          <Subtabs label="Lab views" tabs={LAB_TABS} />
          {board ? <SaveBoard name={board} /> : null}
        </>
      }
    />
  );
}

// ---------- slots ----------
function AddSlot({ ids, onAdd }) {
  const [open, setOpen] = useState(false);
  const [v, setV] = useState('');
  const [err, setErr] = useState(null);
  const root = useRef(null);
  const refs = useMemo(() => [root], []);
  const { symbols } = useLive();
  useDismiss(open, () => setOpen(false), refs);
  const quick = [...SPECIAL.map((s) => s.v), ...symbols.map((s) => s.symbol)].filter((id) => !ids.includes(id)).slice(0, 8);
  const add = (id) => {
    onAdd(id);
    setOpen(false);
    setV('');
    setErr(null);
  };
  const submit = (e) => {
    e.preventDefault();
    const s = cleanSymbol(v);
    if (!s) {
      setErr('Use a ticker, like FSKAX.');
      return;
    }
    add(s);
  };
  if (ids.length >= MAX_SLOTS) return <span className="chip">Five is the most at once</span>;
  return (
    <span className="slot-add" ref={root}>
      <button className="slot add" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name="plus" />
        Add an item
      </button>
      {open ? (
        <div className="slot-pop" role="dialog" aria-label="Add an item">
          <form className="override-row" onSubmit={submit}>
            <div className="field" style={{ flex: 1, minWidth: 0 }}>
              <input aria-label="Ticker to add" placeholder="Any ticker" value={v} maxLength={10} autoFocus onChange={(e) => setV(e.target.value.toUpperCase())} />
            </div>
            <button className="btn sm" type="submit">
              Add
            </button>
          </form>
          {err ? (
            <p className="act-err" role="alert">
              {err}
            </p>
          ) : null}
          <div className="slot-quick">
            {quick.map((id) => (
              <button key={id} type="button" className="chip ask-chip" onClick={() => add(id)}>
                {idLabel(id)}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </span>
  );
}

export function Slots({ ids, onRemove, onAdd }) {
  return (
    <div className="slots" data-testid="slots">
      {ids.map((id, k) => (
        <span className="slot" key={id} data-slot={id}>
          <i style={{ '--c': SLOT_COLORS[k] }} />
          {isSymbol(id) ? (
            <button type="button" className="sym-btn slot-name" data-sym={id}>
              {idLabel(id)}
            </button>
          ) : (
            <span className="slot-name">{idLabel(id)}</span>
          )}
          <button type="button" className="slot-x" aria-label={`Remove ${idLabel(id)}`} onClick={() => onRemove(id)}>
            <Icon name="x" />
          </button>
        </span>
      ))}
      <AddSlot ids={ids} onAdd={onAdd} />
    </div>
  );
}

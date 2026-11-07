import { useCallback, useId, useMemo, useRef, useState } from 'react';
import { Icon } from './Icon.jsx';
import { useDismiss } from '../lib/useDismiss.js';

function norm(o) {
  return typeof o === 'object' ? o : { v: o, t: String(o) };
}

export function Combo({ label, options, value, onChange }) {
  const opts = useMemo(() => options.map(norm), [options]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [place, setPlace] = useState('');
  const root = useRef(null);
  const button = useRef(null);
  const listId = useId();
  const refs = useMemo(() => [root], []);
  const current = opts.find((o) => o.v === value) || opts[0];

  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, refs);

  const show = () => {
    const r = root.current?.getBoundingClientRect();
    if (r) {
      const dock = window.matchMedia?.('(max-width: 860px)').matches ? 96 : 16;
      const need = opts.length * 36 + 24;
      const up = window.innerHeight - r.bottom - dock < need && r.top > need + 72;
      const end = r.left + 200 > window.innerWidth - 12;
      setPlace(`${up ? ' up' : ''}${end ? ' end' : ''}`);
    }
    setActive(Math.max(0, opts.findIndex((o) => o.v === current.v)));
    setOpen(true);
  };

  const pick = (o) => {
    if (o.off) return;
    setOpen(false);
    button.current?.focus();
    if (o.v !== value) onChange?.(o.v);
  };

  const move = (step) => {
    let i = active;
    for (let n = 0; n < opts.length; n += 1) {
      i = (i + step + opts.length) % opts.length;
      if (!opts[i].off) break;
    }
    setActive(i);
  };

  const onKey = (e) => {
    if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      show();
      return;
    }
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      move(1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      move(-1);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      pick(opts[active]);
    } else if (e.key === 'Tab') {
      setOpen(false);
    }
  };

  return (
    <div className={`combo${open ? ` open${place}` : ''}`} ref={root}>
      <button
        ref={button}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={onKey}
      >
        <small>{label}</small> {current.t}
        <Icon name="chev" />
      </button>
      <div role="listbox" id={listId} aria-label={label}>
        {opts.map((o, i) => (
          <div
            key={String(o.v)}
            id={`${listId}-${i}`}
            role="option"
            aria-selected={o.v === current.v}
            aria-disabled={o.off || undefined}
            className={i === active && open ? 'active' : undefined}
            style={o.off ? { opacity: 0.5 } : undefined}
            onClick={() => pick(o)}
            onPointerEnter={() => !o.off && setActive(i)}
          >
            {o.t}
            {o.note ? <small className="muted">{o.note}</small> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

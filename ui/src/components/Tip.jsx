import { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

export function Tip({ at, head, rows = [], hint }) {
  const ref = useRef(null);
  const [pos, setPos] = useState(null);
  useLayoutEffect(() => {
    if (!at || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    let left = at.x + 14;
    let top = at.y + 14;
    if (left + r.width > window.innerWidth - 8) left = at.x - r.width - 14;
    if (top + r.height > window.innerHeight - 8) top = at.y - r.height - 14;
    setPos({ left: Math.max(8, left), top: Math.max(8, top) });
  }, [at, head]);
  if (!at) return null;
  return createPortal(
    <div ref={ref} className={`tip${pos ? ' on' : ''}`} style={pos || { left: -999, top: -999 }} role="status">
      {head ? <b>{head}</b> : null}
      {rows.map((r) => (
        <div className="r" key={r.label}>
          <span>
            {r.color ? <i style={{ '--c': r.color }} /> : null}
            {r.label}
          </span>
          <em>{r.value}</em>
        </div>
      ))}
      {hint ? <div className="hint">{hint}</div> : null}
    </div>,
    document.body,
  );
}

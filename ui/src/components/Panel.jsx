import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './Icon.jsx';
import { useDismiss } from '../lib/useDismiss.js';

export function Panel(props) {
  if (!props.open) return null;
  return <PanelBody {...props} />;
}

function PanelBody({ open, onClose, kind = 'drawer', title, sub, crumbs, head, children, label }) {
  const box = useRef(null);
  const back = useRef(null);
  const [on, setOn] = useState(false);
  useDismiss(open, onClose);

  useEffect(() => {
    back.current = document.activeElement;
    const id = requestAnimationFrame(() => {
      setOn(true);
      box.current?.querySelector('[data-close]')?.focus({ preventScroll: true });
    });
    return () => {
      cancelAnimationFrame(id);
      if (back.current && document.contains(back.current)) back.current.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Tab' || !box.current) return;
      const items = box.current.querySelectorAll('button, a[href], input, textarea, select, [tabindex="0"]');
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const cls = kind === 'drawer' ? 'drawer' : `drawer ${kind}`;
  return createPortal(
    <>
      <div className={`scrim${on ? ' on' : ''}`} style={{ pointerEvents: 'auto' }} data-testid="scrim" onClick={onClose} />
      <div ref={box} className={`${cls}${on ? ' on' : ''}`} role="dialog" aria-modal="true" aria-label={label || (typeof title === 'string' ? title : undefined)}>
        <header>
          {head}
          <div className="t">
            {crumbs && crumbs.length ? (
              <div className="crumbs">
                {crumbs.map((c, i) => (
                  <span key={c.label} style={{ display: 'contents' }}>
                    {c.go ? (
                      <button type="button" onClick={c.go}>
                        {c.label}
                      </button>
                    ) : (
                      <span>{c.label}</span>
                    )}
                    {typeof title === 'string' || i < crumbs.length - 1 ? <span className="sep">›</span> : null}
                  </span>
                ))}
                {typeof title === 'string' ? <span>{title}</span> : null}
              </div>
            ) : null}
            <h3>{title}</h3>
            {sub ? <p className="muted" style={{ fontSize: 12.5 }}>{sub}</p> : null}
          </div>
          <button className="icon-btn" type="button" data-close aria-label="Close" onClick={onClose}>
            <Icon name="x" />
          </button>
        </header>
        <div className="body">{children}</div>
      </div>
    </>,
    document.body,
  );
}

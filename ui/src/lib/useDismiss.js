import { useEffect, useRef } from 'react';

const stack = [];

export function useDismiss(open, onClose, refs) {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    if (!open) return undefined;
    const token = {};
    stack.push(token);
    const onKey = (e) => {
      if (e.key !== 'Escape' || stack[stack.length - 1] !== token) return;
      e.preventDefault();
      close.current();
    };
    const onDown = (e) => {
      if (!refs || !refs.length) return;
      if (refs.some((r) => r.current && r.current.contains(e.target))) return;
      close.current();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown);
    return () => {
      const i = stack.indexOf(token);
      if (i >= 0) stack.splice(i, 1);
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDown);
    };
  }, [open, refs]);
}

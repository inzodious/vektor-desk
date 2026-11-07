import { useCallback, useEffect, useMemo, useState } from 'react';
import { SymbolContext } from './context.js';
import { SymbolSheet } from './SymbolSheet.jsx';

export function SymbolProvider({ children }) {
  const [sym, setSym] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get('sym')?.toUpperCase() || null;
    } catch {
      return null;
    }
  });
  const openSymbol = useCallback((s) => setSym(s ? String(s).toUpperCase() : null), []);
  const close = useCallback(() => setSym(null), []);

  useEffect(() => {
    const onClick = (e) => {
      const chip = e.target.closest?.('[data-sym]');
      if (!chip || chip.closest('.drawer')) return;
      e.preventDefault();
      openSymbol(chip.dataset.sym);
    };
    const onKey = (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const chip = e.target.closest?.('[data-sym]');
      if (!chip || chip.tagName === 'BUTTON' || chip.tagName === 'A' || chip.closest('.drawer')) return;
      e.preventDefault();
      openSymbol(chip.dataset.sym);
    };
    document.addEventListener('click', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [openSymbol]);

  const value = useMemo(() => ({ openSymbol, symbol: sym }), [openSymbol, sym]);
  return (
    <SymbolContext.Provider value={value}>
      {children}
      <SymbolSheet symbol={sym} onClose={close} />
    </SymbolContext.Provider>
  );
}

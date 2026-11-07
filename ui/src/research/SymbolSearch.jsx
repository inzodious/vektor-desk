import { useEffect, useMemo, useRef, useState } from 'react';
import { Panel } from '../components/Panel.jsx';
import { Icon } from '../components/Icon.jsx';
import { useLive, useSymbol } from '../live/context.js';
import { useApi } from '../lib/api.js';
import { cleanSymbol } from '../lib/research.js';

const MAX = 8;

function SearchBody({ onPick }) {
  const { symbols, names } = useLive();
  const dossiers = useApi('/api/agents/dossiers');
  const watch = useApi('/api/engine/watchlist');
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const input = useRef(null);

  const all = useMemo(() => {
    const map = new Map();
    const add = (symbol, name, tag) => {
      if (!symbol) return;
      const cur = map.get(symbol) || { symbol, name: null, tags: [] };
      cur.name = cur.name || name || null;
      if (!cur.tags.includes(tag)) cur.tags.push(tag);
      map.set(symbol, cur);
    };
    symbols.forEach((s) => add(s.symbol, names?.[s.symbol], 'Held'));
    (Array.isArray(watch.data?.symbols) ? watch.data.symbols : []).forEach((w) => add(w.symbol, w.name, 'Watching'));
    (Array.isArray(dossiers.data) ? dossiers.data : []).forEach((d) => add(d.symbol, null, 'Dossier'));
    return [...map.values()];
  }, [symbols, names, watch.data, dossiers.data]);

  const term = q.trim().toUpperCase();
  const hits = useMemo(() => {
    if (!term) return all.slice(0, MAX);
    return all
      .filter((s) => s.symbol.includes(term) || (s.name || '').toUpperCase().includes(term))
      .sort((a, b) => Number(!a.symbol.startsWith(term)) - Number(!b.symbol.startsWith(term)) || a.symbol.localeCompare(b.symbol))
      .slice(0, MAX);
  }, [all, term]);
  const typed = cleanSymbol(term);
  const extra = typed && !hits.some((h) => h.symbol === typed) ? { symbol: typed, name: null, tags: ['Look up'] } : null;
  const list = extra ? [...hits, extra] : hits;
  const cur = Math.min(active, Math.max(0, list.length - 1));

  const onKey = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(list.length - 1, a + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === 'Enter' && list[cur]) {
      e.preventDefault();
      onPick(list[cur].symbol);
    }
  };

  return (
    <div className="search-body">
      <div className="field">
        <input
          ref={input}
          data-autofocus
          role="combobox"
          aria-expanded="true"
          aria-controls="sym-results"
          aria-activedescendant={list[cur] ? `sym-opt-${list[cur].symbol}` : undefined}
          aria-label="Symbol or name"
          placeholder="Symbol or name, like FTEC"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKey}
        />
      </div>
      <ul className="search-list" id="sym-results" role="listbox" aria-label="Matches">
        {list.map((s, i) => (
          <li key={s.symbol} id={`sym-opt-${s.symbol}`} role="option" aria-selected={i === cur} className={i === cur ? 'on' : ''} onPointerEnter={() => setActive(i)} onClick={() => onPick(s.symbol)}>
            <span className="sym">
              <i style={{ '--c': s.tags.includes('Held') ? 'var(--s1)' : 'var(--s3)' }} />
              {s.symbol}
            </span>
            <small className="muted">{s.name || (s.tags.includes('Look up') ? 'Open the symbol sheet' : '')}</small>
            <span className="search-tags">
              {s.tags.map((t) => (
                <span className="chip" key={t}>
                  {t}
                </span>
              ))}
            </span>
          </li>
        ))}
        {!list.length ? <li className="empty-hint">No match. Type a ticker to look it up.</li> : null}
      </ul>
      <p className="muted console-foot">
        Press <kbd>/</kbd> anywhere to search. Arrows move, Enter opens.
      </p>
    </div>
  );
}

function typing(el) {
  return el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
}

export function SymbolSearch() {
  const [open, setOpen] = useState(false);
  const { openSymbol } = useSymbol();

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || typing(document.activeElement)) return;
      if (document.querySelector('[role="dialog"]')) return;
      e.preventDefault();
      setOpen(true);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  return (
    <>
      <button className="icon-btn" type="button" aria-label="Search symbols" aria-keyshortcuts="/" title="Search symbols ( / )" data-testid="search-open" onClick={() => setOpen(true)}>
        <Icon name="search" />
      </button>
      <Panel open={open} onClose={() => setOpen(false)} kind="sheet find" title="Find a symbol" label="Find a symbol">
        <SearchBody
          onPick={(s) => {
            setOpen(false);
            openSymbol(s);
          }}
        />
      </Panel>
    </>
  );
}

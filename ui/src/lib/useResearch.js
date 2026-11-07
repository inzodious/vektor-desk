import { useEffect, useState } from 'react';
import { getJson, useApi } from './api.js';

export function useResearchData() {
  const dossiers = useApi('/api/agents/dossiers');
  const watch = useApi('/api/engine/watchlist');
  const asks = useApi('/api/agents/console?limit=50');
  const list = Array.isArray(dossiers.data) ? [...dossiers.data].sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '')) : [];
  const watchRows = Array.isArray(watch.data?.symbols) ? watch.data.symbols : [];
  const queued = (Array.isArray(asks.data) ? asks.data : []).filter((r) => r.desk === 'research' && (r.status === 'queued' || r.status === 'running'));
  return { dossiers, list, watch, watchRows, watchServed: !!watch.data || (watch.error && watch.error.status !== 404), asks, queued };
}

export function useResearchMany(symbols) {
  const key = [...new Set(symbols)].sort().join(',');
  const [state, setState] = useState({ key: null, data: {} });
  useEffect(() => {
    if (!key) return undefined;
    const ctl = new AbortController();
    Promise.all(
      key.split(',').map((s) =>
        getJson(`/api/engine/research?symbol=${encodeURIComponent(s)}`, { signal: ctl.signal })
          .then((d) => [s, d])
          .catch(() => [s, null]),
      ),
    ).then((pairs) => {
      if (!ctl.signal.aborted) setState({ key, data: Object.fromEntries(pairs) });
    });
    return () => ctl.abort();
  }, [key]);
  return { data: state.key === key ? state.data : {}, loading: !!key && state.key !== key };
}

export function useJsonMany(paths) {
  const key = [...new Set(paths.filter(Boolean))].join('\n');
  const [state, setState] = useState({ key: null, data: {} });
  useEffect(() => {
    if (!key) return undefined;
    const ctl = new AbortController();
    Promise.all(
      key.split('\n').map((p) =>
        getJson(p, { signal: ctl.signal })
          .then((d) => [p, d])
          .catch((e) => [p, { error: e.message, status: e.status }]),
      ),
    ).then((pairs) => {
      if (!ctl.signal.aborted) setState({ key, data: Object.fromEntries(pairs) });
    });
    return () => ctl.abort();
  }, [key]);
  return { data: state.key === key ? state.data : {}, loading: !!key && state.key !== key };
}

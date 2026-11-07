import { useMemo } from 'react';
import { useApi } from './api.js';

export function indexMetrics(rows = []) {
  const map = new Map();
  rows.forEach((m) => map.set(`${m.metric_id}|${m.scope}|${m.scope_id}|${m.window}`, m));
  const get = (id, { scope = 'portfolio', scopeId = 'all', window = 'now' } = {}) => map.get(`${id}|${scope}|${scopeId}|${window}`) || null;
  const all = (id, scope) => rows.filter((m) => m.metric_id === id && (!scope || m.scope === scope));
  return { get, all, rows };
}

export function useMetrics(ids, params = '') {
  const api = useApi(`/api/engine/metrics?ids=${encodeURIComponent(ids)}${params ? `&${params}` : ''}`);
  const idx = useMemo(() => indexMetrics(api.data?.metrics || []), [api.data]);
  return { ...idx, asOf: api.data?.as_of || null, loading: api.loading && !api.data, error: api.error, reload: api.reload };
}

export function val(m) {
  return m && m.value != null && m.quality !== 'insufficient_history' ? m.value : null;
}

export function fundsFromMetrics(rows) {
  const byFund = new Map();
  rows.forEach((m) => {
    if (m.scope !== 'holding') return;
    const f = byFund.get(m.scope_id) || { symbol: m.scope_id };
    if (m.metric_id === 'plan.weight') f.weight = m.value;
    if (m.metric_id === 'plan.target') f.target = m.value;
    if (m.metric_id === 'plan.drift') f.drift = m.value;
    if (m.metric_id === 'plan.next_deposit') f.next = m.value;
    if (m.metric_id === 'plan.single_stock') f.single = m.value;
    if (m.quality && m.quality !== 'ok') f.quality = m.quality;
    byFund.set(m.scope_id, f);
  });
  return [...byFund.values()].sort((a, b) => (b.target ?? -1) - (a.target ?? -1) || (b.weight ?? 0) - (a.weight ?? 0));
}

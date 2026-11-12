import { useMemo } from 'react';
import { useApi } from '../lib/api.js';
import { AsOfContext, asOfFromMetrics, asOfView } from '../lib/asof.js';
import { useNow } from '../lib/useNow.js';

export function AsOfProvider({ children }) {
  const api = useApi('/api/asof', { every: 60000 });
  const missing = !api.data && Boolean(api.error);
  const metrics = useApi(missing ? '/api/engine/metrics?ids=value.market' : null);
  const now = useNow(300000);
  const fallbackDay = metrics.data?.as_of || null;
  const view = useMemo(() => (api.data ? asOfView(api.data, now) : missing ? asOfFromMetrics(fallbackDay) : null), [api.data, missing, fallbackDay, now]);
  return <AsOfContext.Provider value={view}>{children}</AsOfContext.Provider>;
}

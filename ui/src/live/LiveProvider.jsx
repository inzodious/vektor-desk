import { useEffect, useMemo, useState } from 'react';
import { LIVE_STATES, LiveContext, groupLive } from './context.js';
import { getJson, useApi } from '../lib/api.js';

export function LiveProvider({ children }) {
  const live = useApi('/api/live', { every: (d) => (LIVE_STATES.includes(d?.state) ? 15000 : 300000) });
  const positions = useApi('/api/positions');
  const [intraday, setIntraday] = useState({});
  const state = live.data?.state;
  const asOf = live.data?.as_of;
  const day = live.data?.day;

  useEffect(() => {
    if (!state || !LIVE_STATES.includes(state)) return undefined;
    const ctl = new AbortController();
    getJson('/api/live/intraday', { signal: ctl.signal })
      .then((d) => setIntraday(d && d.symbols && (!d.day || d.day === day) ? d.symbols : {}))
      .catch(() => {});
    return () => ctl.abort();
  }, [state, asOf, day]);

  const value = useMemo(() => {
    const names = {};
    const cost = {};
    (positions.data?.positions || []).forEach((p) => {
      if (p.symbol && p.description) names[p.symbol] = p.description;
      if (p.symbol && !p.isCash) cost[p.symbol] = (cost[p.symbol] || 0) + (p.cost || 0);
    });
    const { symbols, cash } = groupLive(live.data?.rows || []);
    return { live: live.data, symbols, cash, names, cost, intraday, loading: live.loading && !live.data, error: live.error, reload: live.reload };
  }, [live.data, live.loading, live.error, live.reload, positions.data, intraday]);

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

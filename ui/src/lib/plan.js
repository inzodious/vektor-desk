import { useMemo } from 'react';
import { useApi } from './api.js';

export function planLimits(profile, rules) {
  const drift = (rules?.rules || []).find((r) => r.kind === 'drift_max_pts' && r.enabled !== false);
  return {
    driftPts: drift?.params?.pts ?? 5,
    satelliteCap: profile?.profile?.opportunity?.satellite_cap_pct ?? 10,
    version: profile?.version ?? null,
    rulesVersion: rules?.version ?? profile?.rules_version ?? null,
  };
}

export function usePlanLimits() {
  const profile = useApi('/api/decisions/profile');
  const rules = useApi('/api/decisions/rules');
  return useMemo(() => planLimits(profile.data, rules.data), [profile.data, rules.data]);
}

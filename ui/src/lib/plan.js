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

// ---------- what drift is measured against ----------
export function referenceOf(data) {
  const judged = !(data && data.source && data.judged === false);
  const name = data?.name || (judged ? 'Your plan' : 'Safe mix');
  return { judged, name, mix: judged ? 'its target' : `the ${name.toLowerCase()}`, note: judged ? null : data?.note || null };
}

export function driftWords(ref, limits) {
  if (ref.judged) return { judged: true, label: 'Largest drift', line: `Rebalance at ${limits.driftPts}`, hero: (v) => `largest drift ${v.toFixed(1)} pts`, tag: 'Drift', rows: 'Drift by fund', target: 'Target', gap: 'Drift', split: 'split to pull every fund back toward its target.', step: 'drift' };
  return {
    judged: false,
    label: `Vs ${ref.mix}`,
    line: 'A yardstick, not a target',
    hero: (v) => `up to ${v.toFixed(1)} pts from ${ref.mix}`,
    tag: `Vs ${ref.mix}`,
    rows: `Against ${ref.mix}`,
    target: ref.name,
    gap: 'Gap',
    split: `split the way ${ref.mix} would, as a yardstick.`,
    step: 'gap',
  };
}

export const driftTone = (ref, value, limits) => (ref.judged && value != null && Math.abs(value) >= limits.driftPts ? 'watch' : undefined);

export function useReference() {
  const api = useApi('/api/engine/reference');
  return useMemo(() => referenceOf(api.data), [api.data]);
}

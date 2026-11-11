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

export function ruleState(rule, pass, ref) {
  if (rule.enabled === false) return { tone: '', word: 'Off', icon: 'flag' };
  if (rule.kind === 'drift_max_pts' && !ref.judged) return { tone: '', word: 'Not judged', icon: 'info', line: `${ref.mix.charAt(0).toUpperCase()}${ref.mix.slice(1)} is a yardstick, not a target` };
  if (pass == null) return { tone: 'info', word: 'Not checked', icon: 'flag' };
  return pass >= 1 ? { tone: 'ok', word: 'Passing', icon: 'check' } : { tone: 'watch', word: 'Heads up', icon: 'flag' };
}

export function judgedRuleRows(rows, rules, ref) {
  if (ref.judged) return rows;
  const drift = new Set((rules || []).filter((r) => r.kind === 'drift_max_pts').map((r) => r.id));
  return rows.filter((r) => !drift.has(r.scope_id));
}

export function useReference() {
  const api = useApi('/api/engine/reference');
  return useMemo(() => referenceOf(api.data), [api.data]);
}

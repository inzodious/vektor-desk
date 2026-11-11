const NOTE = 'No plan of your own is loaded, so drift and the benchmark are measured against the built-in safe mix. It is a yardstick, not a target, and the drift rule is not judged against it.';
const SAFE = { FXAIX: 40, SCHD: 20, FTIHX: 10, FTEC: 10, NLR: 5, GRID: 5, ICLN: 5, UFO: 5 };
const NEXT = { SCHD: 300, FTIHX: 150, NLR: 50 };
const REBASED = ['plan.target', 'plan.drift', 'plan.next_deposit', 'plan.drift_max'];
const DRIFT_RULE = 'drift-max';
const round = (v) => Math.round(v * 100) / 100;

// ---------- reference: the plan, and the safe mix as a yardstick ----------
export function referenceFixtures(metrics) {
  const rows = metrics.metrics;
  const holding = (id) => rows.filter((m) => m.metric_id === id && m.scope === 'holding');
  const plan = Object.fromEntries(holding('plan.target').map((m) => [m.scope_id, m.value]));
  const weight = Object.fromEntries(holding('plan.weight').map((m) => [m.scope_id, m.value]));
  const like = holding('plan.target')[0];
  const max = rows.find((m) => m.metric_id === 'plan.drift_max');
  const row = (metric_id, scope_id, value) => ({ ...like, metric_id, scope_id, value: round(value), quality: 'modelled' });
  const drift = Object.fromEntries(Object.entries(SAFE).map(([s, t]) => [s, (weight[s] || 0) - t]));
  const rebased = [
    ...rows.filter((m) => !REBASED.includes(m.metric_id) && !(m.metric_id === 'plan.rules' && m.scope_id === DRIFT_RULE)),
    ...Object.keys(SAFE)
      .filter((s) => weight[s] == null)
      .map((s) => ({ ...row('plan.weight', s, 0), quality: 'ok' })),
    ...Object.entries(SAFE).map(([s, t]) => row('plan.target', s, t)),
    ...Object.entries(drift).map(([s, d]) => row('plan.drift', s, d)),
    ...Object.entries(NEXT).map(([s, v]) => row('plan.next_deposit', s, v)),
    { ...max, value: round(Math.max(...Object.values(drift).map(Math.abs))), quality: 'modelled' },
  ];
  return {
    'engine.reference': { as_of: metrics.as_of, source: 'plan', name: 'Your plan', weights: plan, judged: true, note: null },
    'engine.reference.yardstick': { as_of: metrics.as_of, source: 'safe_mix', name: 'Safe mix', weights: SAFE, judged: false, note: NOTE },
    'engine.metrics.yardstick': { ...metrics, metrics: rebased },
  };
}

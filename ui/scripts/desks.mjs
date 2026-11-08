const FIRST_RUN = ['plan_keeper', 'tax'];
const FILINGS = { desk: 'filings', title: 'Filings desk', model: 'opus', effort: 'high', live: true, last_run: null, next_run: null, week: { runs: 0, turns: 0, tokens: 0, cap: 7 } };
const YAML = { plan_keeper: true, tax: true, risk: true, research: true, skeptic: null, scout: false, strategy: null, filings: null };
const APP = { scout: true, filings: true };

// ---------- desks: guard on and not ready, guard lifted ----------
export function desksFixtures(status) {
  const desks = status.desks.some((d) => d.desk === 'filings') ? status.desks : [...status.desks, { ...FILINGS, model: status.desks[0]?.model || FILINGS.model }];
  const shaped = (guardOn) =>
    desks.map((d) => {
      const app = d.app !== undefined ? d.app : APP[d.desk] ?? null;
      const yaml = d.yaml !== undefined ? d.yaml : YAML[d.desk] ?? null;
      const source = d.source || (app != null ? 'app' : yaml != null ? 'desk.yaml' : 'default');
      const enabled = app ?? yaml ?? d.desk !== 'filings';
      const guarded = guardOn && !FIRST_RUN.includes(d.desk);
      return { ...d, enabled, source, app, yaml, guarded, next_run: guarded || !enabled ? null : d.next_run };
    });
  const guard = { on: true, allowed: FIRST_RUN, ready: false, why: 'Tax desk hasn’t finished a run yet', ...(status.guard || {}) };
  return {
    'agents.status': { ...status, enabled_source: status.enabled_source || 'default', guard: { ...guard, on: true }, desks: shaped(true) },
    'agents.status.lifted': { ...status, enabled_source: status.enabled_source || 'default', guard: { ...guard, on: false, ready: true, why: null }, desks: shaped(false) },
  };
}

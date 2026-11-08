const day = (iso) => iso.replace(/^\d{4}-\d{2}-\d{2}/, '2026-11-08');
const restamp = (v) => (v ? { ...v, created_at: v.created_at && day(v.created_at), answered_at: v.answered_at && day(v.answered_at), taken_at: v.taken_at && day(v.taken_at) } : v);

// ---------- risk check: taken, fresh ----------
export function riskFixtures(risk, versions) {
  const list = (versions?.versions || []).map(restamp);
  return {
    'decisions.risk': { ...risk, current: restamp(risk.current) },
    'decisions.risk.fresh': { ...risk, current: null },
    'decisions.risk.versions': { versions: list },
    'decisions.risk.versions.fresh': { versions: [] },
  };
}

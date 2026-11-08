const AS_OF = '2026-11-09';

// ---------- conviction holds: two holds, none yet, before the risk check ----------
export function convictionsFixtures(risk) {
  const c = risk?.current;
  const suggested = c ? { band_min_pct: 0, band_max_pct: c.speculative_max_pct, from_band: c.band, label: c.label } : null;
  const ceiling = suggested?.band_max_pct ?? 10;
  const items = [
    { rule_id: 'conviction-acme', symbol: 'ACME', band_min_pct: 0, band_max_pct: ceiling, note: 'Long-term bet on the satellite build-out', enabled: true, weight_pct: Math.round((ceiling + 2.4) * 100) / 100, weight_as_of: AS_OF, status: 'above' },
    { rule_id: 'conviction-orbt', symbol: 'ORBT', band_min_pct: 2, band_max_pct: 8, note: null, enabled: true, weight_pct: 5.1, weight_as_of: AS_OF, status: 'inside' },
  ];
  return {
    'decisions.convictions': { items, suggested },
    'decisions.convictions.empty': { items: [], suggested },
    'decisions.convictions.fresh': { items: [], suggested: null },
  };
}

export const EDITABLE = ['industry_focus', 'opportunity', 'tax', 'growth', 'usage', 'agents', 'deposits', 'alerts', 'rules'];

export function withEditable(profile) {
  return profile && !Array.isArray(profile.editable) ? { ...profile, editable: EDITABLE } : profile;
}

// ---------- synthetic scored filings until the demo engine serves them ----------
const SIGNALS = {
  ACME: [
    { accession: '0000000000-26-000311', form: '8-K', filed_at: '2026-11-03', scored_at: '2026-11-03T21:40:00Z', direction: 1, confidence: 0.72, event_type: 'contract', horizon_days: 10, rationale: 'New launch contract adds a second customer; terms are synthetic.', in_lane: true, lane_open: true },
    { accession: '0000000000-26-000287', form: '10-Q', filed_at: '2026-10-30', scored_at: '2026-10-30T22:05:00Z', direction: 0, confidence: 0.55, event_type: 'earnings', horizon_days: 5, rationale: 'Quarter landed close to guidance.', in_lane: false, lane_open: false },
    { accession: '0000000000-26-000254', form: '4', filed_at: '2026-10-21', scored_at: '2026-10-21T20:30:00Z', direction: -1, confidence: 0.4, event_type: 'insider_sell', horizon_days: 5, rationale: 'Director sale under a pre-set plan.', in_lane: false, lane_open: false },
  ],
  NOVA: [{ accession: '0000000000-26-000402', form: '8-K', filed_at: '2026-11-04', scored_at: '2026-11-04T21:15:00Z', direction: -1, confidence: 0.61, event_type: 'dilution', horizon_days: 10, rationale: 'At-the-market share program announced.', in_lane: false, lane_open: false }],
};

export function withFilingSignals(sym, body) {
  if (!body || Array.isArray(body.filing_signals)) return body;
  return { ...body, filing_signals: SIGNALS[sym] || [] };
}

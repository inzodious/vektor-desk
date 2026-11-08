const num = (o) => ({ price: o.price, day_move_pct: o.move, drop_from_high_pct: o.drop, move_z: o.z, high_52w: o.high, ret_1y_pct: o.ret, valuation_value: o.vv, valuation_pctile: o.vp });

const hit = (o) => ({
  signal_id: `${o.as_of}-${o.symbol}`,
  symbol: o.symbol,
  name: o.name,
  as_of: o.as_of,
  list: o.list,
  reason: o.reason,
  price: o.price,
  drop_from_high_pct: o.drop,
  move_z: o.z,
  valuation: o.vv == null ? null : { metric: o.metric, value: o.vv, pctile_own: o.vp },
  numbers: num(o),
  case: o.case || null,
});

const ROWS = [
  hit({ symbol: 'ACME', name: 'Acme Rockets (synthetic)', as_of: '2026-11-06', list: 'held', reason: 'crossed_20', price: 2.96, move: -4.1, drop: -21.4, z: -1.6, high: 3.77, ret: -38.2, metric: 'price_vs_5y_avg', vv: 0.62, vp: 0.08, case: { verdict: 'wait', case: 'The drop follows a delayed launch, not a funding problem. Wait for the next schedule update before adding.', risks: 'Another slip would push cash needs into next year.', confidence: 0.6, horizon_days: 30, numbers_cited: ['drop_from_high_pct'], model: 'claude', written_at: '2026-11-06T23:10:00Z', run_id: 'r-disc-1' } }),
  hit({ symbol: 'FTEC', name: 'Fidelity MSCI Information Technology ETF', as_of: '2026-11-06', list: 'held', reason: 'big_down_day', price: 182.4, move: -3.2, drop: -7.9, z: -2.4, high: 198.0, ret: 21.6, metric: 'price_vs_5y_avg', vv: 1.18, vp: 0.71, case: { verdict: 'buy', case: 'A broad tech fund down 2.4 swings on a rate scare; nothing in the holdings changed. Fits the plan if it goes to the tech sleeve.', risks: 'Rates could keep pressing growth names for weeks.', confidence: 0.7, horizon_days: 90, numbers_cited: ['move_z'], model: 'claude', written_at: '2026-11-06T23:12:00Z', run_id: 'r-disc-1' } }),
  hit({ symbol: 'MSFT', name: 'Microsoft', as_of: '2026-11-05', list: 'quality', reason: 'crossed_10', price: 402.1, move: -1.8, drop: -10.6, z: -1.2, high: 449.8, ret: 8.4, metric: 'pe_annual', vv: 29.4, vp: 0.22 }),
  hit({ symbol: 'NOVA', name: 'Nova Fission (synthetic)', as_of: '2026-11-04', list: 'watchlist', reason: 'crossed_30', price: 24.1, move: -6.4, drop: -31.2, z: -2.9, high: 35.0, ret: -12.0, metric: 'price_vs_5y_avg', vv: 0.84, vp: 0.3, case: { verdict: 'avoid', case: 'The share sale behind the drop dilutes holders by about a tenth; the plan rules out new single stocks.', risks: 'Missing a rebound if the offering prices well.', confidence: 0.65, horizon_days: 60, numbers_cited: ['drop_from_high_pct'], model: 'claude', written_at: '2026-11-05T22:40:00Z', run_id: 'r-disc-0' } }),
  hit({ symbol: 'COST', name: 'Costco', as_of: '2026-11-03', list: 'quality', reason: 'big_down_day', price: 881.0, move: -2.6, drop: -9.1, z: -2.2, high: 969.0, ret: 14.1, metric: 'pe_annual', vv: 48.2, vp: 0.55 }),
];

// ---------- discount scan: hits, quiet week, first day ----------
export function discountsFixtures(api) {
  const base = { as_of: '2026-11-06', scanned: 31, rule: api?.rule || 'After the close: a down day of 2+ standard deviations of its last year and 1% or more, or a first close 10, 20 or 30% under its 52-week high', note: null };
  return {
    'engine.discounts': { ...base, rows: ROWS },
    'engine.discounts.quiet': { ...base, rows: [], note: 'No discounts in the last 10 days.' },
    'engine.discounts.fresh': { as_of: null, scanned: 0, rule: base.rule, rows: [], note: 'The first scan runs after the close.' },
  };
}

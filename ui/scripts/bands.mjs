const HORIZONS = [1, 5, 10, 20, 40];
const POLICY_YEARS = [1, 5, 10, 20];
const LADDER = [500, 600, 1000, 1500, 2000, 3000, 4000, 5000, 6000, 8000, 10000];
const START = 16770;
const DEPOSIT = 600;
const FI = 1000000;
const TARGET_YEARS = 8.2;
const CUT = 2;
const MAX_YEARS = 40;

const MIXES = [
  { id: 'dip-buy', name: 'Dip-buy', weights: { IVV: 0.6, FTEC: 0.2, VXUS: 0.15, BND: 0.05 }, cash: 0.2, mu: 0.067, sigma: 0.11, beta: 0.78, rank: 2, fit: 'below', worst: -12.4, sharpe: 0.58, fee: 0.04 },
  { id: 'safe-mix', name: 'Safe mix', weights: { IVV: 0.6, FTEC: 0.2, VXUS: 0.15, BND: 0.05 }, cash: 0, mu: 0.072, sigma: 0.14, beta: 0.98, rank: 3, fit: 'fits', worst: -17.8, sharpe: 0.55, fee: 0.04 },
  { id: 'tech-tilt', name: 'Aggressive tech tilt', weights: { IVV: 0.5, FTEC: 0.3, SMH: 0.1, VXUS: 0.1 }, cash: 0, mu: 0.076, sigma: 0.18, beta: 1.12, rank: 4, fit: 'fits', worst: -26.9, sharpe: 0.62, fee: 0.08 },
  { id: 'as-held', name: 'As held', weights: { IVV: 0.45, ACME: 0.25, FTEC: 0.2, VXUS: 0.1 }, cash: 0.04, mu: 0.073, sigma: 0.19, beta: 1.21, rank: 5, fit: 'above', worst: -34.2, sharpe: 0.41, fee: 0.03 },
];
const TOPPED = { id: 'rebalanced', name: 'Topped back up to today’s weights', mu: 0.074, sigma: 0.29, beta: 1.21, rank: 5, worst: -41.8 };
const TRIM = { mu: 0.074, sigma: 0.155, beta: 1.06, rank: 3, worst: -21.5 };
const SHARE = {
  hold: [{ p10: 14, p50: 21, p90: 30 }, { p10: 6, p50: 13, p90: 27 }, { p10: 3, p50: 8, p90: 24 }, { p10: 1, p50: 4, p90: 18 }],
  rebalance: [24, 24, 24, 24].map((v) => ({ p10: v, p50: v, p90: v })),
  trim: [{ p10: 9, p50: 13, p90: 15 }, { p10: 4, p50: 9, p90: 15 }, { p10: 2, p50: 6, p90: 14 }, { p10: 1, p50: 3, p90: 11 }],
};
const POLICIES = [
  { id: 'hold', name: 'Hold', rule: 'Nothing sold or topped up; new money goes to the safe mix.' },
  { id: 'rebalance', name: 'Rebalance', rule: 'Topped back up, or trimmed, to today’s weight every month.' },
  { id: 'trim', name: 'Trim to band', rule: 'Held, and sold back to the top of its band whenever it grows past it.' },
];

const fv = (mu, years, deposit = DEPOSIT) => {
  const g = (1 + mu) ** years;
  return START * g + deposit * 12 * ((g - 1) / mu);
};

const band = (m, years) => {
  const mid = fv(m.mu, years);
  const spread = Math.exp(1.2816 * m.sigma * Math.sqrt(years));
  const contributed = START + DEPOSIT * 12 * years;
  return { years, p10: Math.round(mid / spread), p50: Math.round(mid), p90: Math.round(mid * spread), contributed, chance_loss: Number((0.42 / Math.sqrt(years)).toFixed(3)), chance_below_contributed: Number((0.4 / Math.sqrt(years)).toFixed(3)), return_p50_pct: Number((m.mu * 100).toFixed(2)) };
};

const reach = (mu, deposit) => {
  if (mu <= 0) return null;
  for (let m = 1; m <= MAX_YEARS * 12; m += 1) if (fv(mu, m / 12, deposit) >= FI) return Number((m / 12).toFixed(2));
  return null;
};

const luck = (m) => 0.18 * m.sigma;

const chance = (m, deposit) => {
  const mid = reach(m.mu, deposit);
  if (mid == null) return 0;
  const z = (TARGET_YEARS - mid) / (mid * 1.6 * m.sigma);
  return Number((1 / (1 + Math.exp(-1.7 * z))).toFixed(4));
};

const fiYears = (m, deposit = DEPOSIT) => ({ p10: reach(m.mu + luck(m), deposit), p50: reach(m.mu, deposit), p90: reach(m.mu - luck(m), deposit) });

const fiTime = (m, goal) => (goal ? LADDER.map((deposit) => {
  const y = fiYears(m, deposit);
  return { deposit, years_p10: y.p10, years_p50: y.p50, years_p90: y.p90, chance_by_target: chance(m, deposit) };
}) : null);

const core = (m, { goal = true, years = HORIZONS } = {}) => ({
  risk_rank: m.rank,
  worst_year_p10_pct: m.worst,
  cvar95_1y_pct: Number((m.worst * 1.6).toFixed(1)),
  max_drawdown_pct: Number((m.worst * 1.3).toFixed(1)),
  drawdown_10y: { p10: Number((m.worst * 2).toFixed(1)), p50: Number((m.worst * 1.3).toFixed(1)), p90: Number((m.worst * 0.8).toFixed(1)) },
  p50_value_10y: band(m, 10).p50,
  chance_fi: goal ? chance(m, DEPOSIT) : null,
  fi_years: goal ? fiYears(m) : null,
  bands: years.map((y) => band(m, y)),
});

const lowered = (m) => ({ ...m, mu: m.mu - (CUT / 100) * m.beta * (1 - (m.cash || 0)), worst: Number((m.worst - 1.4 * m.beta).toFixed(1)), rank: Math.min(5, m.rank + (m.id === 'tech-tilt' ? 1 : 0)) });

const row = (m, { profile = true, goal = true } = {}) => ({
  id: m.id,
  name: m.name,
  weights: m.weights,
  cash: m.cash,
  priced_from: Object.fromEntries(Object.keys(m.weights).map((s) => [s, s])),
  status: 'ok',
  fit: profile ? m.fit : null,
  ...core(m, { goal }),
  fi_time: fiTime(m, goal),
  lower: { ...core(lowered(m), { goal }), fi_time: fiTime(lowered(m), goal) },
  sharpe: m.sharpe,
  backtest: { months: 120, cagr_pct: Number((m.mu * 130).toFixed(1)), vol_pct: Number((m.sigma * 100).toFixed(1)), sharpe: m.sharpe, sortino: Number((m.sharpe * 1.4).toFixed(2)), max_drawdown_pct: Number((m.worst * 1.2).toFixed(1)), calmar: 0.5, worst_year_pct: m.worst, hit_rate: 0.6, start: '2016-11', end: '2026-10' },
  long_history: { months: 1205, cagr_pct: Number((m.mu * 100).toFixed(1)), max_drawdown_pct: Number((m.worst * 2.2).toFixed(1)), worst_year_pct: Number((m.worst * 1.5).toFixed(1)), start: '1926-07', end: '2026-10' },
  model: { beta: m.beta, alpha_dropped_pct: 1.2, resid_vol_pct: 8, months: 120, start: '2016-11', end: '2026-10' },
  fee_pct: m.fee,
  policy: m.id === 'as-held' ? 'hold' : 'rebalance',
  proxy_note: m.id === 'as-held' ? 'FXAIX trades as IVV' : null,
  notes: [],
  ...(m.id === 'as-held'
    ? {
        sleeves: [
          { id: 'ACME', weight: 0.24, beta: 1.86, resid_vol_pct: 62.4, fee_pct: 0, months: 82 },
          { id: 'rest', weight: 0.72, beta: 1.04, resid_vol_pct: 3.1, fee_pct: 0.04, months: 120, holds: ['FTEC', 'IVV', 'VXUS'] },
          { id: 'cash', weight: 0.04, beta: 0, resid_vol_pct: 0, fee_pct: 0, months: null },
          { id: 'new-money', weight: 0, beta: 0.98, resid_vol_pct: 2.3, fee_pct: 0.04, months: 120, to: 'safe-mix' },
        ],
        new_money: 'safe-mix',
        variants: [{ id: TOPPED.id, name: TOPPED.name, ...core(TOPPED, { goal }) }],
      }
    : {}),
});

const policy = (p, m, goal) => {
  const got = core(m, { goal, years: POLICY_YEARS });
  return { ...p, ...got, bands: got.bands.map((b, i) => ({ ...b, weight_pct: SHARE[p.id][i] })) };
};

const convictions = (goal = true) => {
  const held = MIXES.find((m) => m.id === 'as-held');
  return [
    {
      symbol: 'ACME',
      status: 'ok',
      weight_pct: 24,
      band_min_pct: 5,
      band_max_pct: 15,
      beta: 1.86,
      resid_vol_pct: 62.4,
      months: 82,
      policies: [policy(POLICIES[0], held, goal), policy(POLICIES[1], TOPPED, goal), policy(POLICIES[2], TRIM, goal)],
    },
  ];
};

const CAVEATS = [
  'Alpha is set to zero: no mix gets credit for beating the market in its own history.',
  'Leftover swings are drawn month by month and holding by holding, so a fund’s own long slumps and stocks that fall together are understated.',
  'International and bond funds are modelled through their link to the US market since 1926.',
  'As held is left to drift: nothing is sold or topped up, and new money goes to the safe mix.',
  'The lower-return case takes 2 points a year off what stocks earn over cash.',
  'Every mix pays its funds’ yearly fees. Taxes and the margin debit are not modelled.',
];
const METHOD = 'Each mix is fitted to the US market on its own price history (beta plus leftover swings, alpha set to zero), then replayed in 12-month blocks of market history since 1926. As held is fitted holding by holding and left to drift';

// ---------- synthetic bands: with a risk band and FI goal, without, not ready ----------
export function bandsFixtures(api) {
  const base = { ...api, as_of: '2026-11-06', status: 'ok', book: 'as-held', start_value: START, monthly_deposit: DEPOSIT, deposit_source: 'activity', deposit_note: 'from your last 12 months of deposits, net of withdrawals', deposit_ladder: LADDER, fi_number: FI, target_date: '2035-01-01', fi_years_max: MAX_YEARS, real: false, horizons: HORIZONS, policy_years: POLICY_YEARS, premium_cut_pts: CUT, paths: 2000, history: { start: '1926-07', end: '2026-10', months: 1203 }, method: METHOD, caveats: CAVEATS };
  const profile = { band: 4, label: 'Moderately aggressive', worst_year_loss_pct: 33, version: 2 };
  const tilt = MIXES.find((m) => m.id === 'tech-tilt');
  return {
    'engine.bands': { ...base, profile, rows: MIXES.map((m) => row(m)), convictions: convictions() },
    'engine.bands.noprofile': { ...base, profile: null, fi_number: null, target_date: null, deposit_ladder: [], rows: MIXES.map((m) => row(m, { profile: false, goal: false })), convictions: [] },
    'engine.bands.partial': { ...base, profile, rows: [...MIXES.filter((m) => m !== tilt).map((m) => row(m)), { id: tilt.id, name: tilt.name, weights: tilt.weights, cash: 0, priced_from: {}, status: 'not_ready', note: 'Needs 36 months of prices for its funds; has 14.', notes: [] }], convictions: [{ symbol: 'ACME', status: 'not_ready', band_min_pct: 5, band_max_pct: 15, note: 'Needs 36 months of ACME prices and at least 2% of the book.' }] },
    'engine.bands.fresh': { as_of: null, status: 'not_ready', rows: [], book: 'as-held', note: 'The bands are built with the daily numbers. They show here after the first run with price history.' },
  };
}

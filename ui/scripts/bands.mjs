const HORIZONS = [1, 5, 10, 20, 40];
const START = 16770;
const DEPOSIT = 600;
const FI = 1000000;

const MIXES = [
  { id: 'dip-buy', name: 'Dip-buy', weights: { IVV: 0.6, FTEC: 0.2, VXUS: 0.15, BND: 0.05 }, cash: 0.2, mu: 0.064, sigma: 0.11, rank: 2, fit: 'below', worst: -12.4, sharpe: 0.58, chance: 0.31 },
  { id: 'safe-mix', name: 'Safe mix', weights: { IVV: 0.6, FTEC: 0.2, VXUS: 0.15, BND: 0.05 }, cash: 0, mu: 0.072, sigma: 0.14, rank: 3, fit: 'fits', worst: -17.8, sharpe: 0.55, chance: 0.42 },
  { id: 'tech-tilt', name: 'Aggressive tech tilt', weights: { IVV: 0.5, FTEC: 0.3, SMH: 0.1, VXUS: 0.1 }, cash: 0, mu: 0.081, sigma: 0.18, rank: 4, fit: 'fits', worst: -26.9, sharpe: 0.62, chance: 0.53 },
  { id: 'as-held', name: 'As held', weights: { IVV: 0.45, ACME: 0.25, FTEC: 0.2, VXUS: 0.1 }, cash: 0.04, mu: 0.083, sigma: 0.27, rank: 5, fit: 'above', worst: -38.6, sharpe: 0.41, chance: 0.47 },
];

const fv = (mu, years) => {
  const g = (1 + mu) ** years;
  return START * g + DEPOSIT * 12 * ((g - 1) / mu);
};

const band = (m, years) => {
  const mid = fv(m.mu, years);
  const spread = Math.exp(1.2816 * m.sigma * Math.sqrt(years));
  const contributed = START + DEPOSIT * 12 * years;
  return { years, p10: Math.round(mid / spread), p50: Math.round(mid), p90: Math.round(mid * spread), contributed, chance_loss: Number((0.42 / Math.sqrt(years)).toFixed(3)), chance_below_contributed: Number((0.4 / Math.sqrt(years)).toFixed(3)), return_p50_pct: Number((m.mu * 100).toFixed(2)) };
};

const row = (m, { profile = true, goal = true } = {}) => ({
  id: m.id,
  name: m.name,
  weights: m.weights,
  cash: m.cash,
  priced_from: Object.fromEntries(Object.keys(m.weights).map((s) => [s, s])),
  status: 'ok',
  risk_rank: m.rank,
  fit: profile ? m.fit : null,
  worst_year_p10_pct: m.worst,
  cvar95_1y_pct: Number((m.worst * 1.6).toFixed(1)),
  p50_value_10y: band(m, 10).p50,
  chance_fi: goal ? m.chance : null,
  sharpe: m.sharpe,
  max_drawdown_pct: Number((m.worst * 1.3).toFixed(1)),
  drawdown_10y: { p10: Number((m.worst * 2).toFixed(1)), p50: Number((m.worst * 1.3).toFixed(1)), p90: Number((m.worst * 0.8).toFixed(1)) },
  bands: HORIZONS.map((y) => band(m, y)),
  backtest: { months: 120, cagr_pct: Number((m.mu * 130).toFixed(1)), vol_pct: Number((m.sigma * 100).toFixed(1)), sharpe: m.sharpe, sortino: Number((m.sharpe * 1.4).toFixed(2)), max_drawdown_pct: Number((m.worst * 1.2).toFixed(1)), calmar: 0.5, worst_year_pct: m.worst, hit_rate: 0.6, start: '2016-11', end: '2026-10' },
  long_history: { months: 1205, cagr_pct: Number((m.mu * 100).toFixed(1)), max_drawdown_pct: Number((m.worst * 2.2).toFixed(1)), worst_year_pct: Number((m.worst * 1.5).toFixed(1)), start: '1926-07', end: '2026-10' },
  model: { beta: 1, alpha_dropped_pct: 1.2, resid_vol_pct: 8, months: 120, start: '2016-11', end: '2026-10' },
  fee_pct: 0,
  proxy_note: m.id === 'as-held' ? 'FXAIX trades as IVV' : null,
  notes: [],
});

// ---------- synthetic bands: with a risk band and FI goal, without, not ready ----------
export function bandsFixtures(api) {
  const base = { ...api, as_of: '2026-11-06', status: 'ok', book: 'as-held', start_value: START, monthly_deposit: DEPOSIT, deposit_source: 'activity', deposit_note: 'from your last 12 months of deposits', fi_number: FI, target_date: '2035-01-01', real: false, horizons: HORIZONS, paths: 2000, history: { start: '1926-07', end: '2026-10', months: 1203 } };
  const profile = { band: 4, label: 'Moderately aggressive', worst_year_loss_pct: 33, version: 2 };
  const tilt = MIXES.find((m) => m.id === 'tech-tilt');
  return {
    'engine.bands': { ...base, profile, rows: MIXES.map((m) => row(m)) },
    'engine.bands.noprofile': { ...base, profile: null, fi_number: null, target_date: null, rows: MIXES.map((m) => row(m, { profile: false, goal: false })) },
    'engine.bands.partial': { ...base, profile, rows: [...MIXES.filter((m) => m !== tilt).map((m) => row(m)), { id: tilt.id, name: tilt.name, weights: tilt.weights, cash: 0, priced_from: {}, status: 'not_ready', note: 'Needs 36 months of prices for its funds; has 14.', notes: [] }] },
    'engine.bands.fresh': { as_of: null, status: 'not_ready', rows: [], book: 'as-held', note: 'The bands are built with the daily numbers. They show here after the first run with price history.' },
  };
}

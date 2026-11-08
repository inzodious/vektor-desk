const row = (r) => ({ version: 1, kind: 'strategy', as_of: '2026-11-06', open_positions: 0, account: null, reward_risk: null, backtest: null, ...r });
const rr = (sharpe, sortino, days, source = 'sub_ledger') => ({ source, days, ann_return_pct: null, sharpe, sortino, max_drawdown_pct: null, calmar: null, hit_rate: null });
const acct = (value, cash, ret) => ({ as_of: '2026-11-06', sleeve: 1000, cash, value, return_pct: ret });

// ---------- synthetic paper leaderboard until the engine serves real rows ----------
export function leaderboardFixtures() {
  const base = { as_of: '2026-11-06', benchmark: 'IWM', gate_days: 182, note: null };
  const rows = [
    row({ id: 'low-vol-sectors', name: 'Calm sectors', status: 'eligible', started: '2026-04-20', days_live: 200, days_to_eligible: 0, eligible_on: '2026-10-19', waiting_on: null, return_pct: 6.8, bench_return_pct: 3.1, excess_pts: 3.7, max_drawdown_pct: -4.2, trades: 18, open_positions: 3, account: acct(1061.4, 212.3, 6.1), reward_risk: rr(1.12, 1.58, 200), backtest: { source: 'lab_holdout', start: '2023-01-01', end: '2025-12-31', ann_return_pct: 9.4, sharpe: 0.98, sortino: 1.37, max_drawdown_pct: -8.1, calmar: 1.1, hit_rate: null } }),
    row({ id: 'filings-lane', kind: 'lane', name: 'Filings lane: buy small caps Claude scores +1 or better', status: 'paper', started: '2026-10-05', days_live: 32, days_to_eligible: 150, eligible_on: '2027-04-05', waiting_on: 'time', return_pct: 4.1, bench_return_pct: 1.2, excess_pts: 2.9, max_drawdown_pct: -3.4, trades: 3, open_positions: 1, account: acct(1012.0, 905.5, 1.2) }),
    row({ id: 'filings-lane-strong', kind: 'lane', name: 'Filings lane: +2 scores only, hold 10 sessions', status: 'paper', started: '2026-10-20', days_live: 17, days_to_eligible: 165, eligible_on: '2027-04-20', waiting_on: 'time', return_pct: 1.6, bench_return_pct: 0.4, excess_pts: 1.2, max_drawdown_pct: -1.1, trades: 1, open_positions: 1, account: acct(1004.8, 899.0, 0.5) }),
    row({ id: 'tech-tilt', kind: 'mix', name: 'Aggressive tech tilt', status: 'paper', started: '2026-11-03', days_live: 4, days_to_eligible: 178, eligible_on: '2027-05-04', waiting_on: 'time', return_pct: 0.6, bench_return_pct: 0.2, excess_pts: 0.4, max_drawdown_pct: -0.8, trades: 4, open_positions: 4, account: acct(1006.1, 3.2, 0.6), backtest: { source: 'bands', start: '2016-11', end: '2026-10', ann_return_pct: 10.5, sharpe: 0.62, sortino: 0.87, max_drawdown_pct: -32.3, calmar: 0.5, hit_rate: 0.6 } }),
    row({ id: 'sector-momentum', name: 'Sector momentum', status: 'paper', started: '2026-06-30', days_live: 129, days_to_eligible: 53, eligible_on: '2026-12-29', waiting_on: 'time', return_pct: 0.9, bench_return_pct: 5.2, excess_pts: -4.3, max_drawdown_pct: -5.0, trades: 23, open_positions: 4, reward_risk: rr(0.3, 0.45, 94, 'forward_record') }),
    row({ id: 'dip-buyer', name: 'Buy the deepest dip', status: 'retired', started: '2026-05-01', days_live: 189, days_to_eligible: null, eligible_on: null, waiting_on: null, return_pct: -7.9, bench_return_pct: 2.0, excess_pts: -9.9, max_drawdown_pct: -14.2, trades: 31 }),
  ];
  const early = row({ id: 'filings-lane', kind: 'lane', name: 'Filings lane: buy small caps Claude scores +1 or better', status: 'paper', started: '2026-11-05', days_live: 2, days_to_eligible: 180, eligible_on: '2027-05-06', waiting_on: 'time', return_pct: null, bench_return_pct: null, excess_pts: null, max_drawdown_pct: null, trades: 1, open_positions: 1 });
  const empty = { ...base, as_of: null, rows: [], note: 'No strategies are paper trading yet. The filings lane starts the morning after the first filing is scored.' };
  return {
    'engine.lab.leaderboard': { ...base, rows },
    'engine.lab.leaderboard.early': { ...base, rows: [early] },
    'engine.lab.leaderboard.empty': empty,
    'engine.lab.leaderboard.fresh': empty,
  };
}

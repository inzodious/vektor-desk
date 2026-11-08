import { signedPct } from './strategy.js';

export const FIT = {
  fits: { t: 'Fits your band', tone: 'ok' },
  below: { t: 'Calmer than your band', tone: 'info' },
  above: { t: 'Riskier than your band', tone: 'watch' },
};

// ---------- money ----------
export function money(v) {
  if (v == null || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  const sign = v < 0 ? '−' : '';
  if (a >= 1e6) return `${sign}$${Number((a / 1e6).toFixed(a >= 1e7 ? 1 : 2))}M`;
  if (a >= 1e4) return `${sign}$${Math.round(a / 1e3)}K`;
  if (a >= 1e3) return `${sign}$${Number((a / 1e3).toFixed(1))}K`;
  return `${sign}$${Math.round(a)}`;
}

// ---------- rows ----------
export function mixLine(row) {
  const parts = Object.entries(row?.weights || {})
    .sort((a, b) => b[1] - a[1])
    .map(([s, w]) => `${Math.round(w * 100)}% ${s}`);
  if (row?.cash) parts.push(`${Math.round(row.cash * 100)}% cash`);
  return parts.join(' · ');
}

export function fitBadge(fit) {
  return FIT[fit] || null;
}

export function bandAt(row, years) {
  return (row?.bands || []).find((b) => b.years === years) || null;
}

export function chanceText(v) {
  if (v == null) return null;
  if (v >= 0.995) return 'Nearly certain';
  if (v < 0.005) return 'Under 1%';
  return `${Math.round(v * 100)}%`;
}

export function rewardText(row) {
  const s = row?.sharpe ?? row?.backtest?.sharpe;
  if (s == null) return null;
  const word = s >= 1 ? 'strong' : s >= 0.5 ? 'fair' : s >= 0 ? 'thin' : 'negative';
  return { v: s.toFixed(2), word };
}

export function backtestLine(bt) {
  if (!bt) return null;
  const span = bt.start && bt.end ? `${bt.start} to ${bt.end}` : 'so far';
  const parts = [];
  if (bt.cagr_pct != null) parts.push(`${signedPct(bt.cagr_pct)} a year`);
  if (bt.max_drawdown_pct != null) parts.push(`worst dip ${signedPct(bt.max_drawdown_pct)}`);
  return `Real prices, ${span}: ${parts.join(', ')}`;
}

export function mixesHead(d) {
  const rows = d?.rows || [];
  const ready = rows.filter((r) => r.status === 'ok');
  const fitting = ready.filter((r) => r.fit === 'fits');
  const best = [...ready].filter((r) => r.chance_fi != null).sort((a, b) => b.chance_fi - a.chance_fi)[0] || null;
  return { total: rows.length, ready: ready.length, fitting: fitting.length, best };
}

export function assumptions(d) {
  if (!d) return [];
  const out = [];
  if (d.start_value != null) out.push(`Starts at ${money(d.start_value)}`);
  if (d.monthly_deposit != null) out.push(`adds ${money(d.monthly_deposit)} a month${d.deposit_note ? ` (${d.deposit_note})` : ''}`);
  if (d.fi_number != null) out.push(`FI at ${money(d.fi_number)}${d.target_date ? ` by ${String(d.target_date).slice(0, 4)}` : ''}`);
  if (d.paths) out.push(`${d.paths.toLocaleString('en-US')} paths through market history${d.history?.start ? ` since ${d.history.start.slice(0, 4)}` : ''}`);
  if (d.real) out.push('in today’s dollars');
  return out;
}

export function rankDots(rank) {
  return [1, 2, 3, 4, 5].map((n) => ({ n, on: rank != null && n <= rank }));
}

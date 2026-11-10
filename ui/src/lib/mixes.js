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
    .filter(([, w]) => Math.round(w * 100) > 0)
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
  return { total: rows.length, ready: ready.length, fitting: fitting.length };
}

// ---------- cases ----------
export function caseOf(row, lower) {
  return lower && row?.lower ? { ...row, ...row.lower } : row;
}

export function feeText(pct) {
  if (pct == null) return null;
  if (pct <= 0) return 'No fund fees';
  return `Fees ${Number(pct.toFixed(2))}% a year`;
}

// ---------- time to FI ----------
export function yearsNum(v) {
  if (v == null) return null;
  return v < 10 ? Number(v.toFixed(1)) : Math.round(v);
}

export function yearsText(v, max = 40) {
  if (v == null) return `${max}+ years`;
  const n = yearsNum(v);
  return n === 1 ? '1 year' : `${n} years`;
}

export function fiYear(asOf, years) {
  if (!asOf || years == null) return null;
  const start = Number(String(asOf).slice(0, 4)) + (Number(String(asOf).slice(5, 7)) - 1) / 12;
  return Math.floor(start + years);
}

export function fiLadder(d, lower = false) {
  const ready = (d?.rows || []).filter((r) => r.status === 'ok' && r.fi_time?.length);
  if (!ready.length) return null;
  const cases = ready.map((r) => ({ id: r.id, name: r.name, fi_time: caseOf(r, lower).fi_time || [] }));
  const ref = cases.find((c) => c.id === 'safe-mix') || cases[0];
  const mine = d.monthly_deposit ?? 0;
  const levels = ref.fi_time.map((x, i) => {
    const mids = cases.map((c) => ({ id: c.id, name: c.name, years: c.fi_time[i]?.years_p50 ?? null }));
    const sorted = [...mids].sort((a, b) => (a.years ?? Infinity) - (b.years ?? Infinity));
    return { deposit: x.deposit, current: x.deposit === mine, p10: x.years_p10, p50: x.years_p50, p90: x.years_p90, chance: x.chance_by_target, fastest: sorted[0], slowest: sorted[sorted.length - 1] };
  });
  return { ref: { id: ref.id, name: ref.name }, max: d.fi_years_max || 40, levels, mixes: cases.length };
}

export function ladderColumns(levels, room = 12) {
  const mine = levels.find((l) => l.current);
  const all = levels.filter((l) => l.current || !mine || mine.deposit === 0 || Math.abs(l.deposit - mine.deposit) / mine.deposit > 0.12);
  const rest = all.filter((l) => !l.current);
  let cols = all;
  for (let step = 2; cols.length > room && step < 8; step += 1) {
    const keep = new Set(rest.filter((_, i) => i % step === 0 || i === rest.length - 1));
    cols = all.filter((l) => l.current || keep.has(l));
  }
  return cols;
}

function gap(a, b, max) {
  if (a == null && b == null) return null;
  if (a == null || b == null) return { years: max - (a ?? b), more: true };
  return { years: Math.abs(a - b), more: false };
}

export function fiHeadline(d, lower = false) {
  const ladder = fiLadder(d, lower);
  if (!ladder) return null;
  const { levels, max } = ladder;
  const you = levels.find((l) => l.current) || levels[0];
  const paid = levels.filter((l) => l.deposit > 0);
  const [low, high] = [paid[0], paid[paid.length - 1]];
  const other = fiLadder(d, !lower)?.levels.find((l) => l.deposit === you.deposit);
  return {
    ladder,
    you,
    year: fiYear(d.as_of, you.p50),
    deposit: low && high && low !== high ? { low, high, moves: gap(low.p50, high.p50, max) } : null,
    mix: ladder.mixes > 1 ? { fastest: you.fastest, slowest: you.slowest, moves: gap(you.fastest.years, you.slowest.years, max) } : null,
    other: d.premium_cut_pts != null && other ? { years: other.p50 } : null,
    max,
  };
}

export function movesText(g) {
  if (!g) return '—';
  if (!g.more && g.years < 0.5) return 'Under a year';
  const n = yearsNum(g.years);
  return `${n}${g.more ? '+' : ''} ${n === 1 && !g.more ? 'year' : 'years'}`;
}

export function assumptions(d) {
  if (!d) return [];
  const out = [];
  if (d.start_value != null) out.push(`Starts at ${money(d.start_value)}`);
  if (d.monthly_deposit != null) out.push(`adds ${money(d.monthly_deposit)} a month${d.deposit_note ? ` (${d.deposit_note})` : ''}`);
  if (d.fi_number != null) out.push(`FI at ${money(d.fi_number)}${d.target_date ? ` by ${String(d.target_date).slice(0, 4)}` : ''}`);
  if (d.paths) out.push(`${d.paths.toLocaleString('en-US')} paths through market history${d.history?.start ? ` since ${d.history.start.slice(0, 4)}` : ''}`);
  if (d.premium_cut_pts != null) out.push('fund fees paid');
  if (d.real) out.push('in today’s dollars');
  return out;
}

export function rankDots(rank) {
  return [1, 2, 3, 4, 5].map((n) => ({ n, on: rank != null && n <= rank }));
}

import { dayLabel } from './charts.js';
import { plural, usd } from './format.js';
import { signedPct, signedPts } from './strategy.js';

const STATUS = {
  eligible: { t: 'Live-eligible', tone: 'ok' },
  paper: { t: 'On paper', tone: 'info' },
  retired: { t: 'Retired', tone: '' },
};

const WHY = {
  noise: 'the gap is inside the noise band',
  events: 'ahead, but too few buys to trust',
  bars: 'ahead, but the backtest bars were not all met',
  short_record: 'too few priced days to measure',
  behind: 'behind by more than noise',
  ahead: 'ahead by more than noise',
};

const GATE_DAYS = 182;

// ---------- rows ----------
export function boardRows(board) {
  const ranks = {};
  return (board?.rows || []).map((r) => {
    const bench = r.benchmark || board?.benchmark || 'IWM';
    const ranked = r.status !== 'retired' && !r.young && r.score != null;
    if (ranked) ranks[bench] = (ranks[bench] || 0) + 1;
    const goal = r.status === 'eligible' ? r.days_live || 1 : r.checkpoint_day || board?.gate_days || GATE_DAYS;
    return { ...r, benchmark: bench, rank: ranked ? ranks[bench] : null, share: Math.min(1, Math.max(0, (r.days_live || 0) / goal)) };
  });
}

export function boardGroups(board) {
  const rows = boardRows(board);
  const seen = [];
  rows.forEach((r) => {
    if (!seen.includes(r.benchmark)) seen.push(r.benchmark);
  });
  return seen.map((bench) => {
    const mine = rows.filter((r) => r.benchmark === bench);
    return { benchmark: bench, rows: mine, racing: mine.filter((r) => r.status !== 'retired').length };
  });
}

export function groupText(g) {
  const out = g.rows.length - g.racing;
  return `${plural(g.racing, 'racer')}${out ? `, ${out} retired` : ''}`;
}

export function boardStatus(s) {
  return STATUS[s] || { t: s || 'Unknown', tone: '' };
}

export function rankLabel(r) {
  if (r.rank != null) return `Rank ${r.rank} against ${r.benchmark}`;
  if (r.status === 'retired') return 'Retired';
  return r.young ? 'Too new to rank' : 'Not ranked yet';
}

export function trackText(r) {
  const v = r.gate?.verdict;
  const next = r.checkpoint_on ? dayLabel(r.checkpoint_on, true) : null;
  if (r.status === 'retired') return v?.verdict === 'retired' ? `Retired at the day ${v.checkpoint} check · ${WHY.behind}` : `Retired after ${r.days_live ?? '—'} days`;
  if (r.status === 'eligible') return `Day ${r.days_live ?? '—'} · passed the day ${v?.checkpoint ?? GATE_DAYS} check${next ? `, next check ${next}` : ''}`;
  if (v) return `Day ${r.days_live} · day ${v.checkpoint} check: ${whyText(v, r.gate)}${next ? ` · next check ${next}` : ''}`;
  const first = r.checkpoint_day || GATE_DAYS;
  return `Day ${r.days_live ?? 0} of ${first}${next ? ` · first check ${next}` : ''}`;
}

export function whyText(v, gate) {
  if (v?.reason === 'events' && v.events != null && gate?.min_events) return `ahead, but only ${v.events} of ${gate.min_events} buys`;
  return WHY[v?.reason] || 'no verdict yet';
}

export function edgeTone(v) {
  if (v == null) return '';
  return v >= 0 ? 'up' : 'dn';
}

export function luckText(r) {
  if (r.status === 'retired' || r.excess_pts == null || r.luck == null) return null;
  if (r.excess_pts <= 0) return 'No lead to test';
  const p = Math.round(r.luck * 100);
  return `${p < 1 ? 'Under 1' : p > 99 ? 'Over 99' : p}% chance it’s luck`;
}

export function statLine(r, bench = r.benchmark || 'IWM') {
  const parts = [];
  if (r.return_pct != null || r.bench_return_pct != null) parts.push(`${signedPct(r.return_pct)} vs ${bench} ${signedPct(r.bench_return_pct)}`);
  if (r.band_pts != null) parts.push(`noise band ±${r.band_pts.toFixed(1)} pts`);
  if (r.max_drawdown_pct != null) parts.push(`worst dip ${signedPct(r.max_drawdown_pct)}`);
  if (r.trades != null) parts.push(`${r.trades} ${r.trades === 1 ? 'fill' : 'fills'}`);
  return parts.join(' · ') || 'Numbers fill in once a few days of prices are in';
}

export function edgeText(r) {
  return r.excess_pts == null ? 'Too early' : signedPts(r.excess_pts);
}

export function boardHead(board) {
  const rows = boardRows(board);
  const racing = rows.filter((r) => r.status !== 'retired');
  const eligible = rows.filter((r) => r.status === 'eligible').length;
  const leader = rows.filter((r) => r.rank != null && r.excess_pts > 0).sort((a, b) => b.score - a.score)[0];
  return { racing: racing.length, eligible, leader, young: racing.filter((r) => r.young).length };
}

export function gateText(board) {
  return `Checked at day ${board?.gate_days || GATE_DAYS}, then every ${board?.step_days || 91} days`;
}

export function rewardLine(r) {
  const rr = r?.reward_risk;
  const bt = r?.backtest;
  const parts = [];
  if (rr?.sharpe != null) parts.push(`Reward to risk ${rr.sharpe.toFixed(2)} Sharpe${rr.sortino != null ? `, ${rr.sortino.toFixed(2)} Sortino` : ''}${rr.days ? ` over ${rr.days} days` : ''}`);
  if (bt?.sharpe != null) parts.push(`backtest ${bt.sharpe.toFixed(2)}${bt.ann_return_pct != null ? ` at ${signedPct(bt.ann_return_pct)} a year` : ''}`);
  return parts.join(' · ') || null;
}

export function accountText(r) {
  const a = r?.account;
  if (!a || a.value == null) return null;
  return `Paper account ${usd(a.value)}${a.sleeve != null ? ` of ${usd(a.sleeve)}` : ''}${a.return_pct != null ? ` (${signedPct(a.return_pct)})` : ''}${a.cash ? ` · ${usd(a.cash)} cash` : ''}`;
}

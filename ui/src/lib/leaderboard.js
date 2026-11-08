import { dayLabel } from './charts.js';
import { usd } from './format.js';
import { signedPct, signedPts } from './strategy.js';

const STATUS = {
  eligible: { t: 'Live-eligible', tone: 'ok' },
  paper: { t: 'On paper', tone: 'info' },
  retired: { t: 'Retired', tone: '' },
};

// ---------- rows ----------
export function boardRows(board) {
  const gate = board?.gate_days || 182;
  let rank = 0;
  return (board?.rows || []).map((r) => {
    const racing = r.status !== 'retired';
    if (racing) rank += 1;
    return { ...r, rank: racing ? rank : null, share: Math.min(1, Math.max(0, (r.days_live || 0) / gate)), gate };
  });
}

export function boardStatus(s) {
  return STATUS[s] || { t: s || 'Unknown', tone: '' };
}

export function trackText(r) {
  const gate = r.gate || 182;
  if (r.status === 'eligible') return `Day ${r.days_live ?? '—'} · cleared ${gate} days and ahead of the benchmark`;
  if (r.status === 'retired') return `Retired after ${r.days_live ?? '—'} days`;
  if (r.waiting_on === 'benchmark') return `Day ${r.days_live} · time’s served, needs to get ahead of the benchmark`;
  const when = r.eligible_on ? `, eligible ${dayLabel(r.eligible_on, true)}` : '';
  return `Day ${r.days_live ?? 0} of ${gate}${r.days_to_eligible != null ? ` · ${r.days_to_eligible} to go${when}` : when}`;
}

export function edgeTone(v) {
  if (v == null) return '';
  return v >= 0 ? 'up' : 'dn';
}

export function statLine(r, bench = 'IWM') {
  const parts = [];
  if (r.return_pct != null || r.bench_return_pct != null) parts.push(`${signedPct(r.return_pct)} vs ${bench} ${signedPct(r.bench_return_pct)}`);
  if (r.max_drawdown_pct != null) parts.push(`worst dip ${signedPct(r.max_drawdown_pct)}`);
  if (r.trades != null) parts.push(`${r.trades} ${r.trades === 1 ? 'fill' : 'fills'}`);
  return parts.join(' · ') || 'Numbers fill in once a few days of prices are in';
}

export function edgeText(r) {
  return r.excess_pts == null ? 'Too early' : signedPts(r.excess_pts);
}

export function boardHead(board) {
  const rows = boardRows(board);
  const racing = rows.filter((r) => r.rank != null);
  const eligible = rows.filter((r) => r.status === 'eligible').length;
  const leader = racing.find((r) => r.excess_pts != null);
  return { racing: racing.length, eligible, leader };
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

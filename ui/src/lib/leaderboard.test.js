import { describe, expect, it } from 'vitest';
import board from '../fixtures/engine.lab.leaderboard.json';
import early from '../fixtures/engine.lab.leaderboard.early.json';
import empty from '../fixtures/engine.lab.leaderboard.empty.json';
import { accountText, rewardLine, boardGroups, boardHead, boardRows, boardStatus, edgeText, edgeTone, gateText, groupText, luckText, rankLabel, statLine, trackText, whyText } from './leaderboard.js';

const byId = (id) => boardRows(board).find((r) => r.id === id);

describe('leaderboard', () => {
  it('groups racers under their own benchmark', () => {
    const groups = boardGroups(board);
    expect(groups.map((g) => g.benchmark)).toEqual(['IWM', 'Plan mix', 'IVV']);
    expect(groups.map((g) => g.benchmark)).toEqual(board.groups.map((g) => g.benchmark));
    expect(groups.map((g) => [g.rows.length, g.racing])).toEqual(board.groups.map((g) => [g.rows, g.racing]));
    expect(groupText(groups[0])).toBe('4 racers');
    expect(groupText(groups[1])).toBe('2 racers, 1 retired');
    expect(byId('tech-tilt').benchmark).toBe('IVV');
    expect(statLine(byId('tech-tilt'))).toMatch(/vs IVV/);
    expect(boardGroups(empty)).toEqual([]);
  });

  it('ranks inside each benchmark and leaves young and retired racers unranked', () => {
    expect(boardGroups(board).map((g) => g.rows.map((r) => r.rank))).toEqual([[1, 2, null, null], [1, 2, null], [null]]);
    expect(rankLabel(byId('insider-cluster-3'))).toBe('Rank 1 against IWM');
    expect(rankLabel(byId('filings-lane'))).toBe('Too new to rank');
    expect(rankLabel(byId('dip-buyer'))).toBe('Retired');
    expect(byId('filings-lane').young).toBe(true);
  });

  it('ranks on lead against noise, not on raw points', () => {
    const lucky = { id: 'lucky', benchmark: 'IWM', status: 'paper', young: false, days_live: 61, excess_pts: 9, score: 0.4 };
    const steady = { id: 'steady', benchmark: 'IWM', status: 'paper', young: false, days_live: 150, excess_pts: 3, score: 1.1 };
    const fresh = { id: 'fresh', benchmark: 'IWM', status: 'paper', young: true, days_live: 20, excess_pts: 12, score: 2.5 };
    const rows = boardRows({ rows: [steady, lucky, fresh] });
    expect(rows.map((r) => [r.id, r.rank])).toEqual([['steady', 1], ['lucky', 2], ['fresh', null]]);
    expect(boardHead({ rows: [steady, lucky, fresh] }).leader.id).toBe('steady');
  });

  it('says where each racer is against its next check', () => {
    expect(trackText(byId('filings-lane'))).toBe('Day 32 of 182 · first check Apr 5, 2027');
    expect(byId('filings-lane').share).toBeCloseTo(32 / 182, 3);
    expect(trackText(byId('low-vol-sectors'))).toBe('Day 200 · passed the day 182 check, next check Jan 18, 2027');
    expect(byId('low-vol-sectors').share).toBe(1);
    expect(trackText(byId('dip-buyer'))).toBe('Retired at the day 182 check · behind by more than noise');
    expect(trackText({ status: 'retired', days_live: 40, gate: null })).toBe('Retired after 40 days');
    const held = { status: 'paper', days_live: 200, checkpoint_day: 273, checkpoint_on: '2027-01-18', gate: { min_events: 30, verdict: { checkpoint: 182, verdict: 'unproven', reason: 'noise' } } };
    expect(trackText(held)).toBe('Day 200 · day 182 check: the gap is inside the noise band · next check Jan 18, 2027');
    expect(boardRows({ rows: [held] })[0].share).toBeCloseTo(200 / 273, 3);
    expect(whyText({ reason: 'events', events: 12 }, { min_events: 30 })).toBe('ahead, but only 12 of 30 buys');
    expect(whyText({ reason: 'bars' })).toBe('ahead, but the backtest bars were not all met');
    expect(trackText({ days_live: 4, status: 'paper' })).toBe('Day 4 of 182');
    expect(gateText(board)).toBe('Checked at day 182, then every 91 days');
  });

  it('reads the edge, the luck and the numbers plainly', () => {
    const calm = byId('low-vol-sectors');
    const momentum = byId('sector-momentum');
    expect(edgeText(calm)).toBe('+3.7 pts');
    expect(luckText(calm)).toBe('6% chance it’s luck');
    expect(luckText(momentum)).toBe('No lead to test');
    expect(luckText(byId('tech-tilt'))).toBeNull();
    expect(luckText(byId('dip-buyer'))).toBeNull();
    expect(luckText({ excess_pts: 30, luck: 0.001 })).toBe('Under 1% chance it’s luck');
    expect(edgeTone(momentum.excess_pts)).toBe('dn');
    expect(statLine(calm)).toBe('+6.8% vs Plan mix +3.1% · noise band ±3.1 pts · worst dip −4.2% · 38 fills');
    expect(boardStatus('eligible').t).toBe('Live-eligible');
  });

  it('copes with a racer too new for numbers', () => {
    const [r] = boardRows(early);
    expect(edgeText(r)).toBe('Too early');
    expect(edgeTone(r.excess_pts)).toBe('');
    expect(statLine(r)).toBe('1 fill');
    expect(luckText(r)).toBeNull();
    expect(boardHead(early).leader).toBeUndefined();
  });

  it('shows what the paper fills did as a second line', () => {
    expect(accountText(byId('low-vol-sectors'))).toBe('Paper account $1,061 of $1,000 (+6.1%) · $212 cash');
    expect(accountText(byId('filings-lane'))).toBe('Paper account $1,012 of $1,000 (+1.2%) · $906 cash');
    expect(accountText({ account: null })).toBeNull();
    expect(accountText({ account: { value: 1000, sleeve: 1000, cash: 0, return_pct: 0 } })).toBe('Paper account $1,000 of $1,000 (0.0%)');
  });

  it('names the firmest lead, not the biggest number', () => {
    expect(boardHead(board)).toMatchObject({ racing: 7, eligible: 1, young: 3, leader: { id: 'low-vol-sectors' } });
    expect(boardHead({ rows: [] })).toMatchObject({ racing: 0, eligible: 0 });
  });

  it('keeps every fixture row consistent with its gate', () => {
    boardRows(board).forEach((r) => {
      expect(r.young).toBe(r.days_live < board.young_days);
      expect(r.luck).toBe(r.gate.luck);
      if (r.status === 'eligible') expect(r.gate.verdict.verdict).toBe('eligible');
      if (r.gate.verdict?.verdict === 'eligible') expect(r.gate.verdict.excess_pts).toBeGreaterThanOrEqual(r.gate.verdict.band_pts);
      if (r.gate.verdict?.verdict === 'retired') expect(r.gate.verdict.excess_pts).toBeLessThanOrEqual(r.gate.verdict.retire_pts);
    });
  });
});

describe('reward to risk', () => {
  it('reads Sharpe and Sortino, then the backtest', () => {
    expect(rewardLine({ reward_risk: { sharpe: 1.12, sortino: 1.58, days: 200 }, backtest: { sharpe: 0.98, ann_return_pct: 9.4 } })).toBe('Reward to risk 1.12 Sharpe, 1.58 Sortino over 200 days · backtest 0.98 at +9.4% a year');
    expect(rewardLine({ reward_risk: { sharpe: null }, backtest: null })).toBeNull();
    expect(rewardLine({})).toBeNull();
  });
});

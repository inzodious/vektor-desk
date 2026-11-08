import { describe, expect, it } from 'vitest';
import board from '../fixtures/engine.lab.leaderboard.json';
import early from '../fixtures/engine.lab.leaderboard.early.json';
import { accountText, rewardLine, boardHead, boardRows, boardStatus, edgeText, edgeTone, statLine, trackText } from './leaderboard.js';

describe('leaderboard', () => {
  it('ranks racers and leaves retired ones unranked', () => {
    const rows = boardRows(board);
    expect(rows.map((r) => r.rank)).toEqual([1, 2, 3, 4, 5, null]);
    expect(rows[1].share).toBeCloseTo(32 / 182, 3);
    expect(rows[0].share).toBe(1);
  });

  it('says where each racer is on the track', () => {
    const rows = boardRows(board);
    const [eligible, lane] = rows;
    const retired = rows.at(-1);
    expect(trackText(eligible)).toBe('Day 200 · cleared 182 days and ahead of the benchmark');
    expect(trackText(lane)).toBe('Day 32 of 182 · 150 to go, eligible Apr 5, 2027');
    expect(trackText(retired)).toBe('Retired after 189 days');
    expect(trackText({ days_live: 190, waiting_on: 'benchmark', status: 'paper', gate: 182 })).toMatch(/needs to get ahead of the benchmark/);
  });

  it('reads the edge and the numbers plainly', () => {
    const [eligible] = boardRows(board);
    const momentum = boardRows(board).find((r) => r.id === 'sector-momentum');
    expect(edgeText(eligible)).toBe('+3.7 pts');
    expect(edgeTone(momentum.excess_pts)).toBe('dn');
    expect(statLine(eligible)).toBe('+6.8% vs IWM +3.1% · worst dip −4.2% · 18 fills');
    expect(boardStatus('eligible').t).toBe('Live-eligible');
  });

  it('copes with a racer too new for numbers', () => {
    const [r] = boardRows(early);
    expect(edgeText(r)).toBe('Too early');
    expect(edgeTone(r.excess_pts)).toBe('');
    expect(statLine(r)).toBe('1 fill');
    expect(boardHead(early).leader).toBeUndefined();
  });

  it('shows what the paper fills did as a second line', () => {
    const [eligible, lane] = boardRows(board);
    expect(accountText(eligible)).toBe('Paper account $1,061 of $1,000 (+6.1%) · $212 cash');
    expect(accountText(lane)).toBe('Paper account $1,012 of $1,000 (+1.2%) · $906 cash');
    expect(accountText({ account: null })).toBeNull();
    expect(accountText({ account: { value: 1000, sleeve: 1000, cash: 0, return_pct: 0 } })).toBe('Paper account $1,000 of $1,000 (0.0%)');
  });

  it('names the leader', () => {
    expect(boardHead(board)).toMatchObject({ racing: 5, eligible: 1, leader: { id: 'low-vol-sectors' } });
    expect(boardHead({ rows: [] })).toMatchObject({ racing: 0, eligible: 0 });
  });
});

describe('reward to risk', () => {
  it('reads Sharpe and Sortino, then the backtest', () => {
    expect(rewardLine({ reward_risk: { sharpe: 1.12, sortino: 1.58, days: 200 }, backtest: { sharpe: 0.98, ann_return_pct: 9.4 } })).toBe('Reward to risk 1.12 Sharpe, 1.58 Sortino over 200 days · backtest 0.98 at +9.4% a year');
    expect(rewardLine({ reward_risk: { sharpe: null }, backtest: null })).toBeNull();
    expect(rewardLine({})).toBeNull();
  });
});


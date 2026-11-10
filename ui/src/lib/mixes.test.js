import { describe, expect, it } from 'vitest';
import bands from '../fixtures/engine.bands.json';
import { assumptions, backtestLine, bandAt, caseOf, chanceText, feeText, fiHeadline, fiLadder, fiYear, fitBadge, ladderColumns, mixLine, mixesHead, money, movesText, rankDots, rewardText, yearsText } from './mixes.js';

describe('mixes', () => {
  it('writes money short', () => {
    expect(money(950)).toBe('$950');
    expect(money(1500)).toBe('$1.5K');
    expect(money(82177)).toBe('$82K');
    expect(money(1375000)).toBe('$1.38M');
    expect(money(12500000)).toBe('$12.5M');
    expect(money(null)).toBe('—');
  });

  it('describes a mix and its fit', () => {
    expect(mixLine({ weights: { BND: 0.05, IVV: 0.6, FTEC: 0.2, VXUS: 0.15 }, cash: 0.2 })).toBe('60% IVV · 20% FTEC · 15% VXUS · 5% BND · 20% cash');
    expect(mixLine({ weights: { IVV: 0.997, ACME: 0.003 }, cash: 0 })).toBe('100% IVV');
    expect(fitBadge('above')).toEqual({ t: 'Riskier than your band', tone: 'watch' });
    expect(fitBadge(null)).toBeNull();
    expect(rankDots(3).filter((d) => d.on)).toHaveLength(3);
    expect(bandAt(bands.rows[0], 10).years).toBe(10);
  });

  it('words chances, reward and backtests', () => {
    expect(chanceText(0.534)).toBe('53%');
    expect(chanceText(0.999)).toBe('Nearly certain');
    expect(chanceText(0.001)).toBe('Under 1%');
    expect(chanceText(null)).toBeNull();
    expect(rewardText({ sharpe: 0.62 })).toEqual({ v: '0.62', word: 'fair' });
    expect(rewardText({ backtest: { sharpe: 1.2 } }).word).toBe('strong');
    expect(backtestLine({ start: '2016-11', end: '2026-10', cagr_pct: 10.5, max_drawdown_pct: -32.3 })).toBe('Real prices, 2016-11 to 2026-10: +10.5% a year, worst dip −32.3%');
  });

  it('heads the page and lists the assumptions', () => {
    expect(mixesHead(bands)).toEqual({ total: 4, ready: 4, fitting: 2 });
    expect(assumptions(bands)[0]).toBe('Starts at $17K');
    expect(assumptions(bands).join(' · ')).toMatch(/FI at \$1M by 2035/);
    expect(assumptions(bands).at(-1)).toBe('fund fees paid');
  });

  it('switches a row to the lower-return case and words fees', () => {
    const safe = bands.rows.find((r) => r.id === 'safe-mix');
    expect(caseOf(safe, false)).toBe(safe);
    expect(caseOf(safe, true).p50_value_10y).toBe(safe.lower.p50_value_10y);
    expect(caseOf(safe, true).name).toBe('Safe mix');
    expect(caseOf({ id: 'x' }, true)).toEqual({ id: 'x' });
    expect(feeText(0.04)).toBe('Fees 0.04% a year');
    expect(feeText(0.0785)).toBe('Fees 0.08% a year');
    expect(feeText(0)).toBe('No fund fees');
    expect(feeText(null)).toBeNull();
  });

  it('words years and the calendar year they land in', () => {
    expect(yearsText(32.33)).toBe('32 years');
    expect(yearsText(6.67)).toBe('6.7 years');
    expect(yearsText(1)).toBe('1 year');
    expect(yearsText(null)).toBe('40+ years');
    expect(fiYear('2026-11-06', 32.33)).toBe(2059);
    expect(fiYear('2026-11-06', null)).toBeNull();
    expect(movesText({ years: 27.6, more: false })).toBe('28 years');
    expect(movesText({ years: 33.3, more: true })).toBe('33+ years');
    expect(movesText({ years: 0.2, more: false })).toBe('Under a year');
    expect(movesText(null)).toBe('—');
  });

  it('lays the deposit ladder out against every mix', () => {
    const ladder = fiLadder(bands);
    expect(ladder.ref).toEqual({ id: 'safe-mix', name: 'Safe mix' });
    expect(ladder.levels.map((l) => l.deposit)).toEqual(bands.deposit_ladder);
    const you = ladder.levels.find((l) => l.current);
    expect(you).toMatchObject({ deposit: 600, p50: 32.33, fastest: { id: 'tech-tilt' }, slowest: { id: 'dip-buy' } });
    expect(ladder.levels.map((l) => l.p50)).toEqual([...ladder.levels.map((l) => l.p50)].sort((a, b) => b - a));
    expect(fiLadder(bands, true).levels.find((l) => l.current).slowest).toMatchObject({ id: 'as-held', years: null });
    expect(fiLadder({ rows: [] })).toBeNull();
    expect(fiLadder({ rows: [{ status: 'ok', fi_time: null }] })).toBeNull();
  });

  it('thins the ladder to the room it has and keeps your column', () => {
    const { levels } = fiLadder(bands);
    expect(ladderColumns(levels, 12)).toHaveLength(11);
    expect(ladderColumns(levels, 5).map((l) => l.deposit)).toEqual([500, 600, 2000, 5000, 10000]);
    const near = [...levels.map((l) => ({ ...l, current: false })), { deposit: 1974, current: true }].sort((x, y) => x.deposit - y.deposit);
    expect(ladderColumns(near, 12).map((l) => l.deposit)).toEqual([500, 600, 1000, 1500, 1974, 3000, 4000, 5000, 6000, 8000, 10000]);
  });

  it('says what moves the FI date', () => {
    const head = fiHeadline(bands);
    expect(head.you.deposit).toBe(600);
    expect(head.year).toBe(2059);
    expect(movesText(head.deposit.moves)).toBe('28 years');
    expect(movesText(head.mix.moves)).toBe('2.5 years');
    expect(head.other.years).toBe(39.17);
    const low = fiHeadline(bands, true);
    expect(low.other.years).toBe(32.33);
    expect(movesText(low.deposit.moves)).toBe('33+ years');
    expect(movesText(low.mix.moves)).toBe('1.8+ years');
    expect(fiHeadline({ rows: [] })).toBeNull();
    const far = { ...bands, rows: bands.rows.map((r) => ({ ...r, fi_time: r.fi_time.map((x) => ({ ...x, years_p50: null })) })) };
    expect(fiHeadline(far)).toMatchObject({ year: null, mix: { moves: null }, deposit: { moves: null } });
  });
});

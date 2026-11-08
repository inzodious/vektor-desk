import { describe, expect, it } from 'vitest';
import bands from '../fixtures/engine.bands.json';
import { assumptions, backtestLine, bandAt, chanceText, fitBadge, mixLine, mixesHead, money, rankDots, rewardText } from './mixes.js';

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
    expect(mixesHead(bands)).toMatchObject({ total: 4, ready: 4, fitting: 2, best: { id: 'tech-tilt' } });
    expect(assumptions(bands)[0]).toBe('Starts at $17K');
    expect(assumptions(bands).join(' · ')).toMatch(/FI at \$1M by 2035/);
  });
});

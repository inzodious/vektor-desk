import { describe, expect, it } from 'vitest';
import { addBoard, alignSeries, chunkIds, drawdown, idLabel, isSymbol, monthGrid, monthlyReturns, pairMatrix, parseIds, readBoards, removeBoard, scenarioItems, seriesRows } from './lab.js';

function memStore() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
}

describe('ids', () => {
  it('labels specials, accounts and symbols', () => {
    expect(idLabel('portfolio')).toBe('Your portfolio');
    expect(idLabel('shadow:plan_shadow')).toBe('Safe mix shadow');
    expect(idLabel('account:hsa-1')).toBe('HSA');
    expect(idLabel('FTEC')).toBe('FTEC');
  });

  it('tells symbols apart from specials', () => {
    expect(isSymbol('FTEC')).toBe(true);
    expect(isSymbol('portfolio')).toBe(false);
    expect(isSymbol('shadow:plan_shadow')).toBe(false);
    expect(isSymbol('')).toBe(false);
  });

  it('parses, uppercases, dedupes and caps at five', () => {
    expect(parseIds(' ftec, portfolio,FTEC,shadow:plan_shadow ')).toEqual(['FTEC', 'portfolio', 'shadow:plan_shadow']);
    expect(parseIds('a,b,c,d,e,f')).toHaveLength(5);
    expect(parseIds(null)).toEqual([]);
  });

  it('chunks without leaving a lone id', () => {
    expect(chunkIds(['a'])).toEqual([]);
    expect(chunkIds(['a', 'b', 'c'])).toEqual([['a', 'b', 'c']]);
    expect(chunkIds(['a', 'b', 'c', 'd', 'e', 'f'])).toEqual([
      ['a', 'b', 'c', 'd'],
      ['e', 'f'],
    ]);
    expect(chunkIds(['a', 'b', 'c', 'd', 'e', 'f', 'g'])).toEqual([
      ['a', 'b', 'c', 'd', 'e'],
      ['f', 'g'],
    ]);
  });
});

describe('series', () => {
  it('unions dates and fills gaps with null', () => {
    const out = seriesRows({
      ids: ['A', 'B'],
      series: {
        A: [
          { date: '2026-01-02', value: 100 },
          { date: '2026-01-03', value: 101 },
        ],
        B: [{ date: '2026-01-03', value: 100 }],
      },
    });
    expect(out.x).toEqual(['2026-01-02', '2026-01-03']);
    expect(out.values).toEqual([
      [100, 101],
      [null, 100],
    ]);
  });

  it('measures drawdown from the running high', () => {
    expect(drawdown([100, 110, 99, null, 121]).map((v) => (v == null ? v : Math.round(v * 10) / 10))).toEqual([0, 0, -10, null, 0]);
  });

  it('aligns two series on shared dates', () => {
    const a = [
      { date: 'd1', value: 1 },
      { date: 'd2', value: 2 },
    ];
    const b = [
      { date: 'd2', value: 20 },
      { date: 'd3', value: 30 },
    ];
    expect(alignSeries(a, b)).toEqual({ x: ['d2'], a: [2], b: [20] });
    expect(alignSeries(null, null)).toEqual({ x: [], a: [], b: [] });
  });

  it('turns closes into monthly returns and a grid', () => {
    const rows = [
      { date: '2026-01-30', close: 100 },
      { date: '2026-02-27', close: 110 },
      { date: '2026-03-31', close: 99 },
    ];
    const m = monthlyReturns(rows);
    expect(m.map((r) => r.month)).toEqual(['2026-02', '2026-03']);
    expect(m[0].ret).toBeCloseTo(0.1);
    const g = monthGrid({ A: rows, B: rows.slice(1) });
    expect(g.cols).toEqual(['2026-02', '2026-03']);
    expect(g.labels).toEqual(['Feb', 'Mar']);
    expect(g.values[1][0]).toBeNull();
    expect(g.values[1][1]).toBeCloseTo(-0.1);
  });
});

describe('metrics', () => {
  it('builds a symmetric correlation matrix', () => {
    const out = pairMatrix([
      { metric_id: 'risk.corr', scope: 'pair', scope_id: 'A|B', value: 0.5 },
      { metric_id: 'risk.corr', scope: 'pair', scope_id: 'B|C', value: -0.2 },
      { metric_id: 'risk.vol', scope: 'portfolio', scope_id: 'all', value: 12 },
    ]);
    expect(out.syms).toEqual(['A', 'B', 'C']);
    expect(out.values[0]).toEqual([null, 0.5, null]);
    expect(out.values[2][1]).toBe(-0.2);
  });

  it('marks replays without history and keeps modelled shocks', () => {
    const items = scenarioItems([
      { metric_id: 'risk.scenario', scope_id: 'gfc_2008', value: null, quality: 'insufficient_history' },
      { metric_id: 'risk.scenario', scope_id: 'market_-20', value: -1959, quality: 'modelled' },
      { metric_id: 'risk.scenario_pct', scope_id: 'market_-20', value: -17.4 },
    ]);
    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({ label: '2008 replay', value: null, note: 'Needs older prices' });
    expect(items[1]).toMatchObject({ value: -1959, pct: -17.4, hint: 'modelled' });
  });
});

describe('saved boards', () => {
  it('adds newest first, replaces the same path and removes', () => {
    const store = memStore();
    addBoard({ name: 'One', path: '/research/compare?ids=A,B' }, store, new Date('2026-11-07T10:00:00Z'));
    addBoard({ name: 'Two', path: '/portfolio/risk' }, store, new Date('2026-11-07T11:00:00Z'));
    const list = addBoard({ name: 'One again', path: '/research/compare?ids=A,B' }, store, new Date('2026-11-07T12:00:00Z'));
    expect(list.map((b) => b.name)).toEqual(['One again', 'Two']);
    expect(removeBoard(list[1].id, store).map((b) => b.name)).toEqual(['One again']);
  });

  it('ignores junk and paths that are not a board view', () => {
    const store = memStore();
    store.setItem('desk.boards.v1', JSON.stringify([{ path: '/settings' }, null, { name: 'ok', path: '/portfolio/risk' }]));
    expect(readBoards(store)).toEqual([{ name: 'ok', path: '/portfolio/risk' }]);
    store.setItem('desk.boards.v1', '{bad');
    expect(readBoards(store)).toEqual([]);
  });

  it('moves boards saved under the old Lab menu to their new pages', () => {
    const store = memStore();
    store.setItem(
      'desk.boards.v1',
      JSON.stringify([
        { name: 'a', path: '/lab' },
        { name: 'b', path: '/lab?ids=A,B&w=3Y' },
        { name: 'c', path: '/lab/risk' },
        { name: 'd', path: '/lab/patterns' },
        { name: 'e', path: '/lab/patterns/replay?rule=stop-20' },
      ]),
    );
    expect(readBoards(store).map((b) => b.path)).toEqual(['/research/compare', '/research/compare?ids=A,B&w=3Y', '/portfolio/risk', '/strategies/habits', '/strategies/habits/replay?rule=stop-20']);
  });

  it('reports a store that refuses writes', () => {
    const store = {
      getItem: () => null,
      setItem: () => {
        throw new Error('full');
      },
    };
    expect(addBoard({ name: 'x', path: '/research/compare' }, store)).toBeNull();
  });
});

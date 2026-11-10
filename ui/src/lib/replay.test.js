import { describe, expect, it } from 'vitest';
import view from '../fixtures/engine.replay.json';
import fresh from '../fixtures/engine.replay.fresh.json';
import { actionLine, chartSeries, eventRows, familyOptions, firstOf, groups, headline, helpRead, levelOf, levelOptions, pickRule, shortLabel, signed, sizingTiles, spanLabel, split, splitRead, symbolBars, taxRead, yearTicks } from './replay.js';

const byId = (id) => view.variants.find((v) => v.id === id);

describe('replay', () => {
  it('names rules short and reads their level', () => {
    expect(shortLabel(byId('house'))).toBe('The capped you');
    expect(shortLabel(byId('buy-cap-10'))).toBe('Buy cap 10%');
    expect(shortLabel(byId('position-cap-15'))).toBe('Name cap 15%');
    expect(shortLabel(byId('stop-20'))).toBe('Stop at 20% down');
    expect(shortLabel(byId('trend-200'))).toBe('200-day trend');
    expect(shortLabel(byId('long-term'))).toBe('Year and a day');
    expect(levelOf(byId('stop-25'))).toBe(25);
    expect(levelOf(byId('no-margin'))).toBeNull();
    expect(shortLabel(null)).toBe('');
  });

  it('offers families, then levels inside one', () => {
    expect(familyOptions(view).map((o) => o.v)).toEqual(['house', 'buy_cap', 'position_cap', 'stop', 'trend', 'no_margin', 'long_term']);
    expect(levelOptions(view, 'stop')).toEqual([
      { v: 'stop-15', t: '15%' },
      { v: 'stop-20', t: '20%' },
      { v: 'stop-25', t: '25%' },
      { v: 'stop-30', t: '30%' },
    ]);
    expect(levelOptions(view, 'house')).toEqual([]);
    expect(firstOf(view, 'buy_cap').id).toBe('buy-cap-10');
    expect(firstOf(view, 'stop').id).toBe('stop-20');
    expect(firstOf(view, 'trend').id).toBe('trend-200');
    expect(familyOptions(fresh)).toEqual([]);
  });

  it('falls back to the headline rule', () => {
    expect(pickRule(view, 'stop-15').id).toBe('stop-15');
    expect(pickRule(view, 'nope').id).toBe('house');
    expect(pickRule(view, null).id).toBe('house');
    expect(pickRule(fresh, 'house')).toBeNull();
  });

  it('writes the headline both ways', () => {
    expect(headline(view)).toEqual({ value: '+$2,424', tone: 'up', line: 'the capped you finishes ahead of you' });
    const behind = { headline: 'house', variants: [{ id: 'house', change_usd: -300 }] };
    expect(headline(behind)).toEqual({ value: '−$300', tone: 'dn', line: 'you finish ahead of the capped you' });
    expect(headline(fresh)).toBeNull();
    expect(signed(null)).toBe('—');
  });

  it('splits picks from size for the cap rules only', () => {
    const s = split(view, byId('house'));
    expect(Math.round(s.picks)).toBe(11205);
    expect(Math.round(s.size)).toBe(-2424);
    expect(splitRead(s)).toBe('Your picks beat the S&P 500 by $11,205 at the capped size. Going bigger cost $2,424.');
    expect(splitRead({ picks: -500, size: 900 })).toBe('Your picks trailed the S&P 500 by $500 at the capped size. Going bigger added $900.');
    expect(split(view, byId('stop-20'))).toBeNull();
    expect(splitRead(null)).toBeNull();
  });

  it('builds three lines on the shared dates', () => {
    const series = chartSeries(view, byId('house'));
    expect(series.map((s) => s.name)).toEqual(['You', 'The capped you', 'S&P 500']);
    expect(series.every((s) => s.values.length === view.dates.length)).toBe(true);
    expect(series[2].dash).toBe(true);
    expect(chartSeries(view, byId('stop-20'))[1].short).toBe('With the rule');
    expect(chartSeries(fresh, null)).toEqual([]);
  });

  it('labels the first tick by month and the rest by year', () => {
    expect(yearTicks(view.dates).map((t) => t.label)).toEqual(['Aug', '2024', '2025', '2026']);
    expect(yearTicks(['2025-12-19', '2025-12-26', '2026-01-02', '2026-01-09']).map((t) => t.label)).toEqual(['2026']);
  });

  it('reads where a rule helped and hurt', () => {
    const house = byId('house');
    expect(symbolBars(house)[0]).toEqual({ label: 'ORBT', value: 26128.88 });
    expect(helpRead(house)).toBe('It helped most on ORBT (+$26,129) and cost most on HELX (−$10,486).');
    expect(helpRead({ actions: 0 })).toBe('This rule never had to step in.');
    expect(helpRead({ actions: 2, by_symbol: [] })).toBe('It moved money without changing the result.');
    expect(actionLine(house)).toBe('Stepped in 28 times · $110,983 moved');
    expect(actionLine({ actions: 0 })).toBe('Never stepped in');
  });

  it('words what the rule did, largest first', () => {
    const rows = eventRows(byId('house'));
    expect(rows).toHaveLength(6);
    expect(rows[0]).toMatchObject({ date: 'May 26, 2026', symbol: 'ORBT', what: 'Cut to the cap', usd: '$18,157', to: 'to the index' });
    expect(eventRows(byId('stop-20'))[0]).toMatchObject({ date: 'Jun 29, 2026', what: 'Stopped out' });
    expect(eventRows(byId('long-term'))[0]).toMatchObject({ what: 'Sale held back', to: 'kept in the stock' });
    expect(eventRows(byId('no-margin'))[0]).toMatchObject({ what: 'Not borrowed', to: 'left unbought' });
    expect(eventRows(null)).toEqual([]);
  });

  it('shows tax only for the holding rule', () => {
    expect(taxRead(view, byId('long-term'))).toEqual({ value: '$46', line: 'less tax on realized gains', tone: 'up', rates: '28% short-term, 19% long-term' });
    expect(taxRead(view, byId('house'))).toBeNull();
    expect(taxRead({ tax_rates: null }, byId('long-term'))).toBeNull();
    expect(taxRead(view, { family: 'long_term', tax_change_usd: 120 }).line).toBe('more tax, on larger gains');
  });

  it('groups every rule and reads each group honestly', () => {
    const g = groups(view);
    expect(g.map((x) => x.key)).toEqual(['size', 'exits', 'habits']);
    expect(g[0].items).toHaveLength(8);
    expect(g[0].read).toBe('Mixed: Buy cap 10% helps, Name cap 5% costs.');
    expect(g[1].read).toBe('Every version finishes ahead. Best: Stop at 20% down.');
    expect(g[1].items[0]).toMatchObject({ label: 'Stop at 15% down', id: 'stop-15' });
    const losing = groups({ variants: [{ id: 'stop-15', family: 'stop', params: { stop: 0.15 }, change_usd: -40, actions: 1, moved_usd: 10 }] });
    expect(losing).toHaveLength(1);
    expect(losing[0].read).toBe('No version finishes ahead of what you did.');
    expect(groups(fresh)).toEqual([]);
  });

  it('turns sizing into six tiles', () => {
    const tiles = sizingTiles(view);
    expect(tiles.map((t) => t.k)).toEqual(['Single-name buys', 'Typical buy', 'Over 10%', 'Largest buy', 'Days on margin', 'Margin interest']);
    expect(tiles[0]).toEqual({ k: 'Single-name buys', v: '32', line: '2 partly on margin' });
    expect(tiles[1].v).toBe('9.8%');
    expect(tiles[2]).toMatchObject({ v: '16', line: 'of 32 buys', tone: 'dn' });
    expect(tiles[3]).toMatchObject({ v: '39%', line: 'ACME, Aug 3, 2023' });
    expect(tiles[4]).toMatchObject({ v: '43', line: 'peak $7,769' });
    expect(tiles[5].v).toBe('$126');
    expect(sizingTiles(fresh)).toEqual([]);
    expect(spanLabel(view)).toBe('Aug 2, 2023 to Nov 9, 2026');
    expect(spanLabel(fresh)).toBeNull();
  });
});

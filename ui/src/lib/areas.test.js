import { describe, expect, it } from 'vitest';
import { AREAS, PORTFOLIO_TABS, SETTINGS_TABS, STRATEGY_TABS, movedPath, settingsTabFor } from './areas.js';
import { titleFor } from './useTitle.js';

describe('menu', () => {
  it('lists the six areas in order, with Settings off the menu', () => {
    expect(AREAS.map((a) => a.title)).toEqual(['Bridge', 'Results', 'Portfolio', 'Strategies', 'Decisions', 'Research']);
    expect(AREAS.some((a) => a.key === 'settings')).toBe(false);
  });

  it('groups the subtabs the way the menu reads', () => {
    expect(PORTFOLIO_TABS.map((t) => t.label)).toEqual(['Holdings', 'Stock plans', 'Risk', 'Tax']);
    expect(STRATEGY_TABS.map((t) => t.label)).toEqual(['Race', 'Mixes', 'My habits']);
    expect(SETTINGS_TABS.map((t) => t.label)).toEqual(['Desk', 'Crew', 'Data', 'Box', 'Risk check', 'First run']);
  });
});

describe('movedPath', () => {
  it('sends old Plan links to Portfolio', () => {
    expect(movedPath('/plan')).toBe('/portfolio');
    expect(movedPath('/plan/stocks')).toBe('/portfolio/stocks');
  });

  it('sends old Lab links to their new areas', () => {
    expect(movedPath('/lab')).toBe('/strategies');
    expect(movedPath('/lab', '?ids=FXAIX,FTEC')).toBe('/research/compare');
    expect(movedPath('/lab', '?w=3Y')).toBe('/research/compare');
    expect(movedPath('/lab', '', { board: true })).toBe('/research/compare');
    expect(movedPath('/lab/risk')).toBe('/portfolio/risk');
    expect(movedPath('/lab/mixes')).toBe('/strategies/mixes');
    expect(movedPath('/lab/strategies')).toBe('/strategies');
    expect(movedPath('/lab/strategies/sector-momentum')).toBe('/strategies/sector-momentum');
    expect(movedPath('/lab/patterns')).toBe('/strategies/habits');
    expect(movedPath('/lab/patterns/replay')).toBe('/strategies/habits/replay');
    expect(movedPath('/lab/boards')).toBe('/research/boards');
  });

  it('leaves current pages alone', () => {
    expect(movedPath('/')).toBeNull();
    expect(movedPath('/portfolio')).toBeNull();
    expect(movedPath('/planet')).toBeNull();
    expect(movedPath('/lab/nowhere')).toBeNull();
  });
});

describe('settingsTabFor', () => {
  it('finds the tab a section moved to', () => {
    expect(settingsTabFor('#jobs')).toBe('/settings/box');
    expect(settingsTabFor('#inbox')).toBe('/settings/data');
    expect(settingsTabFor('#keys')).toBe('/settings/data');
    expect(settingsTabFor('')).toBeNull();
    expect(settingsTabFor('#profile')).toBeNull();
  });
});

describe('titleFor', () => {
  it('names the area in the tab title', () => {
    expect(titleFor('/')).toBe('Bridge · Vektor Desk');
    expect(titleFor('/results/week')).toBe('Results · Vektor Desk');
    expect(titleFor('/portfolio/tax')).toBe('Portfolio · Vektor Desk');
    expect(titleFor('/strategies/habits/replay')).toBe('Strategies · Vektor Desk');
    expect(titleFor('/research/compare')).toBe('Research · Vektor Desk');
    expect(titleFor('/settings/box')).toBe('Settings · Vektor Desk');
    expect(titleFor('/nowhere')).toBe('Vektor Desk');
  });
});

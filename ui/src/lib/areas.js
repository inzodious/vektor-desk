export const AREAS = [
  { key: 'bridge', title: 'Bridge', short: 'Bridge', path: '/', art: 'bridge' },
  { key: 'results', title: 'Results', short: 'Results', path: '/results', art: 'bridge' },
  { key: 'portfolio', title: 'Portfolio', short: 'Portfolio', path: '/portfolio', art: 'plan' },
  { key: 'strategies', title: 'Strategies', short: 'Strategies', path: '/strategies', art: 'lab' },
  { key: 'decisions', title: 'Decisions', short: 'Decide', path: '/decisions', art: 'decisions' },
  { key: 'research', title: 'Research', short: 'Research', path: '/research', art: 'research' },
];

export const SETTINGS = { key: 'settings', title: 'Settings', short: 'Settings', path: '/settings', art: 'settings' };

export const areaByKey = Object.fromEntries([...AREAS, SETTINGS].map((a) => [a.key, a]));

// ---------- subtabs ----------
export const PORTFOLIO_TABS = [
  { to: '/portfolio', label: 'Holdings', end: true },
  { to: '/portfolio/stocks', label: 'Stock plans' },
  { to: '/portfolio/risk', label: 'Risk' },
  { to: '/portfolio/tax', label: 'Tax' },
];

export const STRATEGY_TABS = [
  { to: '/strategies', label: 'Race', end: true },
  { to: '/strategies/mixes', label: 'Mixes' },
  { to: '/strategies/habits', label: 'My habits' },
];

export const SETTINGS_TABS = [
  { to: '/settings', label: 'Desk', end: true },
  { to: '/settings/crew', label: 'Crew' },
  { to: '/settings/data', label: 'Data' },
  { to: '/settings/box', label: 'Box' },
  { to: '/settings/risk', label: 'Risk check' },
  { to: '/settings/first-run', label: 'First run' },
];

// ---------- moved pages ----------
const MOVED = [
  ['/plan/stocks', '/portfolio/stocks'],
  ['/plan', '/portfolio'],
  ['/lab/risk', '/portfolio/risk'],
  ['/lab/mixes', '/strategies/mixes'],
  ['/lab/strategies', '/strategies'],
  ['/lab/patterns/replay', '/strategies/habits/replay'],
  ['/lab/patterns', '/strategies/habits'],
  ['/lab/boards', '/research/boards'],
];

const SETTINGS_HASH = { '#jobs': '/settings/box', '#box': '/settings/box', '#token': '/settings/box', '#inbox': '/settings/data', '#keys': '/settings/data', '#crew': '/settings/crew' };

export function movedPath(pathname, search = '', { board = false } = {}) {
  if (pathname === '/lab' || pathname === '/lab/') return board || /[?&](ids|w)=/.test(search) ? '/research/compare' : '/strategies';
  for (const [from, to] of MOVED) {
    if (pathname === from || pathname.startsWith(`${from}/`)) return `${to}${pathname.slice(from.length)}`;
  }
  return null;
}

export function settingsTabFor(hash) {
  return SETTINGS_HASH[hash] || null;
}

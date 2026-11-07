export const AREAS = [
  { key: 'bridge', title: 'Bridge', short: 'Bridge', path: '/', art: 'bridge', kicker: 'Bridge · the whole desk at a glance', phase: '2 and 3', lands: 'The departures board, KPI row, drift bullets and gauges land here.' },
  { key: 'research', title: 'Research', short: 'Research', path: '/research', art: 'research', kicker: 'Research · dossiers and sources', phase: '6', lands: 'Dossiers, sources, the watchlist and the Console land here.' },
  { key: 'decisions', title: 'Decisions', short: 'Decide', path: '/decisions', art: 'decisions', kicker: 'Decisions · queue and journal', phase: '4', lands: 'The queue, Preflight lights, order ticket and Journal land here.' },
  { key: 'plan', title: 'Plan', short: 'Plan', path: '/plan', art: 'plan', kicker: 'Plan · mix, drift and the road to FI', phase: '3', lands: 'Mix and drift lands first, the tax calendar in phase 5 and the FI path in phase 11.' },
  { key: 'lab', title: 'Lab', short: 'Lab', path: '/lab', art: 'lab', kicker: 'Lab · compare, risk and patterns', phase: '7', lands: 'Compare, Risk and Saved boards land first, then the Strategy lab and Patterns.' },
  { key: 'settings', title: 'Settings', short: 'Settings', path: '/settings', art: 'settings', kicker: 'Settings', phase: '1' },
];

export const areaByKey = Object.fromEntries(AREAS.map((a) => [a.key, a]));

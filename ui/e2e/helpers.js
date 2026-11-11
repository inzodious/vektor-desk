export const ROUTES = [
  { path: '/', h1: 'Bridge' },
  { path: '/?scenario=fail', h1: 'Bridge' },
  { path: '/?scenario=long', h1: 'Bridge' },
  { path: '/portfolio?scenario=warn', h1: 'Holdings' },
  { path: '/research', h1: 'Research' },
  { path: '/research?s=ACME', h1: 'Research' },
  { path: '/research/sources', h1: 'Research' },
  { path: '/research/watchlist', h1: 'Research' },
  { path: '/research/calendar', h1: 'Research' },
  { path: '/?open=console', h1: 'Bridge' },
  { path: '/decisions', h1: 'Decisions' },
  { path: '/decisions/journal', h1: 'Journal' },
  { path: '/decisions/flight', h1: 'Flight record' },
  { path: '/portfolio', h1: 'Holdings' },
  { path: '/portfolio/tax', h1: 'Tax' },
  { path: '/plan', h1: 'Holdings' },
  { path: '/lab', h1: 'Race' },
  { path: '/lab/risk', h1: 'Risk' },
  { path: '/lab/patterns/replay?rule=stop-20', h1: 'Replay' },
  { path: '/research/compare', h1: 'Compare' },
  { path: '/research/compare?ids=FXAIX,FTEC,VXUS', h1: 'Compare' },
  { path: '/portfolio/risk', h1: 'Risk' },
  { path: '/portfolio/risk?scenario=empty', h1: 'Risk' },
  { path: '/portfolio?scenario=empty', h1: 'Holdings' },
  { path: '/strategies', h1: 'Race' },
  { path: '/strategies/sector-momentum', h1: 'Sector momentum' },
  { path: '/strategies/dip-margin', h1: 'Margin in a dip' },
  { path: '/strategies/habits', h1: 'My habits' },
  { path: '/strategies/habits/replay', h1: 'Replay' },
  { path: '/strategies/habits/replay?rule=long-term', h1: 'Replay' },
  { path: '/research/boards', h1: 'Saved boards' },
  { path: '/settings', h1: 'Settings' },
  { path: '/settings/crew', h1: 'Settings' },
  { path: '/settings/data', h1: 'Settings' },
  { path: '/settings/box', h1: 'Settings' },
  { path: '/settings/first-run', h1: 'First run' },
  { path: '/settings/risk', h1: 'Risk check' },
  { path: '/strategies/mixes', h1: 'Mixes' },
  { path: '/portfolio/stocks', h1: 'Stock plans' },
  { path: '/portfolio/stocks?scenario=fresh', h1: 'Stock plans' },
  { path: '/results/day', h1: 'Results' },
  { path: '/results/week', h1: 'Results' },
  { path: '/results/year', h1: 'Results' },
  { path: '/results/day?scenario=fresh', h1: 'Results' },
  { path: '/?scenario=fresh', h1: 'Bridge' },
  { path: '/research?scenario=fresh', h1: 'Research' },
  { path: '/decisions?scenario=fresh', h1: 'Decisions' },
  { path: '/decisions/journal?scenario=fresh', h1: 'Journal' },
  { path: '/decisions/flight?scenario=fresh', h1: 'Flight record' },
  { path: '/portfolio?scenario=fresh', h1: 'Holdings' },
  { path: '/portfolio/risk?scenario=fresh', h1: 'Risk' },
  { path: '/strategies?scenario=fresh', h1: 'Race' },
  { path: '/strategies/habits/replay?scenario=fresh', h1: 'Replay' },
  { path: '/settings?scenario=fresh', h1: 'Settings' },
  { path: '/nowhere', h1: 'Lost in orbit' },
];

export const MONDAY_MIDDAY = new Date('2026-11-09T16:42:00Z');

export function watchErrors(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  return errors;
}

export async function overflow(page) {
  return page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, view: window.innerWidth }));
}

export function record(over = {}) {
  return { id: 'd_test', title: 'Test', status: 'approved', kind: 'buy', ...over };
}

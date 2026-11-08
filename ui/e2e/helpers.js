export const ROUTES = [
  { path: '/', h1: 'Bridge' },
  { path: '/?scenario=fail', h1: 'Bridge' },
  { path: '/?scenario=long', h1: 'Bridge' },
  { path: '/plan?scenario=warn', h1: 'Plan' },
  { path: '/research', h1: 'Research' },
  { path: '/research?s=ACME', h1: 'Research' },
  { path: '/research/sources', h1: 'Research' },
  { path: '/research/watchlist', h1: 'Research' },
  { path: '/research/calendar', h1: 'Research' },
  { path: '/?open=console', h1: 'Bridge' },
  { path: '/decisions', h1: 'Decisions' },
  { path: '/decisions/journal', h1: 'Journal' },
  { path: '/decisions/flight', h1: 'Flight record' },
  { path: '/plan', h1: 'Plan' },
  { path: '/lab', h1: 'Compare' },
  { path: '/lab?ids=FXAIX,FTEC,VXUS', h1: 'Compare' },
  { path: '/lab/risk', h1: 'Risk' },
  { path: '/lab/risk?scenario=empty', h1: 'Risk' },
  { path: '/plan?scenario=empty', h1: 'Plan' },
  { path: '/lab/strategies', h1: 'Strategy lab' },
  { path: '/lab/strategies/sector-momentum', h1: 'Sector momentum' },
  { path: '/lab/strategies/dip-margin', h1: 'Margin in a dip' },
  { path: '/lab/patterns', h1: 'Patterns' },
  { path: '/lab/boards', h1: 'Saved boards' },
  { path: '/settings', h1: 'Settings' },
  { path: '/settings/first-run', h1: 'First run' },
  { path: '/settings/risk', h1: 'Risk check' },
  { path: '/?scenario=fresh', h1: 'Bridge' },
  { path: '/research?scenario=fresh', h1: 'Research' },
  { path: '/decisions?scenario=fresh', h1: 'Decisions' },
  { path: '/decisions/journal?scenario=fresh', h1: 'Journal' },
  { path: '/decisions/flight?scenario=fresh', h1: 'Flight record' },
  { path: '/plan?scenario=fresh', h1: 'Plan' },
  { path: '/lab/risk?scenario=fresh', h1: 'Risk' },
  { path: '/lab/strategies?scenario=fresh', h1: 'Strategy lab' },
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

export const ROUTES = [
  { path: '/', h1: 'Bridge' },
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
  { path: '/lab', h1: 'Lab' },
  { path: '/settings', h1: 'Settings' },
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

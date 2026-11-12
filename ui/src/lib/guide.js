// ---------- what each page is, and where to go next ----------
const GUIDES = [
  ['/', 'The whole desk at a glance: what you own, what ran overnight and what needs you.', '/decisions', 'Decisions'],
  ['/results', 'How your money did over a day, week, month or year, and why.', '/portfolio', 'Portfolio'],
  ['/portfolio', 'What you hold against your plan, and where the next deposit goes.', '/portfolio/stocks', 'Stock plans'],
  ['/portfolio/stocks', 'A written plan for each single stock you hold.', '/portfolio/risk', 'Risk'],
  ['/portfolio/risk', 'How rough the ride could get, and the range of outcomes ahead.', '/portfolio/tax', 'Tax'],
  ['/portfolio/tax', 'Gains and losses so far, and what a sale would cost in tax.', '/strategies', 'Strategies'],
  ['/strategies', 'Every strategy the lab has tested, what held up out of sample, and the paper race.', '/strategies/mixes', 'Mixes'],
  ['/strategies/mixes', 'Whole-portfolio mixes compared over the same history.', '/strategies/habits', 'My habits'],
  ['/strategies/habits', 'Your own trading habits, replayed under different rules.', '/decisions', 'Decisions'],
  ['/strategies/', 'One strategy: its rule, its test and its paper record.', '/strategies', 'All strategies'],
  ['/decisions', 'Proposals waiting for your yes or no. Nothing trades without you.', '/decisions/journal', 'Journal'],
  ['/decisions/journal', 'Every decision made, with the reason given at the time.', '/decisions/flight', 'Flight record'],
  ['/decisions/flight', 'How past calls turned out against what was expected.', '/research', 'Research'],
  ['/research', 'One analysis per holding, plus any other name you asked about.', '/research/opportunities', 'Opportunities'],
  ['/research/opportunities', 'A ranked list of what is worth buying or watching, with an entry zone and a size.', '/decisions', 'Decisions'],
  ['/research/sources', 'Every source the research cites.', '/research/watchlist', 'Watchlist'],
  ['/research/watchlist', 'Names you are watching but do not hold.', '/research/calendar', 'Calendar'],
  ['/research/calendar', 'Earnings, filings and other dates coming up.', '/research/compare', 'Compare'],
  ['/research/compare', 'Funds and stocks side by side.', '/research/boards', 'Boards'],
  ['/research/boards', 'Comparisons you saved.', '/research', 'Holdings'],
  ['/settings', 'How the desk is set up.', '/settings/crew', 'Crew'],
  ['/settings/crew', 'The desks that work for you, and when each one runs.', '/settings/data', 'Data'],
  ['/settings/data', 'Accounts, uploads and keys.', '/settings/box', 'Box'],
  ['/settings/box', 'The machine the desk runs on: jobs, memory and workers.', '/settings/risk', 'Risk check'],
  ['/settings/risk', 'A short questionnaire that sets your risk level.', '/', 'Bridge'],
  ['/settings/first-run', 'The checklist that brings a new desk to life.', '/', 'Bridge'],
];

const ALIAS = [
  ['/plan/stocks', '/portfolio/stocks'],
  ['/plan', '/portfolio'],
  ['/lab/risk', '/portfolio/risk'],
  ['/lab', '/strategies'],
];

export function guideFor(pathname) {
  let path = String(pathname || '/').replace(/\/+$/, '') || '/';
  for (const [from, to] of ALIAS) {
    if (path === from || path.startsWith(`${from}/`)) {
      path = `${to}${path.slice(from.length)}`;
      break;
    }
  }
  let best = null;
  for (const [key, what, to, label] of GUIDES) {
    const hit = key.endsWith('/') && key !== '/' ? path.startsWith(key) : path === key || path.startsWith(`${key}/`);
    if (key === '/' ? path === '/' : hit) {
      if (!best || key.length > best.key.length) best = { key, what, to, label };
    }
  }
  return best ? { what: best.what, next: { to: best.to, label: best.label } } : null;
}

const STEPS = [
  ['accounts', 'Pull your accounts', 'mirror'],
  ['prices', 'Fetch price history', 'engine-backfill'],
  ['numbers', 'Run today’s numbers', 'engine-daily'],
  ['market', 'Fetch market history', 'engine-french'],
  ['review', 'Write the results review', 'engine-review'],
  ['discounts', 'Scan for discounts', 'engine-discounts'],
  ['plan_keeper', 'Check your plan', 'agents-run-plan_keeper'],
  ['debrief', 'Write the debrief', 'agents-run-debrief'],
  ['plans', 'Draft your stock plans', 'agents-run-plans'],
  ['paper', 'Run the paper race', 'engine-paper'],
];
const KEYS = [
  'bridge.value',
  'bridge.brief',
  'results.day',
  'results.week',
  'results.month',
  'results.year',
  'results.debrief',
  'portfolio.holdings',
  'portfolio.stock_plans',
  'portfolio.risk',
  'portfolio.tax',
  'strategies.race',
  'strategies.mixes',
  'strategies.habits',
  'decisions.queue',
  'decisions.journal',
  'research.feed',
  'research.boards',
  'settings.risk_check',
];
const T0 = Date.parse('2026-11-11T14:02:10Z');
const at = (s) => new Date(T0 + s * 1000).toISOString().replace('.000Z', 'Z');
const NOW = '2026-11-11T14:00:00Z';

// ---------- the chain ----------
function steps(states = {}) {
  let clock = 4;
  return STEPS.map(([id, title, job]) => {
    const [state = 'waiting', detail = null, fix = null, took = 20] = states[id] || [];
    const ran = state === 'ok' || state === 'failed' || state === 'running';
    const started_at = ran ? at(clock) : null;
    if (ran) clock += took;
    const finished_at = state === 'ok' || state === 'failed' || state === 'skipped' ? at(clock) : null;
    if (state !== 'waiting') clock += 4;
    return { id, title, state, detail, fix, job, started_at, finished_at };
  });
}

const never = { state: 'idle', needs_start: true, can_start: true, blocked: null, result: null, summary: null, started_at: null, finished_at: null, last_ok_at: null, steps: steps() };

const running = {
  state: 'running',
  needs_start: true,
  can_start: false,
  blocked: { error: 'running', message: 'The desk is starting now.' },
  result: null,
  summary: 'Step 4 of 10: Fetch market history',
  started_at: at(0),
  finished_at: null,
  last_ok_at: null,
  steps: steps({ accounts: ['ok', null, null, 17], prices: ['skipped', 'Price history is already complete.'], numbers: ['ok', null, null, 44], market: ['running'] }),
};

const LOOSE = {
  accounts: ['ok', null, null, 17],
  prices: ['skipped', 'Price history is already complete.'],
  numbers: ['ok', null, null, 44],
  market: ['ok', null, null, 38],
  review: ['ok', null, null, 9],
  discounts: ['failed', 'It stopped with an error. Settings, Box, Collect logs shows why.', { label: 'Open Box', to: '/settings/box' }, 6],
  plan_keeper: ['ok', null, null, 153],
  debrief: ['skipped', 'The Debrief desk is switched off.', { label: 'Switch it on', to: '/settings/crew' }],
  plans: ['skipped', 'The Claude token has expired, so no desk can write.', { label: 'Renew the token', to: '/settings/box' }],
  paper: ['ok', null, null, 158],
};
const looseSteps = steps(LOOSE);
const loose = { state: 'done', needs_start: true, can_start: true, blocked: null, result: 'partial', summary: '7 of 10 steps done. 3 need you.', started_at: at(0), finished_at: looseSteps.at(-1).finished_at, last_ok_at: null, steps: looseSteps };

const okSteps = steps(Object.fromEntries(STEPS.map(([id], i) => [id, id === 'prices' ? ['skipped', 'Price history is already complete.'] : ['ok', null, null, 12 + i * 9]])));
const done = { state: 'done', needs_start: false, can_start: true, blocked: null, result: 'ok', summary: '10 of 10 steps done.', started_at: at(0), finished_at: okSteps.at(-1).finished_at, last_ok_at: okSteps.at(-1).finished_at, steps: okSteps };

// ---------- readiness ----------
const START = { kind: 'start', label: 'Start the desk' };
const job = (name, label) => ({ kind: 'job', job: name, label });
const link = (to, label) => ({ kind: 'link', to, label });
const row = (key, state = 'ready', why = null, action = null, next_auto = null, next_auto_text = null) => ({ key, state, why, action, next_auto, next_auto_text });
const sections = (over = {}) => KEYS.map((k) => row(k, ...(over[k] || [])));
const REVIEW_AT = ['2026-11-11T22:35:00Z', 'today at 5:35 PM'];
const SAME = {
  'results.debrief': ['blocked', 'The Debrief desk is switched off.', link('/settings/crew', 'Switch it on')],
  'portfolio.tax': ['blocked', 'Tax needs your Fidelity lot export.', link('/settings/data#inbox', 'Upload it')],
  'research.boards': ['empty', 'You haven’t saved a board yet.', link('/research/compare', 'Open Compare')],
  'settings.risk_check': ['blocked', 'You haven’t answered the risk check yet.', link('/settings/risk', 'Answer it')],
};

const neverRows = {
  'bridge.value': ['empty', 'The desk hasn’t run yet, so there are no holdings to show.', START],
  'bridge.brief': ['empty', 'The brief is written after the first run.', START],
  ...Object.fromEntries(['day', 'week', 'month', 'year'].map((k) => [`results.${k}`, ['empty', 'No results yet: the review hasn’t run.', START, ...REVIEW_AT]])),
  'portfolio.holdings': ['empty', 'The desk hasn’t run yet.', START],
  'portfolio.stock_plans': ['empty', 'No plans yet: the Plan desk hasn’t drafted any.', START, '2026-11-11T23:40:00Z', 'today at 6:40 PM'],
  'portfolio.risk': ['empty', 'Risk needs today’s numbers and a year of prices.', START],
  'strategies.race': ['empty', 'No strategy is paper trading yet.', START],
  'strategies.mixes': ['empty', 'The bands are built with today’s numbers.', START],
  'strategies.habits': ['empty', 'Your habits are read from your own trades, once your accounts are in.', START],
  'decisions.queue': ['empty', 'No proposals yet: the desks haven’t run.', START],
  'research.feed': ['empty', 'No dossiers yet: the research fetch hasn’t run.', job('engine-research', 'Fetch it now'), '2026-11-12T05:40:00Z', 'tonight at 12:40 AM'],
  ...SAME,
};

const gapRows = {
  'bridge.value': ['empty', 'Holdings haven’t been built since the last pull.', job('engine-daily', 'Run today’s numbers'), '2026-11-11T22:20:00Z', 'today at 5:20 PM'],
  'bridge.brief': ['empty', 'No brief yet: the Plan keeper hasn’t written one.', job('agents-run-plan_keeper', 'Write it now'), '2026-11-11T22:30:00Z', 'today at 5:30 PM'],
  ...Object.fromEntries(['day', 'week', 'month', 'year'].map((k) => [`results.${k}`, ['empty', 'No results yet: the review hasn’t run.', job('engine-review', 'Write it now'), ...REVIEW_AT]])),
  'portfolio.holdings': ['empty', 'Your accounts haven’t been pulled yet.', job('mirror', 'Pull them now'), '2026-11-11T22:00:00Z', 'today at 5:00 PM'],
  'portfolio.stock_plans': ['empty', 'No plans yet: the Plan desk hasn’t drafted any.', job('agents-run-plans', 'Draft them now'), '2026-11-11T23:40:00Z', 'today at 6:40 PM'],
  'portfolio.risk': ['empty', 'Risk needs a year of prices, and they aren’t in yet.', job('engine-backfill', 'Fetch price history'), '2026-11-12T06:10:00Z', 'tonight at 1:10 AM'],
  'strategies.race': ['empty', 'No strategy is paper trading yet.', job('engine-paper', 'Run the paper race'), '2026-11-11T21:45:00Z', 'today at 4:45 PM'],
  'strategies.mixes': ['empty', 'The bands are built with today’s numbers.', job('engine-daily', 'Run today’s numbers'), '2026-11-11T22:20:00Z', 'today at 5:20 PM'],
  'strategies.habits': ['empty', 'Your habits are read from your own trades, once your accounts are in.', job('mirror', 'Pull them now'), '2026-11-11T22:00:00Z', 'today at 5:00 PM'],
  'decisions.queue': ['empty', 'No proposals yet: the desks haven’t run.', job('agents-run-plan_keeper', 'Ask the desks now'), '2026-11-11T22:30:00Z', 'today at 5:30 PM'],
  'research.feed': ['empty', 'No dossiers yet: the research fetch hasn’t run.', job('engine-research', 'Fetch it now'), '2026-11-12T05:40:00Z', 'tonight at 12:40 AM'],
  ...SAME,
};

const looseRows = {
  'results.debrief': SAME['results.debrief'],
  'portfolio.stock_plans': ['blocked', 'The Claude token has expired, so the Plan desk can’t write new drafts.', link('/settings/box', 'Renew the token')],
  'strategies.mixes': ['stale', 'Market history is from October; the monthly fetch hasn’t run since.', job('engine-french', 'Fetch it now'), '2026-12-02T08:30:00Z', 'Dec 2 at 3:30 AM'],
};

export function startFixtures() {
  const ready = (start, rows) => ({ now: NOW, start: { state: start.state, needs_start: start.needs_start }, sections: sections(rows) });
  return {
    start: done,
    'start.never': never,
    'start.starting': running,
    'start.loose': loose,
    'start.gaps': done,
    readiness: ready(done, {}),
    'readiness.never': ready(never, neverRows),
    'readiness.starting': ready(running, neverRows),
    'readiness.loose': ready(loose, looseRows),
    'readiness.gaps': ready(done, gapRows),
  };
}

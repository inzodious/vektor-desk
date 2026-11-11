import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const API = process.env.DESK_EMPTY_API;
const DIR = fileURLToPath(new URL('../src/fixtures/', import.meta.url));
const NOW = '2026-11-11T14:00:00Z';
const KINDS = ['day', 'week', 'month', 'year'];
const PATHS = [
  ['engine.metrics', '/api/engine/metrics?ids=*'],
  ['engine.health', '/api/engine/health'],
  ['engine.reference', '/api/engine/reference'],
  ['engine.value', '/api/engine/value'],
  ['engine.discounts', '/api/engine/discounts'],
  ['engine.reviews.index', '/api/engine/reviews/index'],
  ...KINDS.map((k) => [`engine.reviews.never.${k}`, `/api/engine/reviews?kind=${k}`]),
  ['engine.fi', '/api/engine/fi'],
  ['engine.planfacts', '/api/engine/planfacts'],
  ['engine.series', '/api/engine/series?id=value&scope=portfolio&scope_id=all'],
  ['engine.factors', '/api/engine/factors'],
  ['engine.lookthrough', '/api/engine/lookthrough?limit=8'],
  ['engine.wash', '/api/engine/wash'],
  ['engine.lab.leaderboard', '/api/engine/lab/leaderboard'],
  ['engine.bands', '/api/engine/bands'],
  ['engine.replay', '/api/engine/replay'],
  ['engine.patterns', '/api/engine/patterns'],
  ['engine.scorecard', '/api/engine/scorecard'],
  ['engine.watchlist', '/api/engine/watchlist'],
  ['engine.macro', '/api/engine/macro'],
  ['compare', '/api/compare?ids=portfolio,shadow:plan_shadow&window=1Y'],
  ['positions', '/api/positions'],
  ['live', '/api/live'],
  ['jobs', '/api/jobs'],
  ['status', '/api/status'],
  ['lab.strategies', '/api/lab/strategies'],
  ['agents.brief', '/api/agents/brief'],
  ['agents.console', '/api/agents/console?limit=50'],
  ['agents.dossiers', '/api/agents/dossiers'],
  ['agents.runs', '/api/agents/runs?limit=8'],
  ['agents.status', '/api/agents/status'],
  ['decisions.queue', '/api/decisions/queue'],
  ['decisions.rules', '/api/decisions/rules'],
  ['decisions.profile', '/api/decisions/profile'],
  ['decisions.profile.status', '/api/decisions/profile/status'],
  ['decisions.plan-steps', '/api/decisions/plan-steps?days=14'],
  ['decisions.deposits', '/api/decisions/deposits'],
  ['decisions.plans', '/api/decisions/plans'],
  ['decisions.calendar', '/api/decisions/calendar'],
  ['decisions.journal', '/api/decisions/journal?limit=500'],
  ['decisions.unmatched', '/api/decisions/unmatched'],
  ['decisions.summary', '/api/decisions/summary'],
  ['decisions.risk', '/api/decisions/risk'],
  ['decisions.risk.versions', '/api/decisions/risk/versions'],
  ['decisions.convictions', '/api/decisions/convictions'],
];

// ---------- a desk that has never run, as its own API answers ----------
const tidy = {
  jobs: (b) => ({ ...b, now: NOW, scheduler_alive: true }),
  status: (b) => ({ ...b, reviews: b.reviews ? { ...b.reviews, due: '2026-11-11T22:35:00Z' } : b.reviews }),
  'decisions.profile.status': (b) => ({ ...b, path: '/data/desk.yaml' }),
  'decisions.journal': (b) => ({ ...b, days: (b.days || []).map((d) => ({ ...d, day: '2026-11-10' })) }),
};

if (!API) {
  console.log('never.mjs: set DESK_EMPTY_API to a desk API on an empty data directory to re-record.');
} else {
  for (const [name, path] of PATHS) {
    const res = await fetch(`${API}${path}`);
    const body = await res.json().catch(() => null);
    const out = res.ok ? (tidy[name] || ((b) => b))(body) : { __status: res.status, detail: body?.detail || `HTTP ${res.status}` };
    const file = name.includes('.never.') ? name : `${name}.never`;
    writeFileSync(`${DIR}${file}.json`, `${JSON.stringify(out, null, 1)}\n`);
    console.log(`wrote ${file}.json`);
  }
}

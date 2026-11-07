import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const DIR = fileURLToPath(new URL('../src/fixtures/', import.meta.url));
const read = (n) => JSON.parse(readFileSync(`${DIR}${n}.json`, 'utf8'));
const save = (n, body) => {
  writeFileSync(`${DIR}${n}.fresh.json`, `${JSON.stringify(body, null, 1)}\n`);
  console.log(`wrote ${n}.fresh.json`);
};

// ---------- a desk on its first day with real-shaped data ----------
const live = read('live.long');
save('live', live);
const health = read('engine.health.warn');
save('engine.health', {
  ...health,
  status: 'warn',
  checks: [
    ...health.checks.filter((c) => !['shares', 'symbol_kinds'].includes(c.check_name)),
    { check_name: 'shares', status: 'warn', detail: 'No lot export yet; tax lots and wash-sale checks need one.' },
    { check_name: 'symbol_kinds', status: 'warn', detail: '1 symbol has no type yet (0999999); it counts as a fund until its profile loads.' },
  ],
});
save('decisions.profile.status', read('decisions.profile.status.empty'));
const agents = read('agents.status');
save('agents.status', { ...agents, enabled: false, desks: agents.desks.map((d) => ({ ...d, enabled: false, last_run: null, next_run: null, week: { ...d.week, runs: 0, turns: 0, tokens: 0 } })) });
save('agents.runs', { runs: [] });
save('agents.brief', read('agents.brief.empty'));
save('agents.console', read('agents.console.empty'));
save('agents.dossiers', []);
save('decisions.queue', read('decisions.queue.empty'));
save('decisions.journal', { days: [], count: 0 });
save('engine.scorecard', read('engine.scorecard.empty'));
save('engine.fi', read('engine.fi.empty'));
save('engine.factors', { ...read('engine.factors.empty'), note: 'No holding has three years of prices overlapping the factors.' });
save('engine.lots', { lots: [], files: [] });
save('engine.watchlist', read('engine.watchlist.empty'));
const lab = read('lab.strategies.empty');
save('lab.strategies', lab);

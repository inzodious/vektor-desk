import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { groupLive } from '../src/live/context.js';
import { chunkIds } from '../src/lib/lab.js';

const API = process.env.DESK_API || 'http://127.0.0.1:8000';
const OUT = fileURLToPath(new URL('../src/fixtures/', import.meta.url));
const DAY = '2026-11-09';
const AS_OF = `${DAY}T16:40:00+00:00`;

// ---------- helpers ----------
async function get(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) throw new Error(`${path} answered ${res.status}`);
  return res.json();
}

function save(name, body) {
  writeFileSync(`${OUT}${name}.json`, `${JSON.stringify(body, null, 1)}\n`);
  console.log(`wrote ${name}.json`);
}

let seed = 11;
function rand() {
  seed = (seed * 16807) % 2147483647;
  return (seed - 1) / 2147483646;
}

const round = (v, d = 2) => Math.round(v * 10 ** d) / 10 ** d;

// ---------- read the demo desk ----------
const health = await get('/api/health');
if (!health.demo) throw new Error('Point DESK_API at an API running with DESK_DEMO=1');

const closed = await get('/api/live');
const positions = await get('/api/positions');
const value = await get('/api/engine/value');
const metrics = await get('/api/engine/metrics?ids=*');
const lots = await get('/api/engine/lots');

// ---------- live variants ----------
const MOVES = {};
const NAV = new Set(positions.positions.filter((p) => /fund/i.test(p.description || '') && !/etf/i.test(p.description || '')).map((p) => p.symbol));
const symbols = [...new Set(closed.rows.filter((r) => r.source !== 'cash').map((r) => r.symbol))];
symbols.forEach((s) => {
  MOVES[s] = NAV.has(s) ? 0 : round((rand() - 0.45) * 0.05, 4);
});

const openRows = closed.rows.map((r) => {
  if (r.source === 'cash' || NAV.has(r.symbol)) return { ...r };
  const price = round(r.prev_close * (1 + MOVES[r.symbol]));
  return { ...r, price, value: round(r.shares * price), day_change: round(r.shares * (price - r.prev_close)), source: 'finnhub' };
});
const total = round(openRows.reduce((a, r) => a + r.value, 0));
const change = round(openRows.reduce((a, r) => a + r.day_change, 0));
const open = { ...closed, state: 'open', day: DAY, opens_at: `${DAY}T14:30:00+00:00`, closes_at: `${DAY}T21:00:00+00:00`, as_of: AS_OF, value: total, day_change: change, day_change_pct: round((change / (total - change)) * 100), quality: 'ok', rows: openRows };
save('live', open);
save('live.stale', { ...open, quality: 'stale', as_of: `${DAY}T15:05:00+00:00` });
save('live.closed', { ...closed, day: '2026-11-07' });
save('live.long', { ...open, rows: [...openRows, { ...openRows.find((r) => r.source !== 'cash'), symbol: '0999999', source: 'holdings' }, { ...openRows.find((r) => r.source !== 'cash'), symbol: 'LONGSYMBOL' }] });
save('live.empty', { state: 'closed', day: '2026-11-07', opens_at: null, closes_at: null, as_of: null, holdings_date: null, value: 0, day_change: 0, day_change_pct: null, quality: 'insufficient_history', rows: [], benchmarks: {} });

const intraday = {};
symbols
  .filter((s) => !NAV.has(s))
  .forEach((s) => {
    const prev = closed.rows.find((r) => r.symbol === s).prev_close;
    const end = prev * (1 + MOVES[s]);
    intraday[s] = Array.from({ length: 28 }, (_, i) => ({
      t: new Date(Date.parse(`${DAY}T14:30:00Z`) + i * 300000).toISOString().replace('.000Z', '+00:00'),
      price: round(i === 27 ? end : prev + (end - prev) * (i / 27) + (rand() - 0.5) * 0.008 * prev),
    }));
  });
save('live.intraday', { day: DAY, symbols: intraday });

// ---------- engine ----------
save('positions', positions);
save('engine.value', value);
save('engine.metrics', metrics);
save('engine.lots', { lots: [], files: [] });
save('engine.lots.any', { lots: [], files: [] });
const withLots = lots.lots.length ? lots : null;
if (withLots) save(`engine.lots.${withLots.lots[0].symbol}`, { lots: withLots.lots.filter((l) => l.symbol === withLots.lots[0].symbol), files: withLots.files });

const top = symbols[0];
const prices = await get(`/api/engine/prices?symbol=${top}&start=2025-11-07`);
save('engine.prices.any', prices);

for (const [scope, id] of [
  ['portfolio', 'all'],
  ['shadow', 'plan_shadow'],
  ['shadow', 'sp500_shadow'],
]) {
  save(`engine.series.${id}`, await get(`/api/engine/series?id=value&scope=${scope}&scope_id=${id}`));
}

for (const p of ['profile', 'rules', 'deposits']) save(`decisions.${p}`, await get(`/api/decisions/${p}`));

// ---------- decisions ----------
const queue = await get('/api/decisions/queue');
save('decisions.queue', queue);
save('decisions.queue.empty', { count: 0, snoozed: 0, to_place: 0, items: [] });
const journal = await get('/api/decisions/journal?limit=200');
save('decisions.journal', journal);
save('decisions.summary', await get('/api/decisions/summary'));
save('decisions.unmatched', await get('/api/decisions/unmatched'));
save('decisions.calendar', await get('/api/decisions/calendar'));
const ids = [...queue.items.map((d) => d.id), ...journal.days.flatMap((g) => g.items.filter((d) => d.created_at >= '2026-11-01').map((d) => d.id))];
for (const id of ids) {
  save(`decisions.${id}`, await get(`/api/decisions/${id}`));
  save(`decisions.${id}.ticket`, await get(`/api/decisions/${id}/ticket`));
}

// ---------- agents and tax ----------
save('agents.status', await get('/api/agents/status'));
save('agents.brief', await get('/api/agents/brief'));
save('agents.brief.empty', { summary: null });
save('agents.runs', await get('/api/agents/runs?limit=50'));
save('engine.wash', await get('/api/engine/wash'));

// ---------- research ----------
const dossiers = await get('/api/agents/dossiers');
save('agents.dossiers', dossiers);
for (const d of dossiers) save(`agents.dossiers.${d.symbol}`, d);
save('agents.console', await get('/api/agents/console?limit=50'));
save('engine.macro', await get('/api/engine/macro?start=2025-11-07'));

const watch = await get('/api/engine/watchlist');
save('engine.watchlist', watch);
save('engine.watchlist.empty', { symbols: [] });

const researched = [...new Set([...dossiers.map((d) => d.symbol), ...watch.symbols.map((w) => w.symbol), ...symbols])];
for (const sym of researched) {
  save(`engine.research.${sym}`, await get(`/api/engine/research?symbol=${sym}`));
  save(`engine.prices.${sym}`, await get(`/api/engine/prices?symbol=${sym}&start=2025-11-07`));
  save(`engine.metrics.${sym}`, await get(`/api/engine/metrics?ids=*&scope=holding&scope_id=${sym}`));
}
save('engine.research.any', { symbol: null, filings: [], fundamentals: {}, earnings: [], insiders: [], signals: [] });

// ---------- lab ----------
const slug = (ids) => ids.join(',').replace(/[^A-Za-z0-9]+/g, '_');
const held = symbols.slice(0, 3);
const compareSets = [
  [...held, 'shadow:plan_shadow'],
  ['portfolio', 'shadow:plan_shadow', 'shadow:sp500_shadow'],
  ['FXAIX', 'FTEC', 'VXUS'],
];
for (const rows of [openRows, closed.rows]) {
  const order = groupLive(rows).symbols.map((g) => g.symbol);
  compareSets.push(...chunkIds([...order, 'portfolio', 'shadow:plan_shadow']));
}
const seen = new Set();
for (const ids of compareSets) {
  if (ids.length < 2 || seen.has(slug(ids))) continue;
  seen.add(slug(ids));
  const body = await get(`/api/compare?ids=${encodeURIComponent(ids.join(','))}&window=1Y`);
  save(`compare.${slug(ids)}`, body);
}
save('compare', await get(`/api/compare?ids=${encodeURIComponent(compareSets[0].join(','))}&window=1Y`));
save('engine.lookthrough', await get('/api/engine/lookthrough?limit=8'));
save('engine.series.all', await get('/api/engine/series?id=value&scope=portfolio&scope_id=all'));

// ---------- strategy lab ----------
const labList = await get('/api/lab/strategies');
save('lab.strategies', labList);
save('lab.strategies.empty', { ...labList, strategies: [], rules: [] });
for (const s of [...labList.strategies, ...labList.rules]) save(`lab.strategies.${s.id}`, await get(`/api/lab/strategies/${encodeURIComponent(s.id)}`));
save('lab.strategies.pick-one', await get('/api/lab/strategies/pick-one'));

// ---------- flight record and patterns ----------
const card = await get('/api/engine/scorecard');
save('engine.scorecard', card);
save('engine.scorecard.empty', { ...card, groups: [], desks: [], saves: { n: 0, usd: 0 }, offplan_gap: { n: 0, total_usd: 0, mean_usd: null, hit_rate: null, ci_low: null, ci_high: null }, decisions: [] });
save('engine.patterns', await get('/api/engine/patterns'));

// ---------- FI path and factors ----------
const fiView = await get('/api/engine/fi');
save('engine.fi', fiView);
save('engine.fi.empty', { as_of: fiView.as_of, status: 'not_ready', note: 'No FI goal in Escape Vektor yet; set yearly spend and target age there.' });
save('engine.fi.history', { as_of: fiView.as_of, status: 'not_ready', fi_number: fiView.fi_number, target_date: fiView.target_date, start_value: fiView.start_value, monthly_deposit: fiView.monthly_deposit, deposit_source: fiView.deposit_source, required_return_pct: fiView.required_return_pct, note: "The Monte Carlo needs the French monthly market history; the engine's monthly french job fetches it." });
const factorView = await get('/api/engine/factors');
save('engine.factors', factorView);
save('engine.factors.empty', { as_of: factorView.as_of, holdings: {}, portfolio: {}, coverage_pct: 0, note: 'No French factors yet.' });

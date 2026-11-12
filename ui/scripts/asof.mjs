import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const DIR = fileURLToPath(new URL('../src/fixtures/', import.meta.url));
const read = (name) => JSON.parse(readFileSync(`${DIR}${name}.json`, 'utf8'));
const write = (name, body) => {
  writeFileSync(`${DIR}${name}.json`, `${JSON.stringify(body, null, 1)}\n`);
  console.log(`wrote ${name}.json`);
};

// ---------- the book the fixtures already carry ----------
const FRIDAY = '2026-11-06';
const MONDAY = '2026-11-09';
const review = read('engine.reviews.day');
const index = read('engine.reviews.index');
const live = read('live');
const closed = read('live.closed');

function setMetric(rows, id, value, match = {}) {
  const want = { scope: 'portfolio', scope_id: 'all', window: 'now', ...match };
  const row = rows.find((r) => r.metric_id === id && r.scope === want.scope && r.scope_id === want.scope_id && r.window === want.window);
  if (row) row.value = value;
}

function metricOf(rows, id, match = {}) {
  const want = { scope: 'portfolio', scope_id: 'all', window: 'now', ...match };
  return rows.find((r) => r.metric_id === id && r.scope === want.scope && r.scope_id === want.scope_id && r.window === want.window)?.value ?? null;
}

// ---------- base: one Friday everywhere, live quotes on Monday ----------
const metrics = read('engine.metrics');
setMetric(metrics.metrics, 'value.day_change', review.pack.value.change_usd);
setMetric(metrics.metrics, 'ret.twr', review.pack.value.change_pct, { window: '1D' });
write('engine.metrics', metrics);

function numbersFrom(rows) {
  return {
    value: metricOf(rows, 'value.market'),
    day_change: metricOf(rows, 'value.day_change'),
    day_change_pct: metricOf(rows, 'ret.twr', { window: '1D' }),
    cash_ready: metricOf(rows, 'cash.ready'),
    cash_pending: metricOf(rows, 'cash.pending'),
    cash_pending_days: metricOf(rows, 'cash.pending_days'),
    margin_debit: metricOf(rows, 'margin.debit'),
    margin_cost_month: metricOf(rows, 'margin.cost_month'),
  };
}

const base = {
  day: FRIDAY,
  at: `${FRIDAY}T22:21:40+00:00`,
  provisional: false,
  status: 'final',
  words: 'Fri Nov 6, at the close.',
  previous_day: '2026-11-05',
  expected_day: FRIDAY,
  behind: null,
  prices: { official: 5, quoted: 0, carried: [] },
  numbers: numbersFrom(metrics.metrics),
  live: { day: MONDAY, state: 'open', at: live.as_of, value: live.value, day_change: live.day_change, day_change_pct: live.day_change_pct, words: 'Live, Mon Nov 9, 11:40 AM ET' },
  market: { state: 'open', day: MONDAY },
  review: { day: FRIDAY, computed_at: review.computed_at },
  debrief: { day: FRIDAY, written_at: review.debrief?.written_at || null, stale: false },
};
write('asof', base);
write('asof.closed', { ...base, live: null, market: { state: 'closed', day: '2026-11-07' } });
write('asof.never', { day: null, at: null, provisional: false, status: 'empty', words: 'The engine has not run yet.', previous_day: null, expected_day: null, behind: null, prices: { official: 0, quoted: 0, carried: [] }, numbers: {}, live: null, market: { state: 'closed', day: MONDAY }, review: null, debrief: null });

// ---------- evening: the book has moved on to Monday, borrowed money on it ----------
const EVENING = { value: 16480.12, day_change: 86.63, day_change_pct: 0.5284, cash_ready: 142, cash_pending: 500, cash_pending_days: 22, margin_debit: 1500, margin_cost_month: 15.09 };
const eveningMetrics = JSON.parse(JSON.stringify(metrics));
eveningMetrics.as_of = MONDAY;
eveningMetrics.metrics.forEach((r) => {
  r.as_of = MONDAY;
});
setMetric(eveningMetrics.metrics, 'value.market', EVENING.value);
setMetric(eveningMetrics.metrics, 'value.day_change', EVENING.day_change);
setMetric(eveningMetrics.metrics, 'ret.twr', EVENING.day_change_pct, { window: '1D' });
setMetric(eveningMetrics.metrics, 'cash.pending_days', EVENING.cash_pending_days);
setMetric(eveningMetrics.metrics, 'margin.debit', EVENING.margin_debit);
setMetric(eveningMetrics.metrics, 'margin.cost_month', EVENING.margin_cost_month);
write('engine.metrics.evening', eveningMetrics);

const eveningReview = JSON.parse(JSON.stringify(review));
Object.assign(eveningReview, { start: MONDAY, end: MONDAY, as_of: MONDAY, closed: true, final: false, computed_at: `${MONDAY}T22:35:12+00:00` });
Object.assign(eveningReview.pack, { start: MONDAY, end: MONDAY, as_of: MONDAY, label: 'Mon Nov 9, 2026' });
eveningReview.pack.value = { start: 16393.49, end: EVENING.value, change_usd: EVENING.day_change, change_pct: EVENING.day_change_pct, net_flows: 0, gain_usd: EVENING.day_change };
eveningReview.pack.provisional = { day: MONDAY, carried: ['FXAIX'], note: 'Mon Nov 9 uses closing quotes until the official closes land this evening; fund prices can follow in the morning. FXAIX carries its last price.' };
if (eveningReview.debrief) Object.assign(eveningReview.debrief, { headline: 'Up $87 on Monday, in step with the S&P 500.', written_at: `${MONDAY}T22:50:03+00:00`, stale: false });
write('engine.reviews.evening.day', eveningReview);

// ---------- a debrief written before the numbers moved ----------
const stale = (rewrite) => ({ ...review, debrief: { ...review.debrief, stale: true, rewrite } });
write('engine.reviews.rewriting.day', stale({ state: 'due', due_at: `${MONDAY}T22:46:00+00:00`, words: null }));
write('engine.reviews.rewritefail.day', stale({ state: 'failed', due_at: `${MONDAY}T22:46:00+00:00`, words: 'Written before the final numbers. The rewrite did not finish; the desk tries again at 5:46 PM.' }));

const eveningIndex = JSON.parse(JSON.stringify(index));
eveningIndex.as_of = MONDAY;
eveningIndex.kinds.day = [{ start: MONDAY, end: MONDAY, as_of: MONDAY, label: 'Mon Nov 9, 2026', closed: true, final: false, change_usd: EVENING.day_change, change_pct: EVENING.day_change_pct, has_debrief: true }, ...index.kinds.day];
write('engine.reviews.index.evening', eveningIndex);

write('live.evening', { ...closed, state: 'after', day: MONDAY, as_of: `${MONDAY}T23:40:00+00:00`, holdings_date: MONDAY, value: 16513.99, day_change: 120.5, day_change_pct: 0.74 });

const evening = {
  ...base,
  day: MONDAY,
  at: `${MONDAY}T22:21:40+00:00`,
  provisional: true,
  status: 'provisional',
  words: 'Mon Nov 9, 5:21 PM ET. Provisional until official closes land this evening; fund prices can follow in the morning.',
  previous_day: FRIDAY,
  expected_day: MONDAY,
  prices: { official: 0, quoted: 4, carried: ['FXAIX'] },
  numbers: EVENING,
  live: null,
  market: { state: 'after', day: MONDAY },
  review: { day: MONDAY, computed_at: `${MONDAY}T22:35:12+00:00` },
  debrief: { day: MONDAY, written_at: `${MONDAY}T22:50:03+00:00`, stale: false },
};
write('asof.evening', evening);

// ---------- lagging: the book is on Monday, the review and some numbers are still Friday's ----------
write('asof.lagging', { ...evening, provisional: false, status: 'final', words: 'Mon Nov 9, at the close.', at: '2026-11-10T06:26:10+00:00', prices: { official: 5, quoted: 0, carried: [] }, market: { state: 'closed', day: '2026-11-10' }, review: { day: FRIDAY, computed_at: review.computed_at }, debrief: { day: FRIDAY, written_at: review.debrief?.written_at || null, stale: false } });

// ---------- behind: Monday's prices have not landed ----------
write('asof.behind', { ...base, at: `${MONDAY}T22:21:40+00:00`, expected_day: MONDAY, behind: { sessions: 1, reason: 'No closing quotes or official closes for Mon Nov 9 yet. The next engine run picks them up.' }, live: null, market: { state: 'closed', day: MONDAY } });

// ---------- afterclose: the closing run has not landed, the quotes have ----------
const quoted = (r) => r.source === 'holdings' && r.symbol !== 'FXAIX';
const moved = 120.5 / closed.rows.filter(quoted).reduce((a, r) => a + r.value, 0);
const cents = (n) => Math.round(n * 100) / 100;
const afterRows = closed.rows.map((r) => (quoted(r) ? { ...r, source: 'finnhub', price: cents(r.price * (1 + moved)), value: cents(r.value * (1 + moved)), day_change: cents(r.value * moved) } : r));
write('live.afterclose', { ...closed, rows: afterRows, state: 'after', day: MONDAY, as_of: `${MONDAY}T23:40:00+00:00`, holdings_date: FRIDAY, value: 16513.99, day_change: 120.5, day_change_pct: 0.74 });
write('live.intraday.noticks', { day: MONDAY, symbols: {} });
write('asof.afterclose', {
  ...base,
  at: `${MONDAY}T22:21:40+00:00`,
  expected_day: MONDAY,
  behind: { sessions: 1, reason: 'Closing quotes are in for Mon Nov 9, and the book stops at Fri Nov 6. The next engine run moves it; nothing to tap.' },
  live: { day: MONDAY, state: 'after', at: `${MONDAY}T23:40:00+00:00`, value: 16513.99, day_change: 120.5, day_change_pct: 0.74, words: 'Mon Nov 9, last quotes 6:40 PM ET' },
  market: { state: 'after', day: MONDAY },
});

// ---------- waiting: the day is booked, two funds have not printed their official close ----------
write('asof.waiting', {
  ...evening,
  at: '2026-11-10T00:12:10+00:00',
  words: 'Mon Nov 9, at the close. Waiting on the official close for FXAIX and FTEC; the day is restated when it lands.',
  prices: { official: 3, quoted: 0, carried: [], waiting: ['FXAIX', 'FTEC'] },
  market: { state: 'closed', day: MONDAY },
});

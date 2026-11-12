import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const DIR = fileURLToPath(new URL('../src/fixtures/', import.meta.url));
const at = (hms, day = '2026-11-09') => `${day}T${hms}+00:00`;
const read = (name) => JSON.parse(readFileSync(`${DIR}${name}.json`, 'utf8'));
const write = (name, body) => {
  writeFileSync(`${DIR}${name}.json`, `${JSON.stringify(body, null, 1)}\n`);
  console.log(`wrote ${name}.json`);
};

// ---------- the strategy library ----------
const KINDS = [
  { key: 'classic', title: 'Old and tested' },
  { key: 'practical', title: 'Practical' },
  { key: 'novel', title: 'Novel and creative' },
];
const SPY = 'S&P 500 (SPY)';
const MIX = 'Your plan’s mix';
const MARKET = 'US stock market (French)';
const SMALL = 'Small caps (IWM)';
const PLAIN = 'The same deposits, invested plainly';
const LUMP = 'Investing it all on day one';
const LIB_NOTE = 'Every number here is out of sample: from periods the strategy was not tuned on. The last two years of data are held back and untouched. Each row names what it is measured against; for most that is the S&P 500 with dividends reinvested. Held up means ahead of its benchmark by more than luck allows across every variant tried in the library. The luck bar counts all 212 variants tried across the library, not only a row’s own, so it rises for every row as strategies are added.';
const BENCH_WORDS = {
  [SPY]: 'The S&P 500 index fund SPY, bought and held with dividends reinvested.',
  [MIX]: 'The funds in your plan at their target weights. With no plan loaded this is the S&P 500.',
  [MARKET]: 'Every US stock weighted by size, from Ken French’s research data.',
  [SMALL]: 'The small-company index fund IWM, bought and held with dividends reinvested.',
  [PLAIN]: 'The same starting money and monthly deposits put into the same funds, without the rule.',
  [LUMP]: 'The whole sum invested in the same funds on the first day.',
};
const LIB = [
  ['buy-hold-total', 'Buy and hold the total market', 'classic', 'Buy and hold', 'Buy the whole market and never touch it.', SPY, 'within_noise', 0.1],
  ['sixty-forty', '60/40 stocks and bonds', 'classic', 'Allocation', 'Sixty percent stocks, forty percent bonds, rebalanced once a year.', SPY, 'fell_short', -2.4],
  ['trend-200d', '200-day trend filter', 'classic', 'Trend', 'Hold stocks above their 200-day average, bonds below it.', SPY, 'within_noise', 0.6],
  ['momentum-12-1', '12-1 momentum', 'classic', 'Momentum', 'Each month buy what rose most over the past year, skipping the last month.', SPY, 'held_up', 3.1],
  ['dual-momentum', 'Dual momentum', 'classic', 'Momentum', 'Own the stronger of US and international stocks, or bonds when both lag cash.', SPY, 'within_noise', 1.2],
  ['low-vol', 'Low volatility', 'classic', 'Low volatility', 'Own the calmest fifth of large companies.', SPY, 'within_noise', 0.4],
  ['value-tilt', 'Value tilt', 'classic', 'Factor tilt', 'Lean toward cheap companies using the French value series.', MARKET, 'fell_short', -1.1],
  ['size-tilt', 'Small company tilt', 'classic', 'Factor tilt', 'Lean toward small companies.', MARKET, 'fell_short', -1.8],
  ['quality-tilt', 'Profitability and quality tilt', 'classic', 'Factor tilt', 'Lean toward profitable companies that invest carefully.', MARKET, 'held_up', 2.2],
  ['sector-rotation', 'Sector rotation', 'classic', 'Momentum', 'Hold the three strongest sectors and rotate monthly.', SPY, 'inconclusive', null],
  ['risk-parity', 'Risk parity', 'classic', 'Allocation', 'Size stocks and bonds so each carries the same risk.', MIX, 'within_noise', 0.3],
  ['vol-target', 'Volatility targeting', 'classic', 'Allocation', 'Hold less when markets are jumpy, more when they are calm.', SPY, 'within_noise', 0.8],
  ['dip-5', 'Buy the 5% dip', 'practical', 'Dip buying', 'Hold cash back and put it in after a 5% drop from the high.', SPY, 'fell_short', -0.9],
  ['dip-10', 'Buy the 10% dip', 'practical', 'Dip buying', 'Hold cash back and put it in after a 10% drop from the high.', SPY, 'fell_short', -1.6],
  ['deposit-monthly', 'Monthly deposit versus lump sum', 'practical', 'Deposits', 'Spread a year of deposits monthly, or invest it all on day one.', LUMP, 'rule', null],
  ['rebalance-band-5', 'Rebalance at a 5-point band', 'practical', 'Rebalancing', 'Leave the mix alone until a fund drifts 5 points, then bring it back.', MIX, 'held_up', 0.9],
  ['rebalance-yearly', 'Rebalance once a year', 'practical', 'Rebalancing', 'Bring every fund back to target each January.', MIX, 'within_noise', 0.2],
  ['as-held', 'Your book as held', 'practical', 'Buy and hold', 'What you own today, held with no changes.', SPY, 'within_noise', 0.5],
  ['safe-mix', 'The safe mix', 'practical', 'Allocation', 'The plan’s four-fund mix at its targets.', SPY, 'fell_short', -0.7],
  ['tech-tilt', 'Aggressive tech tilt', 'practical', 'Factor tilt', 'The safe mix with a quarter moved into technology.', SPY, 'within_noise', 1.9],
  ['trend-dip', 'Trend-filtered dip buying', 'novel', 'Dip buying', 'Buy the dip only while the market is still above its 200-day average.', SPY, 'held_up', 1.7],
  ['insider-momentum', 'Insider clusters with momentum', 'novel', 'Insiders', 'Buy when three insiders buy within a month and the stock is already rising.', SMALL, 'within_noise', 2.6],
  ['drawdown-boost', 'Deposit boost in drawdowns', 'novel', 'Deposits', 'Double the monthly deposit while the market is 15% off its high.', PLAIN, 'rule', null],
  ['breakout-vol-cap', '52-week-high breakout with a volatility cap', 'novel', 'Breakout', 'Buy new 52-week highs, but only in stocks calmer than the market.', SPY, 'fell_short', -0.4],
  ['pead-insiders', 'Earnings drift where insiders also bought', 'novel', 'Earnings', 'Hold for 60 days after a strong earnings surprise when insiders bought too.', SPY, 'waiting', null],
  ['discount-entries', 'Discount-day entries', 'novel', 'Dip buying', 'Buy names the discount scan flags, sized by the caps, and hold a year.', SPY, 'not_run', null],
];
const LINE = {
  held_up: (x) => `Ahead by ${x.toFixed(1)} points a year out of sample, more than luck explains across 212 tries.`,
  within_noise: (x) => `Ahead by ${x.toFixed(1)} points a year out of sample, but inside the luck band for 212 tries.`,
  fell_short: (x) => `Behind by ${Math.abs(x).toFixed(1)} points a year out of sample.`,
  inconclusive: () => 'Too few out-of-sample trades to say either way.',
};

function libraryRow([id, title, kind, family, description, benchmark, outcome, excess]) {
  const rule = outcome === 'rule';
  const tested = !['waiting', 'not_run'].includes(outcome);
  const verdict = !tested ? null : rule ? (id === 'deposit-monthly' ? 'fell_short' : 'held_up') : outcome;
  return {
    id,
    title,
    kind,
    family,
    description,
    benchmark,
    benchmark_words: BENCH_WORDS[benchmark],
    type: rule ? 'rule' : 'experiment',
    status: tested ? 'tested' : outcome,
    verdict,
    line: !tested ? null : rule ? (id === 'deposit-monthly' ? 'Lump sum finished ahead in 68 of 100 ten-year starts; monthly deposits trailed by a median 1.4 points.' : 'Finished ahead of plain monthly deposits in 81 of 100 ten-year starts, by a median 0.8 points.') : LINE[outcome](excess),
    reason: outcome === 'waiting' ? 'In tonight’s queue. Small-company history is still loading.' : outcome === 'not_run' ? 'Needs 60 discount days on record; the desk has 14.' : null,
    tested_at: tested ? at('08:12:00') : null,
    out_of_sample: tested && !rule && excess != null ? { start: '2019-01-02', end: '2026-11-06', ann_return_pct: 11.2 + excess, excess_pts: excess, sharpe: 0.71 + excess / 20, mdd_pct: -24.5 } : null,
    noise: tested && !rule && excess != null ? { trials: 212, excess_total_pts: excess * 7.8, band_total_pts: 12.4, luck: Math.abs(excess * 7.8) < 12.4 } : null,
    rule: rule && tested ? { horizon_years: 10, starts: 100, p5_pts: -3.2, p50_pts: id === 'deposit-monthly' ? -1.4 : 0.8, p95_pts: 4.1, share_better: id === 'deposit-monthly' ? 0.32 : 0.81 } : null,
    research_only: benchmark === MARKET,
    yardstick: false,
    outdated: tested && id === 'dual-momentum',
    caveats: family === 'Insiders' ? ['Insider filings arrive up to two days late.'] : [],
    detail: `/api/lab/strategies/${id}`,
  };
}

function library(rows) {
  const n = (f) => rows.filter(f).length;
  return {
    as_of: rows.some((r) => r.status === 'tested') ? at('08:12:00') : null,
    trials: 212,
    note: rows.some((r) => r.status === 'tested') ? LIB_NOTE : 'Nothing has run yet. The lab works through the list tonight, from 1 AM.',
    counts: { outdated: n((r) => r.outdated), total: rows.length, tested: n((r) => r.status === 'tested'), held_up: n((r) => r.verdict === 'held_up'), within_noise: n((r) => r.verdict === 'within_noise'), fell_short: n((r) => r.verdict === 'fell_short'), inconclusive: n((r) => r.verdict === 'inconclusive'), waiting: n((r) => r.status === 'waiting'), not_run: n((r) => r.status === 'not_run') },
    kinds: KINDS,
    benchmarks: Object.entries(BENCH_WORDS).map(([name, words]) => ({ name, words, rows: n((r) => r.benchmark === name) })),
    rows,
  };
}

// ---------- a long library: about 60 entries ----------
const MORE = [
  ['classic', 'Momentum', 'Sector momentum', 'Hold the three sectors that rose most over the past {n} months.', SPY, [3, 6, 9]],
  ['classic', 'Trend', 'Moving-average trend filter', 'Hold stocks above their {n}-day average, bonds below it.', SPY, [50, 100, 150]],
  ['classic', 'Low volatility', 'Calmest sectors', 'Own the three sectors that moved least over {n} days.', SPY, [63, 126, 252]],
  ['classic', 'Factor tilt', 'Value and momentum blend', 'Mix cheap and rising companies, rebalanced every {n} months.', MARKET, [1, 3, 12]],
  ['practical', 'Dip buying', 'Buy the drop', 'Hold cash back and put it in after a {n}% drop from the high.', PLAIN, [3, 7, 15]],
  ['practical', 'Rebalancing', 'Rebalance at a band', 'Leave the mix alone until a fund drifts {n} points, then bring it back.', MIX, [3, 8, 10]],
  ['practical', 'Deposits', 'Split the deposit', 'Put each deposit in over {n} weeks instead of at once.', LUMP, [2, 4, 8]],
  ['practical', 'Allocation', 'Bond cushion', 'Hold {n}% in bonds and the rest in the total market.', SPY, [10, 20, 30]],
  ['novel', 'Insiders', 'Insider clusters', 'Buy small companies when {n} insiders buy within a month.', SMALL, [2, 4, 5]],
  ['novel', 'Breakout', 'Breakout with a trend filter', 'Buy new {n}-week highs while the market is above its 200-day average.', SPY, [13, 26, 52]],
  ['novel', 'Dip buying', 'Sector dip rotation', 'Each month buy the three sectors furthest below their {n}-day high.', SPY, [63, 126, 252]],
  ['novel', 'Momentum', 'Small-company momentum', 'Buy the small companies that rose most over {n} months.', SMALL, [3, 6]],
];
const SPREAD = ['within_noise', 'fell_short', 'held_up', 'within_noise', 'fell_short', 'within_noise', 'inconclusive', 'fell_short'];
const BIG = [
  ...LIB,
  ...MORE.flatMap(([kind, family, title, description, benchmark, ns], i) =>
    ns.map((n, j) => {
      const outcome = SPREAD[(i * 3 + j) % SPREAD.length];
      const excess = outcome === 'held_up' ? 1.4 + j * 0.5 : outcome === 'within_noise' ? 0.2 + j * 0.3 : outcome === 'fell_short' ? -0.6 - j * 0.4 : null;
      return [`${title.toLowerCase().replace(/[^a-z]+/g, '-')}-${n}`, `${title}, ${n}`, kind, family, description.replace('{n}', n), benchmark, outcome, excess];
    }),
  ),
];

const ORDER = ['held_up', 'within_noise', 'inconclusive', 'fell_short', null];
const libraryOrder = (a, b) => KINDS.findIndex((k) => k.key === a.kind) - KINDS.findIndex((k) => k.key === b.kind) || ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict) || (b.out_of_sample?.excess_pts ?? -99) - (a.out_of_sample?.excess_pts ?? -99);
const big = BIG.map(libraryRow).sort(libraryOrder);
const tested = LIB.map(libraryRow).sort((a, b) => KINDS.findIndex((k) => k.key === a.kind) - KINDS.findIndex((k) => k.key === b.kind) || ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict) || (b.out_of_sample?.excess_pts ?? -99) - (a.out_of_sample?.excess_pts ?? -99));
const waiting = LIB.map((r) => libraryRow([...r.slice(0, 6), 'waiting', null])).map((r) => ({ ...r, reason: 'In tonight’s queue. The lab starts at 1 AM.' }));

// ---------- holdings analysed ----------
const holding = (symbol, name, kind, weight_pct, status, o = {}) => ({ symbol, name, kind, weight_pct, status, status_line: null, verdict: null, verdict_line: null, analysed_at: null, analysed_day: null, run_id: null, attempt: null, ...o });
const TODAY = { analysed_at: at('08:41:09'), analysed_day: '2026-11-09', attempt: { status: 'ok', at: at('08:41:09'), note: null } };
const HELD = [
  holding('FXAIX', 'Synthetic 500 Index Fund', 'fund', 59.2, 'today', { ...TODAY, status_line: 'Analysed today', verdict: 'add', verdict_line: 'Add on schedule. It is the core of the book and still under its band.', run_id: 412 }),
  holding('FTEC', 'Synthetic Technology Index ETF', 'fund', 20.8, 'older', { status_line: 'Analysed Thu Nov 5. It is in tonight’s pass.', verdict: 'hold', verdict_line: 'Hold. It sits at the top of its band, so new money goes elsewhere.', analysed_at: '2026-11-05T06:12:00+00:00', analysed_day: '2026-11-05', run_id: 4, attempt: { status: 'ok', at: '2026-11-05T06:12:00+00:00', note: null } }),
  holding('VXUS', 'Synthetic International Index ETF', 'fund', 13.7, 'today', { ...TODAY, status_line: 'Analysed today', verdict: 'add', verdict_line: 'Add. It is the furthest under its target.', analysed_at: at('08:44:30'), run_id: 413, attempt: { status: 'ok', at: at('08:44:30'), note: null } }),
  holding('BND', 'Synthetic Total Bond ETF', 'fund', 4.9, 'failed', { status_line: 'Last try failed at 3:12 AM: the model call timed out. No earlier analysis.', attempt: { status: 'timeout', at: at('08:12:00'), note: 'The model call timed out.' } }),
  holding('ACME', 'Acme Launch Corp', 'stock', 0.5, 'older', { status_line: 'Analysed Wed Nov 4. It is in tonight’s pass.', verdict: 'avoid', verdict_line: 'Stay out of more. One scrubbed launch resets the timeline and the price.', analysed_at: '2026-11-04T06:07:00+00:00', analysed_day: '2026-11-04', run_id: 3, attempt: { status: 'ok', at: '2026-11-04T06:07:00+00:00', note: null } }),
];

// ---------- the analyses behind them ----------
const SOURCE = (title, date) => ({ title: `${title} (synthetic)`, url: 'https://example.com/synthetic/fund-facts', date });
const NEW_DOSSIERS = [
  {
    symbol: 'FXAIX',
    run_id: 412,
    created_at: at('08:41:09'),
    dossier: {
      symbol: 'FXAIX',
      as_of: '2026-11-09',
      what_it_is: 'A fund that owns the 500 largest US companies in proportion to their size. It makes money when US business as a whole does.',
      thesis: 'It is the cheapest way to own US large companies and it is the core the plan is built around.',
      changes_since_last: null,
      valuation_range: { low: 17, high: 24, now: 22, unit: 'multiple', basis: 'Price against next year’s earnings' },
      valuation_note: 'Fair to slightly rich. Earnings growth is carrying the price, not hope.',
      risks: ['A third of the fund sits in ten companies.', 'A US recession hits every holding at once.'],
      bear_case: 'It is concentrated in a handful of very large technology companies, and it has not been cheap for years.',
      fit: 'It is 59% of the book against a 60% target, so the next deposit still goes here. It suits a moderate risk level.',
      verdict: 'add',
      verdict_line: 'Add on schedule. It is the core of the book and still under its band.',
      what_would_change: 'It drifts more than 5 points over its target.\nThe plan changes its core fund.',
      sources: [SOURCE('Fund fact sheet', '2026-10-31')],
    },
  },
  {
    symbol: 'VXUS',
    run_id: 413,
    created_at: at('08:44:30'),
    dossier: {
      symbol: 'VXUS',
      as_of: '2026-11-09',
      what_it_is: 'A fund that owns companies outside the United States, in developed and emerging markets.',
      thesis: 'It spreads the book beyond one country and one currency, at a lower price than US stocks.',
      changes_since_last: null,
      valuation_range: { low: 11, high: 16, now: 13, unit: 'multiple', basis: 'Price against next year’s earnings' },
      valuation_note: 'Cheap against its own history and against US stocks.',
      risks: ['A stronger dollar cuts returns for a US holder.', 'Emerging markets can fall hard and stay down.'],
      bear_case: 'It has trailed US stocks for a decade and nothing forces that to end.',
      fit: 'It is 13.7% of the book against a 15% target: the furthest under, so it is first in line for new money.',
      verdict: 'add',
      verdict_line: 'Add. It is the furthest under its target.',
      what_would_change: 'It reaches its target weight.\nThe plan drops its international sleeve.',
      sources: [SOURCE('Fund fact sheet', '2026-10-31')],
    },
  },
];
const EXTRA = {
  FTEC: { as_of: '2026-11-05', what_it_is: 'A fund that owns US technology companies.', valuation_note: 'Rich against its own history, held up by fast earnings growth.', risks: ['Two companies make up over a third of the fund.', 'Technology falls further than the market in a sell-off.'], fit: 'It is at the top of its band, so new money goes elsewhere. The tilt is a choice, not the plan’s core.', verdict_line: 'Hold. It sits at the top of its band, so new money goes elsewhere.' },
  ACME: { as_of: '2026-11-04', what_it_is: 'A small company that builds launch vehicles and sells rides to orbit.', valuation_note: 'Priced for a launch schedule it has not yet kept.', risks: ['A failed launch grounds the fleet for months.', 'It needs to raise cash again within a year.'], fit: 'It is a single stock outside the plan, half a percent of the book and inside the single-stock band.', verdict_line: 'Stay out of more. One scrubbed launch resets the timeline and the price.' },
};

function dossierFixtures() {
  const list = read('agents.dossiers').filter((d) => !NEW_DOSSIERS.some((n) => n.symbol === d.symbol));
  const merged = [...list.map((d) => (EXTRA[d.symbol] ? { ...d, dossier: { ...d.dossier, ...EXTRA[d.symbol] } } : d)), ...NEW_DOSSIERS];
  const out = { 'agents.dossiers': merged };
  merged.forEach((d) => {
    out[`agents.dossiers.${d.symbol}`] = d;
  });
  return out;
}

const holdings = {
  as_of: '2026-11-09',
  held: 5,
  analysed: 4,
  today: 2,
  failed: 1,
  waiting: 0,
  running: null,
  fresh_at: at('08:44:30'),
  line: '4 of 5 holdings analysed, 2 of them today. 1 failed last night.',
  pass: { status: 'ok', at: at('08:55:30'), note: 'Analysed FXAIX and VXUS. BND failed: the model call timed out.', next: '2026-11-09T23:05:00-05:00' },
  rows: HELD,
};
const holdingsFresh = {
  as_of: '2026-11-09',
  held: 5,
  analysed: 0,
  today: 0,
  failed: 0,
  waiting: 0,
  running: null,
  fresh_at: null,
  line: 'No holding has been analysed yet. The first pass runs tonight from 11:05 PM.',
  pass: { status: 'never', at: null, note: null, next: '2026-11-09T23:05:00-05:00' },
  rows: HELD.map((h) => holding(h.symbol, h.name, h.kind, h.weight_pct, 'none', { status_line: 'Not analysed yet. It is in tonight’s pass.' })),
};

// ---------- buying opportunities ----------
const ZONE = "Today's close down to one monthly swing lower. Split the buy in two.";
const opp = (rank, symbol, name, kind, o) => ({ rank, symbol, name, kind, held: false, weight_pct: 0, sources: ['scanner'], source_label: 'Discount scanner', stance: 'screen', stance_label: 'Cheap by the numbers, no written case yet', why_now: '', facts: [], entry: null, size: null, wrong_if: '', invalid_below: null, case: null, decision_id: null, next_earnings: null, as_of: '2026-11-09', score: 50, ...o });
const OPPS = [
  opp(1, 'QUAL', 'Synthetic Quality Factor ETF', 'fund', {
    sources: ['scanner', 'case'],
    source_label: 'Discount scanner + written case',
    stance: 'buy',
    stance_label: 'Worth buying now',
    group: 'buy',
    group_label: 'Worth buying',
    why_now: 'A broad sell-off pulled quality names down with everything else; earnings estimates for the fund’s top holdings have not moved. Cheap for a reason that looks temporary.',
    facts: ['12.1% under its 52-week high', 'First close 10% under the high on Nov 6', 'Cheaper than 81% of its last 5 years', '2.4% above its 200-day average'],
    entry: { low: 171.2, high: 180.4, price: 180.4, in_zone: true, basis: ZONE },
    size: { usd: 100, shares: 0.55, pct_points: 0.6, room_usd: 400, funding: 'cash', limited_by: 'free cash', note: 'A starter slice, cut to the cash that is free today.', blocked: null },
    wrong_if: 'If the sell-off is the start of an earnings downturn, quality falls less but still falls. Off below $162.00, two monthly swings under today.',
    invalid_below: 162,
    case: { verdict: 'buy', confidence: 0.62, horizon_days: 120, written_at: at('07:12:00') },
    score: 78,
    queued: false,
    not_queued: null,
    price_as_of: '2026-11-09',
    price_source: 'quote',
    price_behind: false,
    analysis_as_of: '2026-11-06',
    since_analysis_pct: -1.8,
    as_of_words: 'Priced at Mon Nov 9, 11:40 AM ET. The written case is from Fri Nov 6; the price is 1.8% lower since.',
  }),
  opp(2, 'NOVA', 'Nova Semiconductor Corp', 'stock', {
    sources: ['scout'],
    source_label: 'Scout idea',
    stance: 'watch',
    stance_label: 'Watch: Skeptic disagreed',
    group: 'could',
    group_label: 'Could become a buy',
    why_now: 'Scout: order backlog doubled year over year while the price sits 18% under its high after a guidance cut the company tied to one customer.',
    facts: ['18.3% under its 52-week high', 'Scout confidence 55%'],
    entry: { low: 41, high: 45.5, price: 45.5, in_zone: true, basis: ZONE },
    size: { usd: 0, shares: 0, pct_points: 0, room_usd: 820, funding: 'wait', limited_by: 'Skeptic', note: 'Nothing to buy until the Skeptic’s point is answered.', blocked: null },
    wrong_if: 'Skeptic: one customer is 40% of sales, so the guidance cut may repeat. Off below $36.90.',
    invalid_below: 36.9,
    decision_id: 'd_20261109_0007',
    queued: true,
    not_queued: null,
    as_of: '2026-11-06',
    price_as_of: '2026-11-06',
    price_source: 'close',
    price_behind: true,
    analysis_as_of: '2026-11-05',
    since_analysis_pct: 2.3,
    as_of_words: 'Priced at the Fri Nov 6 close. Scout’s idea is from Thu Nov 5; the price is 2.3% higher since. The desk has no newer price for it than Fri Nov 6: live quotes cover what you hold, and other closes arrive the same evening, mutual funds later.',
    next_earnings: { date: '2026-11-18', days: 9 },
    score: 64,
  }),
  opp(4, 'ACME', 'Acme Launch Corp', 'stock', {
    held: true,
    weight_pct: 0.5,
    sources: ['scanner', 'case'],
    source_label: 'Discount scanner + written case',
    stance: 'watch',
    stance_label: 'Watch: a loss sale is planned',
    group: 'not_now',
    group_label: 'Not now',
    why_now: 'Fell 6.8% on a scrubbed launch. The case has not changed, but buying now would void the planned loss sale.',
    facts: ['31.0% under its 52-week high', 'Fell 6.8% on Nov 6, a 2.3-sigma day'],
    entry: { low: 24.1, high: 28.9, price: 28.9, in_zone: true, basis: ZONE },
    size: { usd: 0, shares: 0, pct_points: 0, room_usd: 0, funding: 'wait', limited_by: 'loss-sale window', note: 'Nothing to add while the loss sale is planned.', blocked: 'A buy in any account would void the planned loss sale.' },
    wrong_if: 'Another scrubbed launch would keep pressing the price. Off below $19.30.',
    invalid_below: 19.3,
    case: { verdict: 'wait', confidence: 0.58, horizon_days: 60, written_at: at('07:20:00') },
    score: 51,
    queued: false,
    not_queued: null,
    as_of_words: 'Priced at Mon Nov 9, 11:40 AM ET. The written case is from the same day.',
  }),
  opp(3, 'VXUS', 'Synthetic International Index ETF', 'fund', {
    held: true,
    weight_pct: 13.7,
    sources: ['standing'],
    source_label: 'On sale by the numbers',
    group: 'could',
    group_label: 'Could become a buy',
    why_now: '10.4% under its 52-week high, which is 2.1 of its usual monthly swings, and still above its 200-day average.',
    facts: ['10.4% under its 52-week high', '1.1% above its 200-day average'],
    entry: { low: 58.2, high: 61.3, price: 61.3, in_zone: true, basis: ZONE },
    size: { usd: 42, shares: 0.69, pct_points: 0.3, room_usd: 800, funding: 'cash', limited_by: 'free cash', note: 'What is left of free cash after the row above; the rest waits for the next deposit.', blocked: null },
    wrong_if: 'No written case yet, so nobody has checked why it fell. Off below $55.10, two monthly swings under today.',
    invalid_below: 55.1,
    score: 44,
    queued: false,
    not_queued: null,
    as_of_words: 'Priced at Mon Nov 9, 11:40 AM ET. The numbers here are worked out from that price.',
  }),
];
const PROFILE = { source: 'default_moderate', label: 'Moderate', single_stock_max_pct: 5, speculative_max_pct: 5, note: 'No risk check on file yet, so sizes use the Moderate band: 5% a single stock, 5% for all single stocks together.' };
const METHOD = 'Ranked by how unusual the discount is for that name, lifted by a written buy case or a Scout idea. It is a sort, not a forecast.';
const opportunities = {
  as_of: '2026-11-09',
  built_at: at('15:05:00'),
  advice_only: true,
  freshness: { scanner_as_of: '2026-11-09', last_case_at: at('07:20:00'), last_scout_at: at('08:40:00'), night_run_at: at('08:41:00'), night_status: 'ok', note: '1 of these has no written case yet. The numbers stand on their own; the cases are written overnight.' },
  headline: '1 worth buying now. 2 could become a buy, 1 not for now. Top: QUAL, 12% under its high.',
  counts: { total: 4, buy: 1, watch: 2, screen: 1, held: 2, outside: 2, with_case: 2, could: 2, not_now: 1 },
  note: null,
  profile: PROFILE,
  cash: { free_usd: 142, account: 'individual', next_deposit_usd: 500, next_deposit_on: '2026-11-18', note: 'Sizes come from free cash first, then the next deposit. Never from margin.' },
  method: METHOD,
  rows: OPPS,
  prices: { day: '2026-11-09', words: 'Prices run to Mon Nov 9. NOVA is still at an earlier close: live quotes cover what you hold, and other closes arrive the same evening, mutual funds later.', older: [{ symbol: 'NOVA', price_as_of: '2026-11-06', held: false }] },
  passed: [{ symbol: 'BND', name: 'Synthetic Total Bond ETF', reason: 'Written case says avoid: cheap for a reason that looks lasting.' }],
};
const DEBIT = 'Pay the margin debit first: $1,500 is open, so no buy goes to the queue.';
const opportunitiesDebit = {
  ...opportunities,
  headline: '2 worth buying once the margin debit is paid, 2 to watch. Top: QUAL, 12% under its high.',
  counts: { ...opportunities.counts, buy: 2, watch: 1, could: 1 },
  cash: { ...opportunities.cash, free_usd: 0, margin_debit_usd: 1500, note: 'A margin debit of $1,500 is open. It is paid before anything here is bought.' },
  rows: OPPS.map((r) => (r.symbol === 'QUAL' || r.symbol === 'NOVA' ? { ...r, stance: 'buy', stance_label: 'Worth buying once cash is free', group: 'buy', group_label: 'Worth buying', queued: false, not_queued: DEBIT, size: { ...r.size, usd: 0, shares: 0, funding: 'wait', note: 'Nothing to buy until the margin debit is paid.' } } : r)),
};
const opportunitiesFresh = {
  as_of: null,
  built_at: at('15:05:00'),
  advice_only: true,
  freshness: { scanner_as_of: null, last_case_at: null, last_scout_at: null, night_run_at: null, night_status: null, note: null },
  headline: 'No list yet: the engine has not run.',
  counts: { total: 0, buy: 0, watch: 0, screen: 0, held: 0, outside: 0, with_case: 0 },
  note: 'No list yet: the engine has not run. It fills in after the next engine run.',
  profile: PROFILE,
  cash: { free_usd: null, account: null, next_deposit_usd: null, next_deposit_on: null, note: 'Sizes come from free cash first, then the next deposit. Never from margin.' },
  method: METHOD,
  rows: [],
  passed: [],
};

// ---------- heads-up notes ----------
const note = (id, origin, title, thesis, subject) => ({ id, created_at: at('13:35:00'), updated_at: at('13:35:00'), origin, run_id: 'r-seed-9', kind: 'memo', title, symbol: null, thesis, subject, as_of: '2026-11-09', valid: null, expires_at: null, status: 'logged', status_reason: 'A heads-up that needs no decision, so it is kept in the journal.', replaced_by: null });
const notes = {
  count: 2,
  days: 7,
  items: [
    note('d_20261109133500_aa01', 'plan_keeper', 'Margin is back to zero', 'The debit was paid off by the last deposit, so nothing accrues this month.', 'margin'),
    note('d_20261109133500_aa02', 'risk', 'One fund makes up most of the book', 'FXAIX is 59% of the portfolio, which is the plan. Nothing to do.', 'concentration'),
  ],
};

// ---------- cleared by the queue rule ----------
const gone = (id, origin, kind, title, symbol, reason, check, when) => ({ id, created_at: at('05:10:00'), updated_at: at(when), origin, run_id: 'r-seed-7', kind, title, symbol, status: 'expired', status_reason: reason, decided_at: at(when), check, cleared_at: at(when) });
const cleared = {
  count: 2,
  days: 2,
  items: [
    gone('d_20261109051000_cc01', 'tax', 'sell', 'Sell ACME to harvest the loss', 'ACME', 'Your ACME plan already times this sale for Nov 13, so a second proposal would double it.', 'plan', '13:10:00'),
    gone('d_20261109051000_cc02', 'risk', 'memo', 'Hold off on new margin', null, 'The Plan keeper already has a margin hold-off waiting on you, so this one was a repeat.', 'plan', '08:40:00'),
  ],
};
const clearedNone = { count: 0, days: 2, items: [] };

// ---------- the night's run ----------
const step = (id, title, state, o = {}) => ({ id, job: id, title, state, detail: null, ready: null, started_at: null, finished_at: null, ...o });
const overnight = {
  night: '2026-11-08',
  state: 'done',
  started_at: at('04:30:02'),
  finished_at: at('08:55:30'),
  build: '716e203',
  restarts: 0,
  starts: '23:30',
  ends: '06:30',
  summary: '4 of 5 steps done. Not done: Write the debrief.',
  steps: [
    step('mirror', 'Mirror', 'ok', { started_at: at('04:30:02'), finished_at: at('04:30:40') }),
    step('engine-daily', 'Engine daily', 'skipped', { detail: 'It already ran on the version that is live.', finished_at: at('04:31:00') }),
    step('strategies', 'Queue the strategy library', 'ok', { ready: '24 strategies tested, 5 held up out of sample', started_at: at('04:31:02'), finished_at: at('04:33:10') }),
    step('agents-run-research', 'Analyse every holding', 'ok', { ready: '4 holdings analysed', started_at: at('07:40:00'), finished_at: at('08:55:30') }),
    step('agents-run-debrief', 'Write the debrief', 'failed', { detail: 'The model call timed out.', started_at: at('08:55:31'), finished_at: at('09:05:31') }),
  ],
  ready: ['24 strategies tested, 5 held up out of sample', '4 holdings analysed', '4 buying opportunities'],
};
const overnightIdle = { ...overnight, night: '2026-11-09', state: 'idle', started_at: null, finished_at: null, build: null, summary: 'Tonight’s run starts at 23:30.', steps: overnight.steps.map((s) => step(s.id, s.title, 'waiting')), ready: [] };

export function morningFixtures() {
  return { 'lab.library': library(tested), 'lab.library.big': library(big), 'lab.library.fresh': library(waiting), 'lab.library.never': library(waiting), 'agents.holdings': holdings, 'agents.holdings.fresh': holdingsFresh, 'agents.holdings.never': holdingsFresh, opportunities, 'opportunities.evening': opportunitiesDebit, 'opportunities.fresh': opportunitiesFresh, 'opportunities.never': opportunitiesFresh, overnight, 'overnight.fresh': overnightIdle, 'overnight.never': overnightIdle, 'decisions.cleared': cleared, 'decisions.cleared.fresh': clearedNone, 'decisions.cleared.never': clearedNone, 'decisions.cleared.empty': clearedNone, 'decisions.notes': notes, 'decisions.notes.fresh': { count: 0, days: 7, items: [] }, 'decisions.notes.never': { count: 0, days: 7, items: [] }, 'decisions.notes.empty': { count: 0, days: 7, items: [] }, ...dossierFixtures() };
}

// ---------- write ----------
for (const [name, body] of Object.entries(morningFixtures())) write(name, body);

// ---------- what a finished job did ----------
const jobs = read('jobs');
const backfill = jobs.jobs.find((j) => j.name === 'engine-backfill');
if (backfill?.last_run) {
  backfill.last_run.did = 'Asked Tiingo for 2 names. FXAIX and FTEC answered with nothing new for 2026-11-06.';
  backfill.last_run.said = backfill.last_run.did;
}
const paper = jobs.jobs.find((j) => j.name === 'engine-paper');
if (paper?.last_run) {
  paper.last_run.did = null;
  paper.last_run.said = '{"filled": 0, "skipped": 4}';
}
write('jobs', jobs);

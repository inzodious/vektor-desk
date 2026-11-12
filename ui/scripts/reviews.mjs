const round = (v, d = 2) => Math.round(v * 10 ** d) / 10 ** d;
const KEEP = 8;
const FI_NUMBER = 1000000;

const MIXES = [
  { id: 'spy', name: 'S&P 500', kind: 'benchmark', lag: { day: 0.19, week: -0.34, month: 0.62, year: -1.4 } },
  { id: 'safe-mix', name: 'Safe mix', kind: 'mix', lag: { day: 0.12, week: 0.81, month: 0.9, year: 1.9 } },
  { id: 'as-held', name: 'As held', kind: 'mix', lag: { day: 0.02, week: 0.05, month: -0.1, year: 0.3 } },
  { id: 'tech-tilt', name: 'Aggressive tech tilt', kind: 'mix', lag: { day: -0.27, week: -0.92, month: -1.3, year: -3.8 } },
];
const PAPER = [
  { id: 'tech-tilt', name: 'Aggressive tech tilt', kind: 'mix', status: 'paper', move: { day: 0.58, week: 3.01, month: 3.4, year: 7.9 } },
  { id: 'sector-momentum', name: 'Sector momentum', kind: 'strategy', status: 'paper', move: { day: -0.22, week: 1.12, month: 0.4, year: 2.1 } },
  { id: 'filings-lane', name: 'Filings lane', kind: 'lane', status: 'paper', move: { day: 0.05, week: -0.61, month: -0.9, year: -0.9 } },
];
const DEBRIEF = {
  day: {
    headline: 'Up $53 on a quiet Friday, a touch behind the S&P 500.',
    what_happened: 'The portfolio gained 0.31% with no deposits or trades. FXAIX did nearly all of the lifting; FTEC and VXUS gave a little back.',
    why: 'Large US stocks rose while tech and international slipped, and FXAIX is 59% of the portfolio, so its move set the day.',
    against_decisions: 'Friday’s deposit route into BND is approved and waiting on the deposit to settle.',
    watch: ['ACME reports after the close on Tuesday.', 'VXUS is the largest drift at −1.3 pts, still inside the 5 pt band.'],
    next_steps: [
      { text: 'Place the approved $25 BND order once the deposit settles.', symbol: 'BND' },
      { text: 'Leave ACME alone until earnings are out.', symbol: 'ACME' },
    ],
  },
  week: {
    headline: 'Up $933 for the week: $600 was your deposits, $333 the market.',
    what_happened: 'A 2.09% time-weighted week. Monday’s deposits went in on plan across both accounts, then the market added $333.',
    why: 'FXAIX carried the week (+4.7%). VXUS fell 2.9% and FTEC 0.7%, which is why the tech-tilted mix trailed you.',
    against_decisions: 'The risk desk’s August hold-off on ACME scored +$230 at 90 days. The scout’s ACME buy from the same week is −$89.',
    watch: ['The worst day was Tuesday at −0.52%, well inside band 4.', 'A second weak week for VXUS would bring its drift near the band.'],
    next_steps: [
      { text: 'Route the next deposit toward VXUS to close its drift.', symbol: 'VXUS' },
      { text: 'Review the dismissed BND rebalance; the reason still stands.', symbol: 'BND' },
      { text: 'Check the paper race on Friday; the tech tilt leads by 0.9 pts.', symbol: null },
    ],
  },
  year: {
    headline: '2026 so far: up $6,776, with most of it from deposits.',
    what_happened: 'A 4.19% time-weighted year to date. Steady monthly deposits did most of the dollar growth.',
    why: 'US large caps led. The international and bond sleeves lagged, as the plan expects in a year like this.',
    against_decisions: 'Deposit routes placed on schedule; one rebalance dismissed with a reason.',
    watch: ['December is tax-loss season; the tax desk reviews lots from Dec 1.'],
    next_steps: [{ text: 'Keep deposits on the plan through year end.', symbol: null }],
  },
};

const REWRITE_LATE = { state: 'late', due_at: '2026-11-10T06:40:00+00:00', words: 'Written before the final numbers. The rewrite is running late; the next try is tomorrow at 1:40 AM.' };

// ---------- synthetic fill for what the demo desk lacks ----------
function fill(review, { debrief = false, stale = false } = {}) {
  if (!review?.pack) return review;
  const pack = { ...review.pack };
  delete pack.numbers;
  const v = pack.value;
  const kind = pack.kind;
  if (!(pack.vs || []).length) {
    pack.vs = MIXES.map((m) => {
      const ret = round(v.change_pct - m.lag[kind], 4);
      const end = round(v.start * (1 + ret / 100) + v.net_flows);
      return { id: m.id, name: m.name, kind: m.kind, return_pct: ret, excess_pts: round(v.change_pct - ret, 4), value_end: end, diff_usd: round(v.end - end) };
    });
  }
  if (!(pack.paper || []).length) pack.paper = PAPER.map((p) => ({ id: p.id, name: p.name, kind: p.kind, status: p.status, return_pct: p.move[kind], value_end: round(1000 * (1 + p.move[kind] / 100)) }));
  if (!pack.fi) pack.fi = { fi_number: FI_NUMBER, progress_start_pct: round((v.start / FI_NUMBER) * 100, 3), progress_end_pct: round((v.end / FI_NUMBER) * 100, 3), change_pts: round(((v.end - v.start) / FI_NUMBER) * 100, 3) };
  if (!(pack.events || []).length && kind !== 'day') {
    pack.events = [
      { date: pack.as_of, type: 'discount', symbol: 'ACME', detail: 'First close 20% under its 52-week high' },
      { date: pack.start, type: 'filing', symbol: 'ACME', detail: '8-K: new launch contract, scored +1' },
    ];
  }
  if (pack.risk && !(pack.risk.convictions || []).length) pack.risk = { ...pack.risk, convictions: [{ symbol: 'ACME', weight_pct: 0.46, band_min_pct: 0, band_max_pct: 10, status: 'inside' }] };
  const words = debrief ? DEBRIEF[kind] : null;
  return {
    ...review,
    computed_at: `${pack.as_of}T22:36:00+00:00`,
    pack,
    debrief: words ? { ...words, numbers_cited: ['change_usd', 'change_pct', 'vs.spy.pts'], model: 'synthetic', written_at: `${pack.as_of}T22:52:00+00:00`, pack_digest: review.digest, stale, rewrite: stale ? REWRITE_LATE : null } : null,
  };
}

// ---------- reviews: latest of each kind, one step back, first run ----------
export function reviewsFixtures(index, got) {
  const kinds = Object.fromEntries(Object.entries(index.kinds).map(([k, rows]) => [k, rows.slice(0, KEEP).map((r, i) => ({ ...r, has_debrief: i === 0 && Boolean(DEBRIEF[k]) }))]));
  const out = {
    'engine.reviews.index': { ...index, kinds },
    'engine.reviews.index.fresh': { as_of: null, kinds: { day: [], week: [], month: [], year: [] }, note: 'No reviews yet. The first one runs after tonight’s numbers.' },
    'engine.reviews.fresh': { kind: 'day', start: null, end: null, as_of: null, closed: false, final: false, computed_at: null, digest: null, pack: null, debrief: null, note: 'No reviews yet. The first one runs after tonight’s numbers.' },
    'engine.reviews.day': fill(got.day, { debrief: true }),
    'engine.reviews.week': fill(got.week, { debrief: true }),
    'engine.reviews.month': fill(got.month),
    'engine.reviews.year': fill(got.year, { debrief: true, stale: true }),
  };
  if (got.dayBack) out[`engine.reviews.day.${got.dayBack.end}`] = fill(got.dayBack);
  if (got.weekBack) out[`engine.reviews.week.${got.weekBack.end}`] = fill(got.weekBack);
  return out;
}

export async function readReviews(get) {
  const index = await get('/api/engine/reviews/index');
  const one = (kind, row) => get(`/api/engine/reviews?kind=${kind}${row ? `&end=${row.end}` : ''}`);
  return {
    index,
    got: {
      day: await one('day'),
      week: await one('week'),
      month: await one('month'),
      year: await one('year'),
      dayBack: index.kinds.day[1] ? await one('day', index.kinds.day[1]) : null,
      weekBack: index.kinds.week[1] ? await one('week', index.kinds.week[1]) : null,
    },
  };
}

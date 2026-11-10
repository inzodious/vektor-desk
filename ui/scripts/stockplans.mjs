const DAYS = 14;
const DESK = { run_id: 'run_demo_plans_1', model: 'synthetic' };
const SUMMARY = {
  ACME: 'Tightened the trim rule ahead of earnings and added a conditional trim.',
  VXUS: 'First draft: a satellite with a deposit-only add rule.',
};

const ACME = {
  role: 'conviction',
  thesis: 'Launch cadence doubles in 2027 and the backlog covers three years of revenue. Small on purpose: it earns more room only after two clean quarters.',
  weight_band: { min_pct: 0, max_pct: 5 },
  add_rule: { zone_low: 1.92, zone_high: 2.57, max_per_month_usd: 50, deposits_only: true, note: 'Only from new deposits, one buy a month.' },
  trim_rule: { above_pct: 5, to_pct: 3, zone_low: 3.87, zone_high: 4.52, note: 'Trim back to 3% if it runs past the band.' },
  exit_conditions: ['Two straight quarters of missed launches', 'A dilutive raise under $2.50'],
  tax_notes: 'The whole position sits at a loss. Harvesting part in December offsets gains; no rebuy for 31 days.',
  catalysts: [
    { text: 'Q3 earnings', date: '2026-11-12' },
    { text: 'First heavy-lift flight', date: null },
  ],
  next_review: '2026-11-13',
  steps: [
    { id: 'margin-repay', kind: 'repay', due: '2026-11-18', note: 'The 11-18 deposit pays off the margin debit.' },
    { id: 'harvest-2026', kind: 'harvest', due: '2026-12-07', until: '2026-12-15', shares: 10, account: 'Individual', lots: 'highest_cost', no_buy_days: 31, note: 'Pick Specific Shares at the broker and choose the highest-cost lots.' },
    { kind: 'review', due: '2026-11-13', note: 'Read the earnings call before changing anything.' },
    { kind: 'hold', text: 'No new buys on margin', when: 'Always' },
  ],
};
const ACME_DRAFT = {
  ...ACME,
  trim_rule: { ...ACME.trim_rule, above_pct: 4, to_pct: 2.5, note: 'Earnings risk is high this month; trim sooner if it spikes.' },
  next_review: '2026-11-20',
  steps: [...ACME.steps, { kind: 'trim', when: 'If it closes above $4.50', shares: 5, note: 'Takes the weight back inside the band.' }],
};
const FXAIX = {
  role: 'core',
  thesis: 'The base of the portfolio. Low cost, broad, bought on every deposit.',
  weight_band: { min_pct: 50, max_pct: 65 },
  add_rule: { zone_low: null, zone_high: null, max_per_month_usd: null, deposits_only: true, note: 'Every deposit routes here first.' },
  trim_rule: null,
  exit_conditions: [],
  tax_notes: null,
  catalysts: [],
  next_review: '2027-01-15',
  steps: [{ kind: 'add', when: 'Each deposit', amount_usd: 300, note: 'Per the deposit route.' }],
};
const VXUS = {
  role: 'satellite',
  thesis: 'International diversifier. It lags in US-led years and that is what it is for.',
  weight_band: { min_pct: 12, max_pct: 18 },
  add_rule: { zone_low: 61, zone_high: 63.5, max_per_month_usd: 100, deposits_only: true, note: 'Route deposits here while it sits under target.' },
  trim_rule: null,
  exit_conditions: [],
  tax_notes: null,
  catalysts: [],
  next_review: '2027-02-01',
  steps: [{ kind: 'add', due: '2026-11-18', amount_usd: 60, note: 'From the 11-18 deposit.' }],
};

// ---------- seed the demo desk when it has no plans ----------
async function put(api, symbol, plan, approve) {
  const res = await fetch(`${api}/api/decisions/plans/${symbol}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(approve ? { plan, approve: true } : { plan }) });
  if (!res.ok) throw new Error(`plan ${symbol} answered ${res.status}`);
}

export async function seedPlans(api, get) {
  const now = await get('/api/decisions/plans');
  if ((now.items || []).length) return;
  await put(api, 'ACME', ACME, true);
  await put(api, 'ACME', ACME_DRAFT, false);
  await put(api, 'FXAIX', FXAIX, true);
  await put(api, 'VXUS', VXUS, false);
}

// ---------- drafts read as the Plan desk's ----------
function asDesk(plan) {
  if (!plan || plan.status !== 'draft' || !SUMMARY[plan.symbol]) return plan;
  const mine = new Set((plan.approved?.steps || []).map((s) => s.id));
  const by = (s) => (s && !mine.has(s.id) ? { ...s, by: 'desk' } : s);
  return { ...plan, author: 'desk', ...DESK, summary: SUMMARY[plan.symbol], steps: plan.steps.map(by), next_step: by(plan.next_step) };
}

export async function readPlans(get) {
  const plans = await get('/api/decisions/plans');
  const one = {};
  for (const p of plans.items) one[p.symbol] = await get(`/api/decisions/plans/${p.symbol}`);
  return { plans, one, steps: await get(`/api/decisions/plan-steps?days=${DAYS}`), facts: await get('/api/engine/planfacts') };
}

export function plansFixtures({ plans, one, steps, facts }) {
  const { items, ...meta } = plans;
  const out = {
    'decisions.plans': { items: items.map(asDesk), ...meta },
    'decisions.plans.fresh': { items: [], ...meta },
    'decisions.plan-steps': steps,
    'decisions.plan-steps.fresh': { items: [], no_buy: {} },
    'engine.planfacts': facts,
  };
  for (const [symbol, body] of Object.entries(one)) {
    const plan = asDesk(body.plan);
    out[`decisions.plans.${symbol}`] = { plan, history: body.history.map((h) => (h.version === plan.version ? { ...h, author: plan.author, run_id: plan.run_id, model: plan.model, summary: plan.summary } : h)) };
  }
  return out;
}

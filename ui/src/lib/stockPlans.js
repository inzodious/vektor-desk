import { dayLabel, parseDay } from './charts.js';
import { px, usd } from './format.js';

export const ROLE = {
  core: { t: 'Core', tone: 'ok', hint: 'The base of the portfolio' },
  conviction: { t: 'Conviction', tone: 'lilac', hint: 'A stock you mean to keep long' },
  satellite: { t: 'Satellite', tone: 'info', hint: 'A smaller tilt around the core' },
  exit: { t: 'Exit', tone: 'watch', hint: 'On its way out, on a schedule' },
};
export const STEP_KIND = { add: 'Buy', trim: 'Trim', hold: 'Hold', review: 'Review', harvest: 'Harvest a loss', sell: 'Sell', repay: 'Repay margin', other: 'Other' };
const STEP_STATUS = {
  upcoming: { t: 'Coming up', tone: '' },
  open: { t: 'Open now', tone: 'info' },
  partial: { t: 'Partly done', tone: 'watch' },
  done: { t: 'Done', tone: 'ok' },
  passed: { t: 'Window passed', tone: 'watch' },
  waiting: { t: 'Waiting on its trigger', tone: '' },
  standing: { t: 'Standing', tone: '' },
};
const STEP_ORDER = ['open', 'partial', 'upcoming', 'waiting', 'standing', 'passed', 'done'];
const DONE_BY = { you: 'you', broker: 'a broker fill', desk: 'the desk' };
const BAND = { inside: { t: 'Inside its band', tone: 'ok' }, above: { t: 'Above its band', tone: 'watch' }, below: { t: 'Below its band', tone: 'info' } };
const PLAN_FIELDS = ['role', 'thesis', 'weight_band', 'add_rule', 'trim_rule', 'exit_conditions', 'tax_notes', 'catalysts', 'next_review'];
const STEP_FIELDS = ['id', 'kind', 'text', 'due', 'until', 'when', 'shares', 'amount_usd', 'account', 'lots', 'no_buy_days', 'note'];
const TRADES = ['add', 'trim', 'harvest', 'sell'];
const SELLS = ['trim', 'harvest', 'sell'];
const DAY = /^\d{4}-\d{2}-\d{2}$/;

const money = (v) => (v == null ? null : v >= 1000 ? usd(v) : `$${px(v)}`);
const pctText = (v) => `${Number(Number(v).toFixed(1))}%`;
const num = (s) => {
  const t = String(s ?? '')
    .replace(/[$,%\s]/g, '')
    .trim();
  if (!t) return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : NaN;
};
const text = (s) => {
  const t = String(s ?? '').trim();
  return t || null;
};
const str = (v) => (v == null ? '' : String(v));

export const roleOf = (role) => ROLE[role] || { t: role || 'No role', tone: '', hint: '' };
export const stepStatus = (step) => STEP_STATUS[step?.status] || { t: step?.status || '', tone: '' };
export const bandWord = (status) => BAND[status] || null;

// ---------- steps ----------
export function stepWhen(step) {
  if (!step) return '';
  if (step.due && step.until && step.until !== step.due) return `${dayLabel(step.due)} to ${dayLabel(step.until)}`;
  if (step.due) return dayLabel(step.due);
  return step.when || 'No date';
}

export function stepStamp(step) {
  if (!step?.due) return null;
  const d = parseDay(step.due);
  return { day: d.getUTCDate(), mon: dayLabel(step.due).split(' ')[0] };
}

export function stepFacts(step, lotMethods = {}) {
  const out = [];
  if (step.shares != null) out.push(step.shares === 'all' ? 'All shares' : `${Number(step.shares)} ${Number(step.shares) === 1 ? 'share' : 'shares'}`);
  if (step.amount_usd != null) out.push(usd(step.amount_usd));
  if (step.account) out.push(`from ${step.account}`);
  if (step.lots) out.push(lotMethods[step.lots] || step.lots);
  if (step.no_buy_days) out.push(`no buys for ${step.no_buy_days} days after`);
  if (step.status === 'partial' && step.filled_shares != null) out.push(`${Number(step.filled_shares)} sold so far`);
  if (step.status === 'done' && step.done_on) out.push(`done ${dayLabel(step.done_on)}${step.done_by ? ` by ${DONE_BY[step.done_by] || step.done_by}` : ''}`);
  if (step.rebuy_on) out.push(`buys reopen ${dayLabel(step.rebuy_on)}`);
  return out;
}

export function sortSteps(steps) {
  const rank = (s) => {
    const i = STEP_ORDER.indexOf(s.status);
    return i < 0 ? STEP_ORDER.length : i;
  };
  return [...(steps || [])].sort((a, b) => rank(a) - rank(b) || str(a.due || '9999').localeCompare(str(b.due || '9999')));
}

const inForce = (plan, step) => plan?.status === 'approved' || (plan?.approved?.steps || []).some((s) => s.id === step.id);

export function canMarkDone(plan, step) {
  return inForce(plan, step) && ['open', 'partial', 'upcoming', 'waiting', 'passed'].includes(step.status);
}

export function canUndo(plan, step) {
  return inForce(plan, step) && step.status === 'done' && step.done_by === 'you';
}

// ---------- weight and price ----------
export function bandOf(plan, fact) {
  const b = plan?.weight_band;
  if (b && b.max_pct != null) return { min: b.min_pct ?? 0, max: b.max_pct, source: 'plan' };
  const c = plan?.conviction;
  if (c && c.band_max_pct != null) return { min: c.band_min_pct ?? 0, max: c.band_max_pct, source: 'conviction' };
  const f = fact?.band;
  if (f && f.max_pct != null) return { min: f.min_pct ?? 0, max: f.max_pct, source: f.source };
  return null;
}

export function weightOf(plan, fact) {
  return plan?.weight_pct ?? fact?.numbers?.weight_pct ?? null;
}

export function weightMeter(plan, fact) {
  const band = bandOf(plan, fact);
  const weight = weightOf(plan, fact);
  if (!band && weight == null) return null;
  const top = Math.max(band?.max ?? 0, weight ?? 0, 1);
  const max = Math.min(100, Math.ceil((top * 1.25) / 5) * 5);
  const at = (v) => Math.max(0, Math.min(100, (v / max) * 100));
  return { max, from: band ? at(band.min) : null, to: band ? at(band.max) : null, mark: weight == null ? null : at(weight), band, weight };
}

export function weightLine(plan, fact) {
  const band = bandOf(plan, fact);
  const weight = weightOf(plan, fact);
  const w = weight == null ? 'Not held' : `${pctText(weight)} of the portfolio`;
  if (!band) return `${w} · no band yet`;
  return `${w} · band ${pctText(band.min)} to ${pctText(band.max)}`;
}

export function zonesOf(plan, fact) {
  const pick = (r) => (r && r.zone_low != null && r.zone_high != null ? { low: r.zone_low, high: r.zone_high } : null);
  if (plan) return { add: pick(plan.add_rule), trim: pick(plan.trim_rule), suggested: false };
  const z = fact?.zones;
  const fromFact = (v) => (v && v.low != null && v.high != null ? { low: v.low, high: v.high } : null);
  return { add: fromFact(z?.add), trim: fromFact(z?.trim), suggested: true };
}

export function ruler(plan, fact) {
  const n = fact?.numbers;
  const price = n?.price;
  if (price == null) return null;
  const { add, trim, suggested } = zonesOf(plan, fact);
  const vals = [price, n.low_52w, n.high_52w, add?.low, add?.high, trim?.low, trim?.high].filter((v) => v != null);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.06, hi * 0.005);
  const min = Math.max(0, lo - pad);
  const max = hi + pad;
  const at = (v) => ((v - min) / (max - min)) * 100;
  const zone = (z) => (z ? { left: at(z.low), width: Math.max(1.5, at(z.high) - at(z.low)), low: z.low, high: z.high } : null);
  const where = add && price >= add.low && price <= add.high ? 'add' : trim && price >= trim.low && price <= trim.high ? 'trim' : add && price < add.low ? 'under' : trim && price > trim.high ? 'over' : 'between';
  return {
    min,
    max,
    suggested,
    price: { left: at(price), value: price },
    low52: n.low_52w != null ? { left: at(n.low_52w), value: n.low_52w } : null,
    high52: n.high_52w != null ? { left: at(n.high_52w), value: n.high_52w } : null,
    add: zone(add),
    trim: zone(trim),
    where,
  };
}

const WHERE = {
  add: { t: 'In the add zone', tone: 'ok' },
  trim: { t: 'In the trim zone', tone: 'watch' },
  under: { t: 'Under the add zone', tone: 'info' },
  over: { t: 'Over the trim zone', tone: 'watch' },
  between: { t: 'Between zones', tone: '' },
};
export const whereWord = (r) => (r && (r.add || r.trim) ? WHERE[r.where] : null);

export function rulerLabel(symbol, r) {
  if (!r) return `${symbol}: no price yet`;
  const parts = [`${symbol} at ${money(r.price.value)}`];
  if (r.add) parts.push(`add zone ${money(r.add.low)} to ${money(r.add.high)}`);
  if (r.trim) parts.push(`trim zone ${money(r.trim.low)} to ${money(r.trim.high)}`);
  if (r.low52 && r.high52) parts.push(`52-week range ${money(r.low52.value)} to ${money(r.high52.value)}`);
  return parts.join(', ');
}

export function rulerKey(r) {
  if (!r) return [];
  const out = [];
  if (r.add) out.push({ id: 'add', label: r.suggested ? 'Suggested add' : 'Add', value: `${money(r.add.low)} to ${money(r.add.high)}` });
  out.push({ id: 'price', label: 'Last close', value: money(r.price.value) });
  if (r.trim) out.push({ id: 'trim', label: r.suggested ? 'Suggested trim' : 'Trim', value: `${money(r.trim.low)} to ${money(r.trim.high)}` });
  if (r.low52 && r.high52) out.push({ id: 'range', label: '52 weeks', value: `${money(r.low52.value)} to ${money(r.high52.value)}` });
  return out;
}

// ---------- rules in words ----------
export function ruleLines(plan) {
  const out = [];
  const a = plan?.add_rule;
  if (a) {
    const bits = [];
    if (a.zone_low != null && a.zone_high != null) bits.push(`between ${money(a.zone_low)} and ${money(a.zone_high)}`);
    if (a.max_per_month_usd != null) bits.push(`up to ${usd(a.max_per_month_usd)} a month`);
    if (a.deposits_only) bits.push('from new deposits only');
    out.push({ id: 'add', label: 'Add', text: bits.length ? `Add ${bits.join(', ')}.` : 'Add when the plan says so.', note: a.note || null });
  }
  const t = plan?.trim_rule;
  if (t) {
    const bits = [];
    if (t.above_pct != null) bits.push(`above ${pctText(t.above_pct)} of the portfolio${t.to_pct != null ? `, back to ${pctText(t.to_pct)}` : ''}`);
    if (t.zone_low != null && t.zone_high != null) bits.push(`between ${money(t.zone_low)} and ${money(t.zone_high)}`);
    out.push({ id: 'trim', label: 'Trim', text: bits.length ? `Trim ${bits.join(', or ')}.` : 'Trim when the plan says so.', note: t.note || null });
  }
  return out;
}

// ---------- draft and versions ----------
export function versionChip(plan) {
  if (!plan) return null;
  if (plan.status === 'approved') return { t: `Approved v${plan.version}`, tone: 'ok' };
  return { t: plan.author === 'desk' ? `Draft v${plan.version} from the Plan desk` : `Your draft v${plan.version}`, tone: 'watch' };
}

export function planChanges(plan) {
  const base = plan?.approved;
  if (!plan || plan.status !== 'draft' || !base) return [];
  const WORD = { role: 'Role', thesis: 'Thesis', weight_band: 'Weight band', add_rule: 'Add rule', trim_rule: 'Trim rule', exit_conditions: 'Exit conditions', tax_notes: 'Tax notes', catalysts: 'Catalysts', next_review: 'Next review' };
  const out = PLAN_FIELDS.filter((k) => JSON.stringify(plan[k] ?? null) !== JSON.stringify(base[k] ?? null)).map((k) => WORD[k]);
  const before = new Set((base.steps || []).map((s) => s.id));
  const after = new Set((plan.steps || []).map((s) => s.id));
  const added = [...after].filter((id) => !before.has(id)).length;
  const gone = [...before].filter((id) => !after.has(id)).length;
  if (added) out.push(`${added} new ${added === 1 ? 'step' : 'steps'}`);
  if (gone) out.push(`${gone} ${gone === 1 ? 'step' : 'steps'} dropped`);
  return out;
}

export function draftLine(plan) {
  if (!plan || plan.status !== 'draft') return null;
  return plan.approved ? `v${plan.approved.version} stays in force until you approve this one.` : 'Nothing is in force until you approve it.';
}

// ---------- cards ----------
export function planCards(plans, facts) {
  const rows = facts?.rows || [];
  const byFact = new Map(rows.map((r) => [r.symbol, r]));
  const items = plans?.items || [];
  const cards = items.map((plan) => ({ symbol: plan.symbol, plan, fact: byFact.get(plan.symbol) || null }));
  const key = (c) => [c.plan.status === 'draft' ? 0 : 1, c.plan.next_step?.due || '9999', -(weightOf(c.plan, c.fact) || 0)];
  cards.sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    return ka[0] - kb[0] || ka[1].localeCompare(kb[1]) || ka[2] - kb[2];
  });
  const taken = new Set(items.map((p) => p.symbol));
  const bare = rows
    .filter((r) => r.held && !taken.has(r.symbol))
    .sort((a, b) => (b.numbers?.weight_pct || 0) - (a.numbers?.weight_pct || 0))
    .map((fact) => ({ symbol: fact.symbol, plan: null, fact }));
  return { cards, bare };
}

export function plansHead(plans, facts) {
  const { cards, bare } = planCards(plans, facts);
  const drafts = cards.filter((c) => c.plan.status === 'draft').length;
  const approved = cards.length - drafts;
  if (!cards.length) return { big: 'No plans yet', sub: bare.length ? `${bare.length} ${bare.length === 1 ? 'holding' : 'holdings'} waiting for one` : 'The Plan desk drafts them after its next run' };
  const big = `${cards.length} ${cards.length === 1 ? 'plan' : 'plans'}`;
  const bits = [];
  if (approved) bits.push(`${approved} approved`);
  if (drafts) bits.push(`${drafts} ${drafts === 1 ? 'draft waits' : 'drafts wait'} on you`);
  if (bare.length) bits.push(`${bare.length} without a plan`);
  return { big, sub: bits.join(' · ') };
}

// ---------- what goes back to the desk ----------
export function cleanStep(step) {
  const out = {};
  STEP_FIELDS.forEach((k) => {
    if (step[k] != null && step[k] !== '') out[k] = step[k];
  });
  return out;
}

export function editable(plan) {
  const out = {};
  PLAN_FIELDS.forEach((k) => {
    out[k] = plan?.[k] ?? (k === 'exit_conditions' || k === 'catalysts' ? [] : null);
  });
  out.steps = (plan?.steps || []).map(cleanStep);
  return out;
}

export function withStep(plan, step) {
  const body = editable(plan);
  return { ...body, steps: [...body.steps, step] };
}

export function withoutStep(plan, id) {
  const body = editable(plan);
  return { ...body, steps: body.steps.filter((s) => s.id !== id) };
}

export const approvesOnSave = (plan) => plan?.status === 'approved';

// ---------- plan form ----------
export function startPlan(plan, fact) {
  const a = plan?.add_rule;
  const t = plan?.trim_rule;
  const z = fact?.zones;
  const band = bandOf(plan, fact);
  const round = (v) => (v == null ? '' : String(Number(Number(v).toFixed(2))));
  return {
    role: plan?.role || (fact?.kind === 'stock' ? 'satellite' : 'core'),
    thesis: plan?.thesis || '',
    min: band ? str(band.min) : '',
    max: band ? str(band.max) : '',
    addLow: plan ? str(a?.zone_low) : round(z?.add?.low),
    addHigh: plan ? str(a?.zone_high) : round(z?.add?.high),
    addMax: str(a?.max_per_month_usd),
    depositsOnly: a ? Boolean(a.deposits_only) : true,
    addNote: a?.note || '',
    trimAbove: str(t?.above_pct),
    trimTo: str(t?.to_pct),
    trimLow: plan ? str(t?.zone_low) : round(z?.trim?.low),
    trimHigh: plan ? str(t?.zone_high) : round(z?.trim?.high),
    trimNote: t?.note || '',
    exits: (plan?.exit_conditions || []).join('\n'),
    tax: plan?.tax_notes || '',
    review: plan?.next_review || '',
  };
}

export function planCheck(form) {
  if (!ROLE[form.role]) return 'Pick a role for this holding.';
  if (!text(form.thesis)) return 'Say in a line or two why you hold it.';
  if (form.thesis.length > 2000) return 'The thesis runs past 2,000 characters. Trim it a little.';
  const nums = ['min', 'max', 'addLow', 'addHigh', 'addMax', 'trimAbove', 'trimTo', 'trimLow', 'trimHigh'].map((k) => num(form[k]));
  if (nums.some((v) => Number.isNaN(v))) return 'One of the numbers doesn’t read as a number.';
  if (nums.some((v) => v != null && v < 0)) return 'Numbers can’t be negative.';
  const [min, max, addLow, addHigh, , trimAbove, trimTo, trimLow, trimHigh] = nums;
  if ((min != null || max != null) && (max == null || (min ?? 0) > max)) return 'The band needs a ceiling at or above its floor.';
  if (max != null && max > 100) return 'The band’s ceiling can’t pass 100%.';
  if ((addLow == null) !== (addHigh == null)) return 'The add zone needs both prices, or neither.';
  if (addLow != null && addLow > addHigh) return 'The add zone’s low price is above its high price.';
  if ((trimLow == null) !== (trimHigh == null)) return 'The trim zone needs both prices, or neither.';
  if (trimLow != null && trimLow > trimHigh) return 'The trim zone’s low price is above its high price.';
  if (trimAbove != null && trimTo != null && trimTo > trimAbove) return 'Trim back to a weight below the trigger.';
  if (form.review && !DAY.test(form.review)) return 'The review date needs a real date.';
  return null;
}

export function planFromForm(form, plan) {
  const [min, max, addLow, addHigh, addMax, trimAbove, trimTo, trimLow, trimHigh] = ['min', 'max', 'addLow', 'addHigh', 'addMax', 'trimAbove', 'trimTo', 'trimLow', 'trimHigh'].map((k) => num(form[k]));
  const base = editable(plan);
  const hasAdd = addLow != null || addMax != null || text(form.addNote) || plan?.add_rule;
  const hasTrim = trimAbove != null || trimLow != null || text(form.trimNote) || plan?.trim_rule;
  return {
    ...base,
    role: form.role,
    thesis: form.thesis.trim(),
    weight_band: max == null ? null : { min_pct: min ?? 0, max_pct: max },
    add_rule: hasAdd ? { zone_low: addLow, zone_high: addHigh, max_per_month_usd: addMax, deposits_only: Boolean(form.depositsOnly), note: text(form.addNote) } : null,
    trim_rule: hasTrim ? { above_pct: trimAbove, to_pct: trimTo, zone_low: trimLow, zone_high: trimHigh, note: text(form.trimNote) } : null,
    exit_conditions: String(form.exits || '')
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 8),
    tax_notes: text(form.tax),
    next_review: form.review || null,
  };
}

// ---------- step form ----------
export function stepShape(kind) {
  const trade = TRADES.includes(kind);
  const sell = SELLS.includes(kind);
  return {
    text: kind === 'hold' || kind === 'other',
    shares: trade,
    amount: kind === 'add' || kind === 'repay',
    until: trade,
    when: kind !== 'repay' && kind !== 'review',
    account: trade,
    lots: sell,
    noBuy: kind === 'harvest' || kind === 'sell',
  };
}

export function startStep(kind, templates = {}) {
  const t = templates[kind] || {};
  return {
    kind,
    text: '',
    shares: str(t.shares),
    amount: str(t.amount_usd),
    due: t.due || '',
    until: t.until || '',
    when: t.when || '',
    account: t.account || '',
    lots: t.lots || (SELLS.includes(kind) ? 'highest_cost' : ''),
    noBuy: str(t.no_buy_days ?? (kind === 'harvest' ? 31 : '')),
    note: t.note || '',
  };
}

export function stepCheck(form) {
  const shape = stepShape(form.kind);
  if (!STEP_KIND[form.kind]) return 'Pick what kind of step this is.';
  if (shape.text && !text(form.text)) return 'Say what the step is.';
  const all = shape.shares && String(form.shares).trim().toLowerCase() === 'all';
  const shares = shape.shares && !all ? num(form.shares) : null;
  const amount = shape.amount ? num(form.amount) : null;
  const noBuy = shape.noBuy ? num(form.noBuy) : null;
  if ([shares, amount, noBuy].some((v) => Number.isNaN(v))) return 'One of the numbers doesn’t read as a number.';
  if ([shares, amount].some((v) => v != null && v <= 0)) return 'Shares and dollars need to be above zero.';
  if (noBuy != null && (noBuy < 0 || !Number.isInteger(noBuy))) return 'No-buy days is a whole number.';
  if (SELLS.includes(form.kind) && shares == null && !all) return 'Say how many shares, or type all.';
  if (form.kind === 'add' && shares == null && amount == null) return 'Give the buy a dollar amount or a share count.';
  if (form.due && !DAY.test(form.due)) return 'The start date needs a real date.';
  if (form.until && !DAY.test(form.until)) return 'The end date needs a real date.';
  if (form.until && !form.due) return 'A window needs its start date too.';
  if (form.due && form.until && form.until < form.due) return 'The window ends before it starts.';
  if (!form.due && !(shape.when && text(form.when))) return shape.when ? 'Give it a date, or say what it waits on.' : 'Give it a date.';
  return null;
}

export function stepFromForm(form) {
  const shape = stepShape(form.kind);
  const out = { kind: form.kind };
  if (shape.text) out.text = form.text.trim();
  if (shape.shares && text(form.shares)) out.shares = String(form.shares).trim().toLowerCase() === 'all' ? 'all' : num(form.shares);
  if (shape.amount && num(form.amount) != null) out.amount_usd = num(form.amount);
  if (form.due) out.due = form.due;
  if (shape.until && form.until) out.until = form.until;
  if (shape.when && text(form.when)) out.when = form.when.trim();
  if (shape.account && text(form.account)) out.account = form.account.trim();
  if (shape.lots && form.lots) out.lots = form.lots;
  if (shape.noBuy && num(form.noBuy) != null) out.no_buy_days = num(form.noBuy);
  if (text(form.note)) out.note = form.note.trim();
  return out;
}

// ---------- messages ----------
export function refusal(e) {
  if (!e) return null;
  const detail = e.body?.detail;
  if (Array.isArray(detail)) {
    const lines = detail.map((d) => (typeof d === 'string' ? d : d?.msg)).filter(Boolean);
    if (lines.length) return lines.join(' ');
  }
  if (detail && typeof detail === 'object' && Array.isArray(detail.reasons)) return detail.reasons.join(' ');
  const said = e.message && !/^The desk API answered|^HTTP /.test(e.message) ? e.message : null;
  if (e.status === 404) return said || 'Stock plans switch on with the next desk update.';
  if (e.status === 422 || e.status === 409) return said || 'The desk refused that, so nothing was written.';
  if (e.status) return said || `The desk answered ${e.status}. Nothing was written.`;
  return 'The desk API didn’t answer. Nothing was written.';
}

export function savedText(result, symbol, approve) {
  const p = result?.plan;
  if (result && result.changed === false) return `Nothing changed on the ${symbol} plan.`;
  if (!p) return `Saved the ${symbol} plan.`;
  return p.status === 'approved' || approve ? `${symbol} plan v${p.version} is saved and in force.` : `Saved as draft v${p.version}. Approve it to put it in force.`;
}

// ---------- bridge ----------
export function bridgeSteps(data) {
  const items = data?.items || [];
  const noBuy = Object.entries(data?.no_buy || {}).map(([symbol, w]) => ({
    symbol,
    text: w.until ? `No ${symbol} buys until ${dayLabel(w.until)}` : `No ${symbol} buys while its loss sale is planned`,
    reason: w.reason || null,
  }));
  const rows = items.map((s) => ({ key: `${s.symbol}-${s.id}`, symbol: s.symbol, id: s.id, text: s.text, when: stepWhen(s), stamp: stepStamp(s), status: stepStatus(s), open: s.status === 'open' || s.status === 'partial', note: s.note || null }));
  return { rows, noBuy, count: rows.length };
}

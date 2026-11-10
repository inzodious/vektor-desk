import { dayLabel } from './charts.js';
import { plural, usd } from './format.js';

export const FAMILIES = [
  { v: 'house', t: 'The capped you', short: 'The capped you' },
  { v: 'buy_cap', t: 'Cap each buy', short: 'Buy cap', param: 'buy_cap' },
  { v: 'position_cap', t: 'Cap each name', short: 'Name cap', param: 'position_cap' },
  { v: 'stop', t: 'Sell when it drops', short: 'Stop', param: 'stop' },
  { v: 'trend', t: 'Follow the trend', short: '200-day trend' },
  { v: 'no_margin', t: 'No margin', short: 'No margin' },
  { v: 'long_term', t: 'Hold a year and a day', short: 'Year and a day' },
];

const FAMILY = Object.fromEntries(FAMILIES.map((f) => [f.v, f]));
const CAPS = new Set(['house', 'buy_cap', 'position_cap']);
const WHAT = {
  cap: { t: 'Cut to the cap', to: 'to the index' },
  margin: { t: 'Not borrowed', to: 'left unbought' },
  stop: { t: 'Stopped out', to: 'to the index' },
  trend: { t: 'Under its 200-day', to: 'to the index' },
  wait: { t: 'Sale held back', to: 'kept in the stock' },
};

export const GROUPS = [
  { key: 'size', title: 'Size', tone: 'mint', families: ['buy_cap', 'position_cap'], ask: 'Was it the picks or the size?' },
  { key: 'exits', title: 'Exits', tone: 'mustard', families: ['stop', 'trend'], ask: 'Does cutting losers pay for the winners it also cuts?' },
  { key: 'habits', title: 'Margin and patience', tone: 'sky', families: ['no_margin', 'long_term'], ask: 'What did borrowing and selling early cost?' },
];

// ---------- rules ----------
export function levelOf(v) {
  const p = FAMILY[v?.family]?.param;
  return p && v.params?.[p] != null ? Math.round(v.params[p] * 100) : null;
}

export function shortLabel(v) {
  if (!v) return '';
  const f = FAMILY[v.family];
  const level = levelOf(v);
  if (!f) return v.label;
  if (level == null) return f.short;
  return v.family === 'stop' ? `Stop at ${level}% down` : `${f.short} ${level}%`;
}

export function familyOptions(view) {
  const have = new Set((view?.variants || []).map((v) => v.family));
  return FAMILIES.filter((f) => have.has(f.v)).map((f) => ({ v: f.v, t: f.t }));
}

export function levelOptions(view, family) {
  return (view?.variants || [])
    .filter((v) => v.family === family && levelOf(v) != null)
    .map((v) => ({ v: v.id, t: `${levelOf(v)}%` }));
}

export function pickRule(view, id) {
  const list = view?.variants || [];
  return list.find((v) => v.id === id) || list.find((v) => v.id === view?.headline) || list[0] || null;
}

export function firstOf(view, family) {
  const list = (view?.variants || []).filter((v) => v.family === family);
  return list.find((v) => levelOf(v) === 10) || list.find((v) => levelOf(v) === 20) || list[0] || null;
}

// ---------- reads ----------
export function signed(v) {
  return v == null ? '—' : usd(v, { sign: true });
}

export function headline(view) {
  const v = pickRule(view, view?.headline);
  if (!v) return null;
  const ahead = v.change_usd >= 0;
  return { value: signed(v.change_usd), tone: ahead ? 'up' : 'dn', line: ahead ? 'the capped you finishes ahead of you' : 'you finish ahead of the capped you' };
}

export function split(view, v) {
  if (!view?.you || !view?.index_only || !v || !CAPS.has(v.family)) return null;
  return { picks: v.end_value - view.index_only.end_value, size: view.you.end_value - v.end_value };
}

export function splitRead(s) {
  if (!s) return null;
  const picks = s.picks >= 0 ? `Your picks beat the S&P 500 by ${usd(s.picks)} at the capped size.` : `Your picks trailed the S&P 500 by ${usd(-s.picks)} at the capped size.`;
  const size = s.size >= 0 ? `Going bigger added ${usd(s.size)}.` : `Going bigger cost ${usd(-s.size)}.`;
  return `${picks} ${size}`;
}

export function chartSeries(view, v) {
  if (!view?.dates?.length || !v) return [];
  return [
    { name: 'You', short: 'You', color: 'var(--s1)', values: view.you.values, width: 2.5 },
    { name: shortLabel(v), short: v.family === 'house' ? 'Capped you' : 'With the rule', color: 'var(--s2)', values: v.values, width: 2.5 },
    { name: 'S&P 500', short: 'S&P 500', color: 'var(--s5)', values: view.index_only.values, dash: true },
  ];
}

export function yearTicks(days, narrow = false) {
  const out = [];
  let last = '';
  days.forEach((day, i) => {
    const year = day.slice(0, 4);
    if (year !== last) out.push({ i, label: i === 0 ? dayLabel(day).split(' ')[0] : year });
    last = year;
  });
  const start = out.length > 1 && out[1].i - out[0].i < (narrow ? 12 : 6) ? 1 : 0;
  return out.slice(start);
}

export function symbolBars(v) {
  return (v?.by_symbol || []).map((s) => ({ label: s.symbol, value: s.usd }));
}

export function helpRead(v) {
  if (!v) return null;
  if (!v.actions) return 'This rule never had to step in.';
  const best = (v.by_symbol || []).filter((s) => s.usd > 0)[0];
  const worst = (v.by_symbol || []).filter((s) => s.usd < 0)[0];
  const parts = [];
  if (best) parts.push(`helped most on ${best.symbol} (${signed(best.usd)})`);
  if (worst) parts.push(`cost most on ${worst.symbol} (${signed(worst.usd)})`);
  return parts.length ? `It ${parts.join(' and ')}.` : 'It moved money without changing the result.';
}

export const EVENT_ROWS = 6;

export function eventRows(v, max = EVENT_ROWS) {
  return (v?.events || []).slice(0, max).map((e) => {
    const w = WHAT[e.what] || { t: e.what, to: '' };
    return { key: `${e.date}-${e.symbol}-${e.what}`, date: dayLabel(e.date, true), symbol: e.symbol, what: w.t, usd: usd(e.usd), to: w.to };
  });
}

export function actionLine(v) {
  if (!v) return '';
  if (!v.actions) return 'Never stepped in';
  return `Stepped in ${plural(v.actions, 'time')} · ${usd(v.moved_usd)} moved`;
}

export function taxRead(view, v) {
  if (!v || v.family !== 'long_term' || v.tax_change_usd == null || !view?.tax_rates) return null;
  const less = v.tax_change_usd <= 0;
  return {
    value: usd(Math.abs(v.tax_change_usd)),
    line: less ? 'less tax on realized gains' : 'more tax, on larger gains',
    tone: less ? 'up' : 'dn',
    rates: `${view.tax_rates.short_pct}% short-term, ${view.tax_rates.long_pct}% long-term`,
  };
}

// ---------- every rule ----------
export function groups(view) {
  const list = view?.variants || [];
  return GROUPS.map((g) => {
    const rows = list.filter((v) => g.families.includes(v.family));
    const best = rows.reduce((a, b) => (a == null || b.change_usd > a.change_usd ? b : a), null);
    const worst = rows.reduce((a, b) => (a == null || b.change_usd < a.change_usd ? b : a), null);
    let read = null;
    if (rows.length) {
      if (worst.change_usd >= 0 && best.change_usd > 0) read = `Every version finishes ahead. Best: ${shortLabel(best)}.`;
      else if (best.change_usd <= 0) read = 'No version finishes ahead of what you did.';
      else read = `Mixed: ${shortLabel(best)} helps, ${shortLabel(worst)} costs.`;
    }
    return { ...g, items: rows.map((v) => ({ label: shortLabel(v), value: v.change_usd, hint: actionLine(v), id: v.id })), read };
  }).filter((g) => g.items.length);
}

// ---------- habits ----------
export function sizingTiles(view) {
  const s = view?.sizing;
  const m = view?.margin;
  if (!s) return [];
  const big = s.largest;
  return [
    { k: 'Single-name buys', v: String(s.buys), line: s.on_margin ? `${s.on_margin} partly on margin` : 'none on margin' },
    { k: 'Typical buy', v: s.median_pct == null ? '—' : `${s.median_pct.toFixed(1)}%`, line: 'of the account' },
    { k: 'Over 10%', v: String(s.over_10), line: s.buys ? `of ${plural(s.buys, 'buy')}` : 'no buys yet', tone: s.over_10 ? 'dn' : undefined },
    { k: 'Largest buy', v: big ? `${big.pct.toFixed(0)}%` : '—', line: big ? `${big.symbol}, ${dayLabel(big.date, true)}` : 'no buys yet', tone: big && big.pct > 10 ? 'dn' : undefined },
    { k: 'Days on margin', v: String(m?.days ?? 0), line: m?.peak_usd ? `peak ${usd(m.peak_usd)}` : 'never borrowed' },
    { k: 'Margin interest', v: usd(m?.interest_usd ?? 0), line: 'paid so far' },
  ];
}

export function spanLabel(view) {
  return view?.start && view?.end ? `${dayLabel(view.start, true)} to ${dayLabel(view.end, true)}` : null;
}

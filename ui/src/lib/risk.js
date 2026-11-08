export const PARTS = [
  { id: 'tolerance', title: 'How you feel about risk', blurb: 'Your nerve when markets swing.' },
  { id: 'capacity', title: 'What your money can take', blurb: 'Your timeline and cushion.' },
];

export const ZONES = [
  { from: 0.5, to: 1.5, color: 'var(--sky)' },
  { from: 1.5, to: 2.5, color: 'var(--mint)' },
  { from: 2.5, to: 3.5, color: 'var(--teal)' },
  { from: 3.5, to: 4.5, color: 'var(--mustard)' },
  { from: 4.5, to: 5.5, color: 'var(--coral)' },
];

// ---------- answers ----------
export function startAnswers(questions = [], versions = []) {
  const last = versions?.[0]?.answers || {};
  const ids = new Set((questions || []).map((q) => q.id));
  return Object.fromEntries(Object.entries(last).filter(([k]) => ids.has(k)));
}

export function answeredCount(questions = [], answers = {}) {
  return (questions || []).filter((q) => answers[q.id] != null).length;
}

export function byPart(questions = []) {
  return PARTS.map((p) => ({ ...p, questions: (questions || []).filter((q) => q.part === p.id) })).filter((p) => p.questions.length);
}

export function sameValue(a, b) {
  return String(a) === String(b);
}

// ---------- bands ----------
export function bandRows(bands = {}) {
  return Object.entries(bands || {})
    .map(([n, b]) => ({ n: Number(n), ...b }))
    .sort((a, b) => a.n - b.n);
}

export function bandFacts(b) {
  if (!b) return [];
  return [
    { k: 'Stocks', v: `${b.equity_min_pct}–${b.equity_max_pct}%` },
    { k: 'Speculative', v: b.speculative_max_pct ? `up to ${b.speculative_max_pct}%` : 'none' },
    { k: 'One stock', v: `up to ${b.single_stock_max_pct}%` },
    { k: 'Worst year', v: `−${b.worst_year_loss_pct}%` },
  ];
}

export function limitText(c) {
  if (!c) return null;
  const t = c.tolerance_band;
  const cap = c.capacity_band;
  if (c.limited_by === 'capacity' && t != null && cap != null) return `Your nerve says band ${t}; your timeline and cushion hold it at ${cap}.`;
  if (c.limited_by === 'tolerance' && t != null && cap != null) return `Your timeline could carry band ${cap}; your comfort sets it at ${t}.`;
  return `Your nerve and your timeline agree on band ${c.band}.`;
}

export function worstDollars(b, value) {
  if (!b || !value) return null;
  return Math.round((value * b.worst_year_loss_pct) / 100 / 100) * 100;
}

// ---------- results ----------
export function savedText(res) {
  if (!res) return null;
  const r = res.result || res.current;
  if (!res.changed) return 'Same answers as last time, so nothing changed.';
  return `Saved. You’re band ${r?.band}, ${r?.label}.`;
}

export function riskRefusal(err) {
  if (err?.status === 422) return /not answered/.test(err.message || '') ? 'A few questions still need an answer.' : err.message;
  if (err?.status === 404) return 'The risk check switches on with the next desk update.';
  return err?.message || 'The desk didn’t save that. Try again in a moment.';
}

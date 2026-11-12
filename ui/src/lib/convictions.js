export const STATUS = {
  inside: { t: 'Inside its band', tone: 'ok' },
  above: { t: 'Above the ceiling', tone: 'watch' },
  below: { t: 'Under its floor', tone: 'info' },
};

const TICKER = /^[A-Z0-9.-]{1,12}$/;

// ---------- words ----------
export function pct(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${Number.isInteger(n) ? n : Number(n.toFixed(1))}%`;
}

export function statusWord(item) {
  if (item?.enabled === false) return { t: 'Paused', tone: '' };
  return STATUS[item?.status] || { t: 'No weight yet', tone: '' };
}

export function bandText(item) {
  return `${pct(item.band_min_pct)} to ${pct(item.band_max_pct)}`;
}

export function weightLine(item, dayLabel = (d) => d) {
  if (item?.weight_pct == null) return 'Weight shows after the next daily run';
  const when = item.weight_as_of ? ` as of ${dayLabel(String(item.weight_as_of).slice(0, 10))}` : '';
  return `${pct(item.weight_pct)} of the portfolio${when}`;
}

export function nudgeLine(item) {
  if (item?.enabled === false) return 'Paused in your profile, so the single-stock cap applies again.';
  if (item?.status === 'above') return `Above ${pct(item.band_max_pct)}. The desk suggests a trim once a week until it’s back inside.`;
  if (item?.status === 'below') return `Under ${pct(item.band_min_pct)}. Nothing to do unless you want it back up.`;
  if (item?.status === 'inside') return 'Inside its band. No nudges.';
  return null;
}

export function suggestLine(s) {
  if (!s) return 'Take the risk check for a suggested ceiling, or set one yourself.';
  return `Band ${s.from_band} (${s.label}) suggests ${pct(s.band_min_pct)} to ${pct(s.band_max_pct)}.`;
}

export function scaleMax(item) {
  const top = Math.max(Number(item?.band_max_pct) || 0, Number(item?.weight_pct) || 0);
  return Math.max(5, Math.ceil((top * 1.3) / 5) * 5);
}

export function meter(item) {
  const max = scaleMax(item);
  const at = (v) => Math.min(100, Math.max(0, (Number(v) / max) * 100));
  return {
    max,
    from: at(item.band_min_pct),
    to: at(item.band_max_pct),
    mark: item.weight_pct == null ? null : at(item.weight_pct),
  };
}

// ---------- form ----------
export function startForm(item, suggested) {
  if (item) return { symbol: item.symbol, min: String(item.band_min_pct ?? ''), max: String(item.band_max_pct ?? ''), note: item.note || '' };
  return { symbol: '', min: suggested ? String(suggested.band_min_pct) : '0', max: suggested ? String(suggested.band_max_pct) : '', note: '' };
}

export function num(v) {
  const t = String(v ?? '').trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

export function bandCheck(form, { taken = [], editing = false } = {}) {
  const symbol = String(form.symbol || '').trim().toUpperCase();
  if (!TICKER.test(symbol)) return 'Type a ticker, like ACME.';
  if (!editing && taken.includes(symbol)) return `${symbol} already has a band. Edit it instead.`;
  const min = num(form.min);
  const max = num(form.max);
  if (Number.isNaN(min) || Number.isNaN(max)) return 'The floor and ceiling need to be numbers.';
  if (max == null) return 'Give it a ceiling.';
  if ((min ?? 0) < 0 || max > 100) return 'Keep the band between 0% and 100%.';
  if (min != null && min > max) return 'The floor sits above the ceiling.';
  if (String(form.note || '').length > 200) return 'Keep the note under 200 characters.';
  return null;
}

export function bandBody(form) {
  const body = { band_max_pct: num(form.max) };
  const min = num(form.min);
  body.band_min_pct = min == null ? 0 : min;
  body.note = String(form.note || '').trim();
  return body;
}

export function savedText(r, symbol) {
  if (!r?.changed) return `Nothing changed for ${symbol}.`;
  const band = r.item ? ` now holds ${bandText(r.item)}` : '';
  return `Saved. ${symbol}${band}. A backup was kept.`;
}

export function droppedText(r, symbol) {
  return r?.changed === false ? `${symbol} had nothing to remove.` : `Removed ${symbol}’s band. The single-stock cap covers it again.`;
}

export function editRefusal(e) {
  if (!e) return null;
  const said = e.message && !/^The desk API answered|^HTTP /.test(e.message) ? e.message : null;
  if (e.status === 409) return said || 'There’s no profile yet. Write one from the first-run checklist.';
  if (e.status === 404) return said || 'This switches on with the next desk update.';
  if (e.status === 422) return said || 'The desk refused that change, so nothing was written.';
  if (e.status) return `The desk answered ${e.status}. Nothing was written.`;
  return 'The desk API didn’t answer. Nothing was written.';
}

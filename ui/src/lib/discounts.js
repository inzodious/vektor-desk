import { signedPct } from './strategy.js';

export const LIST = { held: { t: 'Held', tone: 'ok' }, watchlist: { t: 'Watchlist', tone: 'lilac' }, quality: { t: 'Quality list', tone: '' } };
export const VERDICT = { buy: { t: 'Case to buy', tone: 'ok' }, wait: { t: 'Wait', tone: 'info' }, avoid: { t: 'Avoid', tone: 'watch' } };

// ---------- words ----------
export function reasonText(r) {
  const n = r?.numbers || {};
  if (r?.reason === 'big_down_day') {
    const move = n.day_move_pct != null ? `${signedPct(n.day_move_pct)} today` : 'A big down day';
    const z = r.move_z != null ? `, ${Math.abs(r.move_z).toFixed(1)}× its usual swing` : '';
    return `${move}${z}`;
  }
  const m = /^crossed_(\d+)$/.exec(r?.reason || '');
  if (m) return `First close ${m[1]}% under its 52-week high`;
  return r?.reason || '';
}

export function valuationText(v) {
  if (!v || v.value == null) return null;
  const what = v.metric === 'pe_annual' ? `P/E ${v.value.toFixed(1)}` : `${Math.round(v.value * 100)}% of its 5-year average price`;
  if (v.pctile_own == null) return what;
  const cheaper = Math.round((1 - v.pctile_own) * 100);
  if (cheaper >= 50) return `${what}, cheaper than ${cheaper}% of its last 5 years`;
  return `${what}, pricier than ${100 - cheaper}% of its last 5 years`;
}

export function listWord(l) {
  return LIST[l] || { t: l || 'Scanned', tone: '' };
}

export function verdictWord(c) {
  if (!c) return null;
  return VERDICT[c.verdict] || { t: c.verdict, tone: '' };
}

export function discountHead(d) {
  const rows = d?.rows || [];
  const held = rows.filter((r) => r.list === 'held').length;
  const cases = rows.filter((r) => r.case).length;
  const buys = rows.filter((r) => r.case?.verdict === 'buy').length;
  return { total: rows.length, held, cases, waiting: rows.length - cases, buys };
}

export function headLine(d) {
  const h = discountHead(d);
  if (!h.total) return null;
  const parts = [`${h.total} ${h.total === 1 ? 'name' : 'names'} on sale`];
  if (h.held) parts.push(`${h.held} you hold`);
  if (h.buys) parts.push(`${h.buys} with a case to buy`);
  if (h.waiting) parts.push(`${h.waiting} still being read`);
  return parts.join(' · ');
}

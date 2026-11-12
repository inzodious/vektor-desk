export function niceTicks(min, max, n = 4) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1;
    min -= pad;
    max += pad;
  }
  const span = max - min;
  const step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const out = [];
  for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
  return out;
}

export function extent(series, refs = []) {
  let lo = Infinity;
  let hi = -Infinity;
  series.forEach((s) =>
    s.values.forEach((v) => {
      if (v == null) return;
      lo = Math.min(lo, v);
      hi = Math.max(hi, v);
    }),
  );
  refs.forEach((r) => {
    lo = Math.min(lo, r.y);
    hi = Math.max(hi, r.y);
  });
  return [lo, hi];
}

export function linePath(values, X, Y) {
  let d = '';
  let pen = false;
  values.forEach((v, i) => {
    if (v == null) {
      pen = false;
      return;
    }
    d += `${pen ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`;
    pen = true;
  });
  return d;
}

export function sparkPath(values, w, h) {
  const vals = values.filter((v) => v != null);
  if (vals.length < 2) return { d: '', y: () => h / 2 };
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const y = (v) => h - 2 - ((v - lo) / (hi - lo || 1)) * (h - 4);
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${((i / (values.length - 1)) * w).toFixed(1)} ${y(v ?? lo).toFixed(1)}`).join('');
  return { d, y };
}

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const ET_DAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' });

export function parseDay(day) {
  const text = String(day ?? '');
  const timed = text.length > 10 ? new Date(text) : null;
  const [y, m, d] = (timed && !Number.isNaN(timed.getTime()) ? ET_DAY.format(timed) : text).slice(0, 10).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function dayLabel(day, withYear = false) {
  const d = parseDay(day);
  if (Number.isNaN(d.getTime())) return '';
  return `${MON[d.getUTCMonth()]} ${d.getUTCDate()}${withYear ? `, ${d.getUTCFullYear()}` : ''}`;
}

export function monthTicks(days, maxLabels = 8) {
  const out = [];
  let last = '';
  days.forEach((day, i) => {
    const key = day.slice(0, 7);
    if (key !== last && i > 0) out.push({ i, label: day.slice(5, 7) === '01' ? day.slice(0, 4) : MON[Number(day.slice(5, 7)) - 1] });
    last = key;
  });
  if (out.length <= maxLabels) return out;
  const every = Math.ceil(out.length / maxLabels);
  return out.filter((_, k) => k % every === 0);
}

export const PERIODS = [
  { v: '1M', t: '1 month', days: 31 },
  { v: '3M', t: '3 months', days: 92 },
  { v: 'YTD', t: 'Year to date' },
  { v: '1Y', t: '1 year', days: 366 },
  { v: 'MAX', t: 'All' },
];

export function periodStart(period, lastDay) {
  if (!lastDay) return null;
  const p = PERIODS.find((x) => x.v === period);
  if (!p || period === 'MAX') return null;
  if (period === 'YTD') return `${lastDay.slice(0, 4)}-01-01`;
  const d = parseDay(lastDay);
  d.setUTCDate(d.getUTCDate() - p.days);
  return d.toISOString().slice(0, 10);
}

export function divergingColor(v, max = 1) {
  const t = Math.max(-1, Math.min(1, v / max));
  const c = t >= 0 ? 'var(--up)' : 'var(--dn)';
  return { fill: `color-mix(in oklab, ${c} ${Math.round(Math.abs(t) * 100)}%, var(--mid))`, ink: Math.abs(t) > 0.55 ? '#fff' : 'var(--ink)' };
}

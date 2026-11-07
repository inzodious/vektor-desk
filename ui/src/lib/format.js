const MINUS = '−';

export function usd(v, o = {}) {
  if (v == null || Number.isNaN(v)) return '—';
  const d = o.cents ? 2 : 0;
  const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  return `${v < 0 ? MINUS : o.sign && v > 0 ? '+' : ''}$${s}`;
}

export function pct(v, dg = 1, sign = false) {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v < 0 ? MINUS : sign && v > 0 ? '+' : ''}${Math.abs(v * 100).toFixed(dg)}%`;
}

export function pts(v, sign = true) {
  if (v == null || Number.isNaN(v)) return '—';
  return `${v < 0 ? MINUS : sign && v > 0 ? '+' : ''}${Math.abs(v * 100).toFixed(1)} pts`;
}

export function px(v) {
  if (v == null || Number.isNaN(v)) return '—';
  return v >= 1000 ? v.toLocaleString('en-US', { maximumFractionDigits: 0 }) : v.toFixed(2);
}

export function count(v) {
  if (v == null) return '—';
  return v.toLocaleString('en-US');
}

const ET = 'America/New_York';

export function etTime(date) {
  return new Intl.DateTimeFormat('en-US', { timeZone: ET, hour: 'numeric', minute: '2-digit' }).format(date);
}

export function etDate(date, o = {}) {
  return new Intl.DateTimeFormat('en-US', { timeZone: ET, month: 'short', day: 'numeric', ...(o.year ? { year: 'numeric' } : {}) }).format(date);
}

export function etStamp(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return `${etDate(d)}, ${etTime(d)} ET`;
}

export function plainDate(isoDay) {
  if (!isoDay) return null;
  const [y, m, d] = isoDay.split('-').map(Number);
  return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' }).format(Date.UTC(y, m - 1, d));
}

export function ago(hours) {
  if (hours == null) return null;
  if (hours < 1 / 60) return 'just now';
  if (hours < 1) return `${Math.round(hours * 60)} min ago`;
  if (hours < 48) {
    const h = Math.round(hours * 10) / 10;
    return `${h} ${h === 1 ? 'hour' : 'hours'} ago`;
  }
  return `${Math.round(hours / 24)} days ago`;
}

export function plural(n, word, many = `${word}s`) {
  return `${count(n)} ${n === 1 ? word : many}`;
}

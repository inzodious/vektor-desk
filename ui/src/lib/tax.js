import { dayLabel } from './charts.js';

export function mergeWindows(windows = []) {
  const map = new Map();
  windows.forEach((w) => {
    const k = `${w.symbol}|${w.kind}`;
    const m = map.get(k) || { symbol: w.symbol, kind: w.kind, date: w.date, clears: w.clears, accounts: [], amount: 0 };
    if (w.date < m.date) m.date = w.date;
    if (w.clears > m.clears) m.clears = w.clears;
    if (w.account && !m.accounts.includes(w.account)) m.accounts.push(w.account);
    m.amount += w.amount || 0;
    map.set(k, m);
  });
  return [...map.values()].sort((a, b) => a.clears.localeCompare(b.clears) || a.symbol.localeCompare(b.symbol));
}

export function windowLine(w) {
  if (w.kind === 'loss_sale') return `Sold ${w.symbol} at a loss on ${dayLabel(w.date)}. Buying it back before ${dayLabel(w.clears)} would wash the loss.`;
  return `Bought ${w.symbol} on ${dayLabel(w.date)}. Selling it at a loss before ${dayLabel(w.clears)} would be a wash sale.`;
}

export function todayEt(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now);
}

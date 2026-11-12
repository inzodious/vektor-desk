import { createContext, useContext } from 'react';
import { dayLabel } from '../lib/charts.js';

export const LiveContext = createContext({ live: null, symbols: [], cash: 0, names: {}, intraday: {}, loading: true, error: null, reload: () => {} });
export const SymbolContext = createContext({ openSymbol: () => {} });

export const useLive = () => useContext(LiveContext);
export const useSymbol = () => useContext(SymbolContext);

export const LIVE_STATES = ['pre', 'open', 'after'];

export function sessionWord(source, state) {
  const fund = source === 'holdings';
  if (state === 'pre' || state === 'open') return fund ? 'Prices at 4 PM' : 'No ticks yet';
  if (state === 'after') return fund ? 'Prior close' : 'Closing quote';
  return fund ? 'Last close' : 'Closing quote';
}

const ACCOUNTS = { individual: 'Individual', hsa: 'HSA', roth: 'Roth IRA', ira: 'IRA', '401k': '401(k)', brokerage: 'Brokerage', joint: 'Joint' };

export function accountLabel(key) {
  if (!key) return '—';
  const head = String(key).split(/[-_]/)[0].toLowerCase();
  return ACCOUNTS[head] || head.charAt(0).toUpperCase() + head.slice(1);
}

export function groupLive(rows = []) {
  const map = new Map();
  let cash = 0;
  rows.forEach((r) => {
    if (r.source === 'cash') {
      cash += r.value || 0;
      return;
    }
    const g = map.get(r.symbol) || { symbol: r.symbol, shares: 0, value: 0, day_change: 0, price: r.price, prev_close: r.prev_close, source: r.source, accounts: [] };
    g.shares += r.shares || 0;
    g.value += r.value || 0;
    g.day_change += r.day_change || 0;
    g.accounts.push({ account: r.account, shares: r.shares, value: r.value, day_change: r.day_change });
    if (r.source === 'finnhub' || r.source === 'live') g.source = r.source;
    map.set(r.symbol, g);
  });
  const symbols = [...map.values()].map((g) => ({ ...g, change_pct: g.prev_close ? g.price / g.prev_close - 1 : null })).sort((a, b) => b.value - a.value);
  return { symbols, cash };
}

export function isLiveSource(source) {
  return source && source !== 'holdings' && source !== 'cash';
}

export function priceStatus(live, row) {
  if (!row) return null;
  const state = live?.state;
  if (isLiveSource(row.source) && LIVE_STATES.includes(state)) {
    return live.quality === 'stale' ? { tone: 'watch', text: 'Quotes delayed', pulse: false } : { tone: 'ok', text: 'Live', pulse: true };
  }
  if (isLiveSource(row.source)) return { tone: '', text: 'Last trade', pulse: false };
  return { tone: 'info', text: `Close ${live?.holdings_date ? dayLabel(live.holdings_date) : ''}`.trim(), pulse: false };
}

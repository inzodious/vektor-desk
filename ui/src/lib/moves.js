export const MOVE_VERDICT = {
  overreaction: { t: 'Looks overdone', tone: 'ok' },
  justified: { t: 'Real news', tone: 'watch' },
  sector: { t: 'Sector move', tone: 'info' },
  unclear: { t: 'No clear cause', tone: 'lilac' },
};

const STATUS = {
  waiting: { t: 'After the close', tone: 'info' },
  queued: { t: 'Queued', tone: 'info' },
  running: { t: 'Researching', tone: 'info' },
  failed: { t: 'Didn’t finish', tone: 'watch' },
  capped: { t: 'Not researched', tone: '' },
  market: { t: 'With the market', tone: '' },
  small: { t: 'Small move', tone: '' },
};

export function moveChip(row, ask) {
  if (row?.verdict && MOVE_VERDICT[row.verdict]) return MOVE_VERDICT[row.verdict];
  if (row?.status === 'waiting' && ask?.status === 'queued') return STATUS.queued;
  return STATUS[row?.status] || STATUS.market;
}

export function bigMoves(data) {
  return (Array.isArray(data?.rows) ? data.rows : []).filter((r) => r.label === 'due');
}

export function quietMoves(data) {
  return (Array.isArray(data?.rows) ? data.rows : []).filter((r) => r.label !== 'due');
}

export function chipRows(data, top = 3) {
  const big = bigMoves(data);
  const rest = quietMoves(data)
    .filter((r) => Math.abs(r.change_usd || 0) >= 0.5)
    .sort((a, b) => Math.abs(b.change_usd) - Math.abs(a.change_usd));
  return [...big, ...rest].slice(0, top);
}

export function moveHead(data) {
  const big = bigMoves(data);
  if (!big.length) return 'Nothing moved more than the market';
  const done = big.filter((r) => r.status === 'explained').length;
  if (done === big.length) return `${big.length === 1 ? 'One big move' : `${big.length} big moves`}, explained`;
  return `${done} of ${big.length} big moves explained`;
}

export function confidenceWords(c) {
  if (c == null) return null;
  return `${Math.round(c * 100)}% sure`;
}

export const BUSY = ['queued', 'running'];

export function movesEvery(d) {
  return BUSY.includes(d?.ask?.status) || (d?.rows || []).some((r) => r.status === 'running') ? 15000 : 300000;
}

const CHECK_WORD = {
  closes: 'Closing prices',
  freshness: 'Mirror freshness',
  value: 'Values against the broker',
  shares: 'Share counts and lots',
  marginal_rate: 'Tax rate',
  research: 'Research data',
  lookthrough: 'Fund look-through',
  symbol_kinds: 'Symbol types',
};
const RANK = { fail: 0, warn: 1 };

export const checkWord = (name) => CHECK_WORD[name] || String(name || '').replace(/_/g, ' ');

export function healthBanner(h) {
  if (!h || (h.status !== 'fail' && h.status !== 'warn')) return null;
  const bad = (h.checks || []).filter((c) => c.status === 'fail' || c.status === 'warn').sort((a, b) => RANK[a.status] - RANK[b.status]);
  const level = h.status;
  const top = bad[0];
  return {
    level,
    head: level === 'fail' ? 'Look, don’t act yet.' : 'Worth a look before you act.',
    fix: top ? `${checkWord(top.check_name)}: ${top.detail}` : 'The engine has not finished a run yet. It fills in after the next nightly run.',
    others: bad.slice(1).map((c) => ({ name: checkWord(c.check_name), status: c.status, detail: c.detail })),
    key: `${h.as_of || 'none'}|${bad.map((c) => `${c.check_name}:${c.status}`).join(',')}`,
  };
}

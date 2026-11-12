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

// ---------- the one alert left on every page: numbers that cannot be trusted ----------
export function healthAlert(h) {
  if (!h || h.status !== 'fail') return null;
  const top = (h.checks || []).find((c) => c.status === 'fail');
  return { head: 'Look, don’t act yet.', fix: top ? `${checkWord(top.check_name)}: ${top.detail}` : 'The engine has not finished a run yet. It fills in after the next run.' };
}

// ---------- every check, for Settings ----------
export function healthChecks(h) {
  if (!h || !Array.isArray(h.checks)) return null;
  const bad = h.checks.filter((c) => c.status === 'fail' || c.status === 'warn').sort((a, b) => RANK[a.status] - RANK[b.status]);
  const fails = bad.filter((c) => c.status === 'fail').length;
  const fine = h.checks.length - bad.length;
  return {
    chip: fails ? `${fails} failing` : bad.length ? `${bad.length} to read` : 'All clear',
    tone: fails ? 'act' : bad.length ? 'watch' : 'ok',
    rows: bad.map((c) => ({ key: c.check_name, name: checkWord(c.check_name), status: c.status, detail: c.detail })),
    fine: fine > 0 ? `${fine} other ${fine === 1 ? 'check is' : 'checks are'} fine.` : null,
  };
}

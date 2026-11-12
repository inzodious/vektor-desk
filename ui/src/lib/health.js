const CHECK_WORD = {
  closes: 'Closing prices',
  freshness: 'Account read',
  value: 'Values against the broker',
  shares: 'Share counts and lots',
  marginal_rate: 'Tax rate',
  research: 'Research data',
  lookthrough: 'Fund look-through',
  symbol_kinds: 'Symbol types',
};

export const checkWord = (name) => CHECK_WORD[name] || String(name || '').replace(/_/g, ' ');

const KINDS = ['blocks', 'needs_you', 'fixes_itself'];
const GROUP = { blocks: 'Blocking', needs_you: 'Needs you', fixes_itself: 'Fixing itself' };

export const kindOf = (c) => (!c || c.status === 'ok' ? null : KINDS.includes(c.kind) ? c.kind : c.status === 'fail' ? 'blocks' : c.status === 'warn' ? 'needs_you' : null);

const sentence = (c) => (c.kind ? c.detail : `${checkWord(c.check_name)}: ${c.detail}`);

// ---------- the one alert left on every page: numbers that cannot be trusted ----------
export function healthAlert(h) {
  if (!h) return null;
  const top = (h.checks || []).find((c) => kindOf(c) === 'blocks');
  if (!top && h.status !== 'fail') return null;
  return { head: 'Look, don’t act yet.', fix: top ? sentence(top) : 'The engine has not finished a run yet. It fills in after the next run.' };
}

// ---------- what only he can fix, for the Setup chip and the first-run page ----------
export function healthNeeds(h) {
  return (h?.checks || []).filter((c) => kindOf(c) === 'needs_you' && typeof c.detail === 'string' && c.detail.trim()).map((c) => ({ key: c.check_name, text: c.kind ? c.detail : sentence(c) }));
}

// ---------- every check, for Settings ----------
export function healthChecks(h) {
  if (!h || !Array.isArray(h.checks)) return null;
  const row = (c) => {
    const tries = Number(c.heal?.attempts) || 0;
    return {
      key: c.check_name,
      name: checkWord(c.check_name),
      detail: c.detail,
      more: typeof c.diagnosis === 'string' && c.diagnosis.trim() && c.diagnosis !== c.detail ? c.diagnosis : null,
      tried: tries ? `The desk has asked ${tries === 1 ? 'once' : `${tries} times`}.` : null,
    };
  };
  const groups = KINDS.map((k) => ({ key: k, title: GROUP[k], rows: h.checks.filter((c) => kindOf(c) === k).map(row) })).filter((g) => g.rows.length);
  const n = (k) => groups.find((g) => g.key === k)?.rows.length || 0;
  const bad = groups.reduce((a, g) => a + g.rows.length, 0);
  const fine = h.checks.length - bad;
  return {
    chip: n('blocks') ? `${n('blocks')} blocking` : n('needs_you') ? `${n('needs_you')} for you` : n('fixes_itself') ? 'Fixing itself' : 'All clear',
    tone: n('blocks') ? 'act' : n('needs_you') ? 'watch' : n('fixes_itself') ? '' : 'ok',
    groups,
    fine: fine > 0 ? `${fine} other ${fine === 1 ? 'check is' : 'checks are'} fine.` : null,
  };
}

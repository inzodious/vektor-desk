const check = (health, name) => (health?.checks || []).find((c) => c.check_name === name);
const lastOk = (jobs, name) => (jobs?.jobs || []).find((j) => j.name === name)?.last_run?.result === 'ok';
const ready = (...apis) => apis.every((x) => x && (x.data != null || x.error || !x.loading));

// ---------- steps ----------
export function firstRunSteps({ status, jobs, health, profile, agents, board } = {}) {
  const s = status?.data;
  const h = health?.data;
  const j = jobs?.data;
  const p = profile?.data;
  const a = agents?.data;
  const b = board?.data;
  const mirrorOk = s?.mirror?.state === 'ok' || s?.mirror?.state === 'stale';
  const token = s?.claude_token?.state;
  const closes = check(h, 'closes');
  const shares = check(h, 'shares');
  const research = check(h, 'research');
  return [
    {
      id: 'mirror',
      title: 'Pull your accounts',
      line: 'Balances and activity come over from Escape Vektor, read only.',
      state: !ready(status) ? 'loading' : mirrorOk ? 'done' : 'todo',
      action: { kind: 'job', job: 'mirror', label: 'Pull now' },
    },
    {
      id: 'token',
      title: 'Connect Claude',
      line: 'The desks think through the Claude Code CLI on your subscription.',
      state: !ready(status) ? 'loading' : token === 'ok' || token === 'renew' ? 'done' : 'todo',
      action: { kind: 'link', to: '/settings', label: 'See the token' },
    },
    {
      id: 'backfill',
      title: 'Fill in price history',
      line: 'Years of daily prices so the risk and lab numbers have something to chew on.',
      state: !ready(health, jobs) ? 'loading' : lastOk(j, 'engine-backfill') || closes?.status === 'ok' ? 'done' : 'todo',
      action: { kind: 'job', job: 'engine-backfill', label: 'Backfill now' },
    },
    {
      id: 'daily',
      title: 'Run the daily numbers',
      line: 'Values, drift, risk and the plan checks for today.',
      state: !ready(health) ? 'loading' : h?.as_of && h.status !== 'fail' ? 'done' : 'todo',
      action: { kind: 'job', job: 'engine-daily', label: 'Run now' },
    },
    {
      id: 'profile',
      title: 'Write your desk profile',
      line: 'Your rules, limits and desks in desk.yaml. Defaults work until you do.',
      state: !ready(profile) ? 'loading' : p?.exists ? 'done' : 'todo',
      action: p?.exists ? { kind: 'link', to: '/settings', label: 'Open the profile' } : { kind: 'post', path: '/api/decisions/profile/init', label: 'Write it now' },
    },
    {
      id: 'lots',
      title: 'Bring in your tax lots',
      line: 'A Fidelity lot export unlocks tax-loss and wash-sale checks.',
      state: !ready(health) ? 'loading' : shares?.status === 'ok' && !/No lot export/i.test(shares?.detail || '') ? 'done' : 'todo',
      action: { kind: 'link', to: '/settings#inbox', label: 'Upload it' },
    },
    {
      id: 'research',
      title: 'Open the research feed',
      line: 'SEC filings and company facts for what you hold.',
      state: !ready(health) ? 'loading' : research?.status === 'ok' ? 'done' : 'todo',
      action: { kind: 'job', job: 'engine-research', label: 'Fetch now' },
    },
    {
      id: 'crew',
      title: 'Wake the crew',
      line: 'Turn the desks on, then lift the first-run guard when Plan keeper and Tax have run.',
      state: !ready(agents) ? 'loading' : a?.enabled && a?.guard && !a.guard.on ? 'done' : 'todo',
      action: { kind: 'link', to: '/settings', label: 'Open Desks' },
    },
    {
      id: 'race',
      title: 'Start the paper race',
      line: 'Strategies trade paper money for 182 days before any can go live.',
      state: !ready(board) ? 'loading' : (b?.rows || []).length ? 'done' : 'todo',
      action: { kind: 'link', to: '/lab/strategies', label: 'See the race' },
    },
    {
      id: 'risk',
      title: 'Take the risk check',
      line: 'Eight questions set the bands every strategy is measured against.',
      state: 'soon',
      action: { kind: 'link', to: '/settings/risk', label: 'Take it' },
    },
  ];
}

export function firstRunScore(steps) {
  const live = steps.filter((s) => s.state !== 'soon');
  const done = live.filter((s) => s.state === 'done').length;
  const left = live.length - done;
  const next = live.find((s) => s.state === 'todo') || null;
  return { done, total: live.length, left, next, share: live.length ? done / live.length : 0 };
}

export function countdown(left) {
  if (left <= 0) return 'Liftoff. Everything’s set.';
  return `T-minus ${left} ${left === 1 ? 'step' : 'steps'}`;
}

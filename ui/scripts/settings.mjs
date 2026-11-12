import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const DIR = fileURLToPath(new URL('../src/fixtures/', import.meta.url));
const read = (n) => JSON.parse(readFileSync(`${DIR}${n}.json`, 'utf8'));
const write = (n, body) => {
  writeFileSync(`${DIR}${n}.json`, `${JSON.stringify(body, null, 1)}\n`);
  console.log(`wrote ${n}.json`);
};
const after = (list, item, anchor) => {
  if (list.includes(item)) return list;
  const at = list.indexOf(anchor);
  return at < 0 ? [...list, item] : [...list.slice(0, at + 1), item, ...list.slice(at + 1)];
};

// ---------- margin rate in the profile ----------
const RATE = 12;
for (const name of ['decisions.profile', 'decisions.profile.fresh', 'decisions.profile.listed', 'decisions.profile.never', 'decisions.profile.quiet']) {
  const d = read(name);
  write(name, { ...d, editable: after(d.editable || [], 'margin', 'growth'), profile: { ...d.profile, margin: { rate_pct: RATE } } });
}
for (const name of ['decisions.profile.status', 'decisions.profile.status.empty', 'decisions.profile.status.failing', 'decisions.profile.status.fresh', 'decisions.profile.status.never']) {
  const d = read(name);
  write(name, { ...d, defaults: after(d.defaults || [], 'margin.rate_pct', 'growth.fi_target_from_plan'), margin: { rate_pct: RATE, source: 'default' } });
}

// ---------- the week line under a desk's meter ----------
for (const name of ['agents.status', 'agents.status.lifted']) {
  const d = read(name);
  write(name, {
    ...d,
    desks: d.desks.map((desk) => {
      if (desk.desk !== 'research') return { ...desk, week: { ...desk.week, line: null, parts: [] } };
      const asked = 0;
      const nightly = desk.week.runs - asked;
      return {
        ...desk,
        week: {
          ...desk.week,
          cap: 9,
          line: `Holdings pass ${nightly} of 5 this week, one per holding. On request ${asked} of 4.`,
          parts: [
            { name: 'Holdings pass', runs: nightly, cap: 5 },
            { name: 'On request', runs: asked, cap: 4 },
          ],
        },
      };
    }),
  });
}

// ---------- price history: which names are behind their last close ----------
const sym = (symbol, role, priority, o = {}) => ({ symbol, role, priority, daily: true, first_bar: '2016-01-04', last_bar: '2026-11-06', fetched_at: '2026-11-09T11:13:20+00:00', error: null, parked_until: null, behind: false, due: false, ...o });
const late = { last_bar: '2026-11-05', behind: true, due: true };
const backfill = {
  target: '2026-11-06',
  asks: 'every hour, day and night',
  limits: { hour: 40, day: 800, month_symbols: 400 },
  used: { hour: 8, day: 61, month_symbols: 58 },
  last_run: {
    finished_at: '2026-11-09T16:13:40+00:00',
    ok: false,
    detail: 'Asked Tiingo for 8 names. Failed: NOVA: Tiingo did not answer for NOVA. FXAIX and 5 others answered with nothing new for 2026-11-06.',
    fetched: ['FXAIX', 'HLTH', 'IDXA', 'IDXB', 'IDXC', 'IDXD'],
    advanced: [],
    behind: ['FXAIX', 'HLTH', 'IDXA', 'IDXB', 'IDXC', 'IDXD'],
    unpriced: ['ZZNEW'],
    errors: ['NOVA: Tiingo did not answer for NOVA'],
    error: null,
    left: 0,
    skipped_for_month_cap: 0,
  },
  symbols: [
    sym('ACME', 'held', 0),
    sym('BND', 'held', 0),
    sym('FTEC', 'held', 0),
    sym('FXAIX', 'held', 0, late),
    sym('VXUS', 'held', 0),
    sym('SPY', 'benchmark', 1),
    sym('NOVA', 'watch', 2, { ...late, error: 'Tiingo did not answer for NOVA' }),
    sym('ZZNEW', 'watch', 2, { first_bar: null, last_bar: null, behind: true, due: false, error: 'Tiingo has no prices for ZZNEW', parked_until: '2026-11-16T11:13:20+00:00' }),
    ...['HLTH', 'IDXA', 'IDXB', 'IDXC', 'IDXD'].map((s) => sym(s, 'universe', 3, late)),
    sym('OLDX', 'past', 3, { daily: false, last_bar: '2026-09-30', fetched_at: '2026-10-01T11:13:20+00:00' }),
  ],
};
write('engine.backfill', backfill);
const idle = { ...backfill, used: { hour: 0, day: 0, month_symbols: 0 }, last_run: null, symbols: [] };
write('engine.backfill.fresh', idle);
write('engine.backfill.never', idle);
write('engine.backfill.current', {
  ...backfill,
  last_run: { ...backfill.last_run, ok: true, detail: 'Nothing was behind, so Tiingo was not asked.', fetched: [], behind: [], unpriced: [], errors: [] },
  symbols: backfill.symbols.map((s) => ({ ...s, last_bar: s.daily ? '2026-11-06' : s.last_bar, first_bar: s.first_bar || '2026-10-01', behind: false, due: false, error: null, parked_until: null })),
});

// ---------- the box's services ----------
const svc = (name, title, state, words, o = {}) => ({ name, title, container: `vektor-desk-${name}`, status: state === 'up' ? 'Up 3 hours' : 'Restarting (1) 20 seconds ago', state, up_seconds: state === 'up' ? 11400 : null, exit_code: state === 'up' ? null : 1, restarted_alone: false, words, ...o });
const running = [
  svc('api', 'the app', 'up', 'The app has been running for 3 hours.'),
  svc('cron', 'the scheduler', 'up', 'The scheduler has been running for 3 hours.'),
  svc('caddy', 'the web server', 'up', 'The web server has been running for 3 hours.'),
  svc('ntfy', 'phone alerts', 'up', 'Phone alerts has been running for 3 hours.'),
  svc('tailscale', 'the Tailscale link', 'up', 'The Tailscale link has been running for 3 hours.'),
];
const status = read('status');
write('status', {
  ...status,
  containers: {
    state: 'ok',
    checked_at: '2026-11-09T16:40:00+00:00',
    fresh: true,
    note: 'All 5 desk services are running.',
    services: running,
    tailnet: { state: 'ok', kind: null, words: 'Tailscale is signed in and running on the box, at 100.64.0.10.', address: '100.64.0.10', line: null },
  },
});
const signedOut = 'The box is signed out of your tailnet. Add a new auth key in Settings, then Redeploy.';
write('status.trouble', {
  ...status,
  containers: {
    state: 'trouble',
    checked_at: '2026-11-09T16:40:00+00:00',
    fresh: true,
    note: `The Tailscale link keeps stopping and starting. ${signedOut}`,
    services: [...running.slice(0, 4), svc('tailscale', 'the Tailscale link', 'restarting', 'The Tailscale link keeps stopping and starting.')],
    tailnet: { state: 'trouble', kind: 'signed_out', words: signedOut, address: null, line: 'health(warnable=login-state): You are logged out.' },
  },
});

// ---------- first profile from a button ----------
const INIT = { method: 'POST', path: '/api/decisions/profile/init', label: 'Set up my profile from my data' };
for (const name of ['decisions.profile.status', 'decisions.profile.status.empty', 'decisions.profile.status.failing', 'decisions.profile.status.fresh', 'decisions.profile.status.never']) {
  const d = read(name);
  write(name, { ...d, init: d.exists ? null : INIT });
}

// ---------- health: what fixes itself, what needs you, what blocks ----------
const SAY = {
  value: ['blocks', 'mirror', 'Your broker’s positions and account totals for Friday do not add up, so values cannot be trusted yet. The desk is reading your accounts again.'],
  marginal_rate: ['needs_you', null, 'No tax rate yet, so after-tax figures are estimates. Open Taxes in Escape Vektor once and the desk reads it from there.'],
  shares: ['needs_you', null, 'No tax lots yet, so tax and wash-sale checks are off. Upload your Fidelity history or a lot export in Settings, Data, Inbox.'],
  symbol_kinds: ['fixes_itself', 'engine-research', 'The desk does not know yet whether 0999999 is a fund or a single stock. It is looking that up.'],
  closes: ['fixes_itself', 'engine-backfill', 'Two fund prices for Monday are not out yet. The desk checks every hour.'],
};
const counted = (c) => c.status === 'fail' || (c.status === 'warn' && c.kind !== 'fixes_itself');
const annotate = (c) => {
  if (c.status === 'ok') return { check_name: c.check_name, status: 'ok', detail: c.diagnosis || c.detail, kind: null, counts: false, job: null, heal: null, diagnosis: c.diagnosis || c.detail };
  const [kind, job, say] = SAY[c.check_name] || [c.status === 'fail' ? 'blocks' : 'needs_you', null, c.detail];
  const row = { check_name: c.check_name, status: c.status, detail: say, kind, job, heal: job ? { job, asked_at: '2026-11-09T16:35:00+00:00', attempts: 1, stuck: false } : null, diagnosis: c.diagnosis || c.detail };
  return { ...row, counts: counted(row) };
};
const healthOf = (h, checks) => {
  const kinds = Object.fromEntries(['fixes_itself', 'needs_you', 'blocks'].map((k) => [k, checks.filter((c) => c.kind === k).length]));
  return { ...h, status: !checks.length ? 'fail' : checks.some((c) => c.status === 'fail') ? 'fail' : checks.some((c) => c.counts) ? 'warn' : 'ok', kinds, checks };
};
for (const name of ['engine.health', 'engine.health.warn', 'engine.health.fail', 'engine.health.fresh', 'engine.health.never']) {
  const h = read(name);
  write(name, healthOf(h, (h.checks || []).map(annotate)));
}
const calm = read('engine.health');
write(
  'engine.health.healing',
  healthOf(
    calm,
    calm.checks.map((c) => (c.check_name === 'closes' ? annotate({ ...c, status: 'warn', diagnosis: 'Closes for FXAIX, BND stop at 2026-11-06. A fund’s price for a day can arrive hours after the others. Fix: nothing to do yet.' }) : c)),
  ),
);

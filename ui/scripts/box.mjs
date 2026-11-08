const at = (hm, day = '2026-11-09') => `${day}T${hm}:00Z`;
const STATUS_OUT = ['Vektor Desk box status', 'live image   ghcr.io/inzodious/vektor-desk:main (synthetic)', 'containers   api healthy, cron healthy', 'backups      newest Nov 9, 7:00 AM, 6 kept', 'disk         41% used on the apps pool'].join('\n');
const LAST = {
  status: ['16:20', '16:20', 'ok', 0, STATUS_OUT],
  check: ['15:02', '15:03', 'ok', 0, 'Claude sign-in ok\nFirestore read ok\nAlpaca paper ok\nTest phone alert sent'],
  backup: ['12:00', '12:04', 'ok', 0, 'Backed up 6 databases and the inbox (synthetic sizes)'],
  'restore-test': ['12:05', '12:09', 'failed', 1, 'Unpacked the newest backup\nlab.db: integrity check found 1 problem (synthetic)'],
  'update-script': ['11:35', '11:35', 'skipped', 75, 'The checkout is still catching up to main; trying again on the next pass'],
};

const lastRun = (name) => {
  const l = LAST[name];
  if (!l) return null;
  const [s, f, result, rc, out] = l;
  return { action: name, request_id: `b0${name.length}c0ffee0`, started: at(s), finished: at(f), result, exit_code: rc, output: out };
};

const script = (o) => ({ checked_at: at('16:40'), pinned: true, current: false, behind: 2, from: 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678', to: 'f9e8d7c6b5a49382716051f4e3d2c1b0a9876543', off: false, ...o });

// ---------- box actions: today, host quiet, first day, script states ----------
export function boxFixtures(api) {
  const base = { ...api, now: at('16:42'), host_alive: true, pickup_seconds: 300 };
  const idle = (a) => ({ ...a, running: false, queued: false, queued_at: null, last_run: null, cooldown_until: null, can_run: true });
  const actions = api.actions.map((a) => {
    const cooling = a.name === 'status';
    const queued = a.name === 'logs';
    return { ...idle(a), last_run: lastRun(a.name), queued, queued_at: queued ? at('16:40') : null, cooldown_until: cooling ? at('16:43') : null, can_run: !cooling && !queued };
  });
  const quiet = { ...base, host_alive: false, script: null, actions: api.actions.map(idle) };
  return {
    box: { ...base, script: script(), actions },
    'box.down': quiet,
    'box.fresh': quiet,
    'box.current': { ...base, script: script({ current: true, behind: 0, from: null, to: null }), actions },
    'box.off': { ...base, script: script({ off: true, pinned: false }), actions },
  };
}

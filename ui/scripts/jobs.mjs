const at = (hm, day = '2026-11-09') => `${day}T${hm}:00Z`;
const LAST = {
  mirror: ['13:00', '13:01', 'ok', null],
  'engine-quotes': ['16:40', '16:40', 'ok', null],
  'engine-daily': ['13:20', '13:24', 'ok', null],
  'engine-backfill': ['11:10', '11:12', 'ok', null],
  'engine-research': ['05:40', '05:43', 'failed', 'SEC answered 503 twice; it tries again tonight.'],
  'engine-lookthrough': ['07:10', '07:14', 'ok', null, '2026-11-08'],
  'engine-lots': ['16:30', '16:30', 'skipped', 'No new lot export in the inbox.'],
  'decisions-sync': ['13:10', '13:10', 'ok', null],
  'engine-french': ['08:30', '08:31', 'ok', null, '2026-11-02'],
  'notify-ops': ['14:20', '14:20', 'ok', null],
  'agents-queue-now-only': ['16:41', '16:41', 'ok', null],
};

const lastRun = (name) => {
  const l = LAST[name];
  if (!l) return null;
  const [s, f, result, detail, day] = l;
  return { trigger: name === 'mirror' ? 'request' : 'schedule', request_id: name === 'mirror' ? 'a1b2c3d4e5f6' : null, started: at(s, day), finished: at(f, day), result, exit_code: result === 'failed' ? 1 : 0, detail };
};

// ---------- jobs list: today, scheduler off, first day ----------
export function jobsFixtures(api) {
  const base = { ...api, now: at('16:42'), scheduler_alive: true };
  const jobs = api.jobs.map((j) => {
    const last = lastRun(j.name);
    const cooling = j.name === 'mirror';
    return { ...j, running: false, running_since: null, queued: false, queued_at: null, last_run: last, cooldown_until: cooling ? at('16:45') : null, can_run: !cooling };
  });
  return {
    jobs: { ...base, jobs },
    'jobs.down': { ...base, scheduler_alive: false },
    'jobs.fresh': { ...base, jobs: api.jobs.map((j) => ({ ...j, running: false, running_since: null, queued: false, queued_at: null, last_run: null, cooldown_until: null, can_run: true })) },
  };
}

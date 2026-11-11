import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const DIR = fileURLToPath(new URL('../src/fixtures/', import.meta.url));
const at = (hms, day = '2026-11-09') => `${day}T${hms}Z`;
const read = (name) => JSON.parse(readFileSync(`${DIR}${name}.json`, 'utf8'));
const write = (name, body) => {
  writeFileSync(`${DIR}${name}.json`, `${JSON.stringify(body, null, 1)}\n`);
  console.log(`wrote ${name}.json`);
};

// ---------- rows ----------
const PRINT = `3d63e0705ff21e2b${'0123456789abcdef'.repeat(3)}`;
const COMMIT = '716e2031a4b5c6d7e8f9012345678901234abcde';
const idle = { running: false, queued: false, queued_at: null, last_run: null, cooldown_until: null, can_run: true };
const DEPLOY = { name: 'deploy-now', title: 'Deploy now', what: 'Pulls main, backs up and restarts on it; also retries a commit auto-deploy is holding back', cooldown_seconds: 300, ...idle };
const APPROVE = { name: 'approve-builder', title: 'Approve builder', what: "Trusts the builders listed in main's deploy/builders.txt, so the box takes the images they sign instead of building its own", cooldown_seconds: 60, ...idle };
const block = (o = {}) => ({ state: 'none', words: 'The box builds its own images, one stage at a time.', builders: [], asking: [], listed: [], want: null, last: null, wait_seconds: 1200, settle_seconds: 600, host_seen: true, ...o });
const FROM_BOX = { commit: COMMIT, how: 'box', why: null, at: at('14:05:10') };
const FROM_BUILDER = { commit: COMMIT, how: 'builder', why: null, at: at('14:05:10') };
const LISTED = [{ fingerprint: PRINT, name: 'Horizon', approved: true }];

// ---------- states ----------
const none = block({ words: 'The box builds its own images, one stage at a time. The last image (716e203) came from this box.', last: FROM_BOX });
const unseen = block({ wait_seconds: null, settle_seconds: null, host_seen: false });
const asking = block({
  state: 'asking',
  words: "Horizon asks to build the desk's images (key 3d63 e070 5ff2 1e2b). It can once that key's fingerprint is in main's deploy/builders.txt and you tap Approve builder. The last image (716e203) came from this box.",
  asking: [{ fingerprint: PRINT, name: 'Horizon', asked_at: at('16:40:00') }],
  last: FROM_BOX,
});
const approve = block({
  state: 'approve',
  words: "Horizon is listed in main and has sent its key. Tap Approve builder to let it build the desk's images. The last image (716e203) came from this box.",
  asking: [{ fingerprint: PRINT, name: 'Horizon', asked_at: at('16:20:00') }],
  listed: [{ fingerprint: PRINT, name: 'Horizon', approved: false }],
  last: FROM_BOX,
});
const online = block({
  state: 'online',
  words: "Horizon builds the desk's images, so the box doesn't have to. The last image (716e203) came from a builder.",
  builders: [{ fingerprint: PRINT, name: 'Horizon', online: true, last_seen: at('16:41:40') }],
  listed: LISTED,
  last: FROM_BUILDER,
});
const asleep = block({
  state: 'asleep',
  words: 'Horizon is approved to build but is asleep or off (last heard 3 hours ago). The box builds here meanwhile. The last image (716e203) came from this box.',
  builders: [{ fingerprint: PRINT, name: 'Horizon', online: false, last_seen: at('13:40:00') }],
  listed: LISTED,
  last: FROM_BOX,
});

// ---------- box ----------
function withActions(box) {
  const actions = [...box.actions];
  if (!actions.some((a) => a.name === 'deploy-now')) {
    const after = actions.findIndex((a) => a.name === 'update-script');
    actions.splice(after < 0 ? actions.length : after + 1, 0, DEPLOY);
  }
  if (!actions.some((a) => a.name === 'approve-builder')) actions.push(APPROVE);
  return { ...box, actions };
}

export function buildFixtures() {
  const quiet = withActions(read('box.current'));
  const out = {};
  for (const [name, build] of Object.entries({ box: none, 'box.current': none, 'box.off': none, 'box.down': unseen, 'box.fresh': unseen })) {
    if (existsSync(`${DIR}${name}.json`)) out[name] = { ...withActions(read(name)), build };
  }
  for (const [name, build] of Object.entries({ 'box.horizon': online, 'box.asleep': asleep, 'box.asking': asking, 'box.approve': approve })) out[name] = { ...quiet, build };
  return out;
}

// ---------- jobs ----------
const RAN = { trigger: 'schedule', request_id: null, started: at('10:59:00'), finished: at('10:59:01'), result: 'ok', exit_code: 0, detail: null };

export function offerFixtures() {
  const out = {};
  for (const name of ['jobs', 'jobs.down', 'jobs.evening', 'jobs.low', 'jobs.fresh', 'jobs.never']) {
    if (!existsSync(`${DIR}${name}.json`)) continue;
    const body = read(name);
    const from = body.jobs.findIndex((j) => j.name === 'engine-lab-export');
    if (from < 0 || body.jobs.some((j) => j.name === 'engine-lab-offer')) continue;
    const ran = name !== 'jobs.fresh' && name !== 'jobs.never';
    const row = { ...body.jobs[from], name: 'engine-lab-offer', title: 'Lab work to the worker', schedules: ['* 1-5 * * *'], last_run: ran ? RAN : null };
    out[name] = { ...body, jobs: [...body.jobs.slice(0, from + 1), row, ...body.jobs.slice(from + 1)] };
  }
  return out;
}

// ---------- write ----------
for (const [name, body] of Object.entries({ ...buildFixtures(), ...offerFixtures() })) write(name, body);

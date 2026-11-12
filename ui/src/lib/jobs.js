import { ApiError, getJson, postJson } from './api.js';
import { originName } from './decisions.js';
import { etDate, etTime } from './format.js';

const WORD = {
  mirror: ['Accounts', 'Pulls balances and activity from Escape Vektor'],
  'engine-quotes': ['Prices', 'Live quotes while the market is open'],
  'engine-daily': ['Daily numbers', 'Values, drift, risk and the rule checks'],
  'engine-backfill': ['Backfill', 'Fills in missing price history'],
  'engine-research': ['Research', 'Company facts and filings'],
  'engine-lookthrough': ['Fund breakdowns', 'What each fund holds'],
  'engine-lots': ['Lots', 'Reads a new lot export from the inbox'],
  'engine-french': ['Factor library', 'Monthly factor returns for exposure'],
  'engine-lab-export': ['Lab export', 'Hands the strategy lab its data'],
  'engine-lab-offer': ['Lab work to the worker', 'Hands new experiments to a worker that is awake'],
  'engine-review': ['Results review', 'Packs up the day, week, month and year'],
  'engine-paper': ['Paper trades', 'Paper strategies place their orders'],
  'engine-discounts': ['Discount scan', 'Looks for names on sale after the close'],
  'engine-universe': ['Universe', 'Refreshes the list of names the lab can pick from'],
  'engine-filings': ['Filings', 'New SEC filings on names you follow'],
  'engine-insider': ['Insider buys', 'Insider trades from SEC forms'],
  'engine-earnings': ['Earnings dates', 'Upcoming and reported earnings'],
  'decisions-sync': ['Decision matching', 'Matches trades to your decisions'],
  'notify-ops': ['Ops alerts', 'Sends desk health to your phone'],
  'agents-triggers': ['Agent triggers', 'Wakes a desk when something moves'],
  'agents-queue': ['Agent queue', 'Overnight agent runs'],
  'agents-queue-now-only': ['Agent queue, urgent', 'Runs anything marked for now'],
  'agents-lab-reviews': ['Lab reviews', 'Agents read the strategy lab'],
};
export const DATA_JOBS = ['mirror', 'engine-quotes', 'engine-daily', 'engine-backfill', 'engine-research', 'engine-lookthrough', 'engine-lots', 'decisions-sync', 'engine-french'];
const REFRESH_ORDER = ['mirror', 'engine-backfill', 'engine-daily', 'engine-research', 'engine-lots'];
const DOW = ['Sundays', 'Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays'];
const MONTH = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const POLL_MS = 3000;
const WAIT_MS = 45 * 60 * 1000;

// ---------- words ----------
export function jobWord(job) {
  const name = job?.name || '';
  if (WORD[name]) return { title: WORD[name][0], blurb: WORD[name][1] };
  const desk = /^agents-run-(.+)$/.exec(name);
  if (desk) {
    const known = originName(desk[1]);
    const raw = desk[1].replace(/_/g, ' ');
    const title = known === desk[1] ? `${raw[0].toUpperCase()}${raw.slice(1)} desk` : /desk$/i.test(known) ? known : `${known} desk`;
    return { title, blurb: 'An agent desk run' };
  }
  return { title: job?.title || name, blurb: null };
}

export function stepTitle(step) {
  return WORD[step?.job]?.[0] || step?.title || jobWord({ name: step?.job || step?.id }).title;
}

function clock(h, m) {
  const ap = h < 12 ? 'AM' : 'PM';
  const hh = h % 12 || 12;
  return m ? `${hh}:${String(m).padStart(2, '0')} ${ap}` : `${hh} ${ap}`;
}

function nums(part) {
  if (!/^[\d,]+$/.test(part)) return null;
  return part.split(',').map(Number);
}

export function cronWords(line) {
  const f = String(line || '').trim().split(/\s+/);
  if (f.length !== 5) return line || '';
  const [mi, hr, dom, monField, dow] = f;
  const mr = /^(\d+)-(\d+)$/.exec(monField);
  const months = monField === '*' ? '' : mr ? `, ${MONTH[+mr[1]]} to ${MONTH[+mr[2]]}` : nums(monField)?.length === 1 ? ` in ${MONTH[nums(monField)[0]]}` : null;
  if (months === null) return line;
  const days = dow === '*' ? '' : dow === '1-5' ? ' on weekdays' : nums(dow)?.length === 1 ? ` on ${DOW[nums(dow)[0] % 7]}` : null;
  const step = /^\*\/(\d+)$/.exec(mi);
  if (mi === '*' && dom === '*' && days !== null) {
    const range = /^(\d+)-(\d+)$/.exec(hr);
    const span = hr === '*' ? '' : range ? `, ${clock(+range[1], 0)} to ${clock((+range[2] + 1) % 24, 0)}` : null;
    if (span !== null) return `Every minute${span}${days}${months}`;
  }
  if (step && dom === '*' && days !== null) {
    const range = /^(\d+)-(\d+)$/.exec(hr);
    const span = hr === '*' ? '' : range ? `, ${clock(+range[1], 0)} to ${clock(+range[2], 0)}` : null;
    if (span !== null) return `Every ${step[1]} min${span}${days}${months}`;
  }
  const m = nums(mi);
  const hs = nums(hr);
  const range = /^(\d+)-(\d+)$/.exec(hr);
  if (m?.length === 1 && range && dom === '*' && days !== null) return `Hourly at :${String(m[0]).padStart(2, '0')}, ${clock(+range[1], 0)} to ${clock(+range[2], 0)}${days}${months}`;
  if (m?.length === 1 && hs && days !== null) {
    const at = hs.map((h) => clock(h, m[0])).join(' and ');
    if (dom === '*') return `${hs.length === 1 && !days && !months ? 'Daily at ' : ''}${at}${days}${months}`;
    if (nums(dom)?.length === 1 && !months) return `Monthly on day ${dom} at ${at}`;
  }
  return line;
}

export function scheduleWords(job) {
  return (job?.schedules || []).map(cronWords).join('; ') || 'Only when asked';
}

function when(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const today = etDate(new Date()) === etDate(d);
  return today ? etTime(d) : `${etDate(d)}, ${etTime(d)}`;
}

// ---------- state ----------
const WAITING = {
  memory: 'low-memory mode runs heavy jobs one at a time',
  night: 'the overnight run goes one step at a time',
};

function waitingWhy(reason, lead, sentence = false) {
  const why = reason === undefined ? WAITING.memory : WAITING[reason];
  if (!why) return '';
  return sentence ? `${lead}${why[0].toUpperCase()}${why.slice(1)}.` : `${lead}${why}`;
}

export function plainLine(text) {
  if (typeof text !== 'string') return null;
  const line = text.trim();
  if (!line || /^[[{]/.test(line) || /^Traceback\b/.test(line)) return null;
  return line;
}

export function jobState(job) {
  if (!job) return { state: 'unknown', line: '' };
  const last = job.last_run;
  if (job.running) return { state: 'running', line: `Running since ${when(job.running_since) || 'just now'}` };
  if (job.waiting) return { state: 'waiting', line: `Waiting for its turn${when(job.waiting_since) ? ` since ${when(job.waiting_since)}` : ''}${waitingWhy(job.waiting_for, ': ')}` };
  if (job.queued) return { state: 'queued', line: 'Starting in a few seconds' };
  if (!last) return { state: 'never', line: 'Hasn’t run since the desk started' };
  const at = when(last.finished || last.started);
  const by = last.trigger === 'request' ? ', on request' : last.trigger === 'start' ? ', from Start the desk' : '';
  if (last.result === 'ok' && last.note) return { state: 'skipped', line: `Skipped ${at}${by}: ${last.note}` };
  if (last.result === 'ok') return { state: 'ok', line: `Ran ${at}${by}`, did: plainLine(last.did) };
  const why = last.error || last.detail;
  if (last.result === 'failed') return { state: 'failed', line: `Didn’t finish ${at}${by}${why ? `: ${why}` : ''}` };
  if (last.result === 'skipped') return { state: 'skipped', line: `Skipped ${at}${last.detail ? `: ${last.detail}` : ''}` };
  return { state: 'ok', line: `Last ran ${at}` };
}

export function cooldownText(job) {
  if (!job?.cooldown_until) return null;
  return `Again at ${when(job.cooldown_until)}`;
}

export function splitJobs(jobs = []) {
  const byName = Object.fromEntries((jobs || []).map((j) => [j.name, j]));
  const main = DATA_JOBS.map((n) => byName[n]).filter(Boolean);
  const rest = (jobs || []).filter((j) => !DATA_JOBS.includes(j.name));
  return { main, rest };
}

export function refreshPlan(health, jobs = []) {
  const checks = health?.checks || [];
  const level = checks.some((c) => c.status === 'fail') ? 'fail' : 'warn';
  const bad = new Set(checks.filter((c) => c.status === level).map((c) => c.check_name));
  const hits = (jobs || []).filter((j) => (j.refreshes || []).some((c) => bad.has(c))).map((j) => j.name);
  return REFRESH_ORDER.filter((n) => hits.includes(n));
}

export const AUTO_EVERY_MS = 2 * 60 * 60 * 1000;

export function autoPlan(health, jobs = [], stamps = {}, now = Date.now()) {
  const byName = Object.fromEntries((jobs || []).map((j) => [j.name, j]));
  return refreshPlan(health, jobs).filter((name) => {
    const j = byName[name];
    if (!j || j.can_run === false || j.running || j.queued || j.waiting) return false;
    const last = Number(stamps?.[name]);
    return !(last > 0) || now - last >= AUTO_EVERY_MS;
  });
}

export function refusalText(err) {
  const body = err?.body || {};
  if (body.error === 'cooldown') return `Asked for a moment ago. ${body.cooldown_until ? `Try again at ${when(body.cooldown_until)}.` : 'Try again in a few minutes.'}`;
  if (body.error === 'waiting') return `It’s already waiting for its turn.${waitingWhy(body.waiting_for, ' ', true)}`;
  if (body.error === 'scheduler_down') return 'The scheduler is taking a break, so nothing would pick this up. It’s back once the cron service runs.';
  if (body.error === 'unknown_job') return 'The desk doesn’t know that job any more. Refresh the page.';
  return err?.message || 'The desk didn’t take that. Try again in a moment.';
}

// ---------- running ----------
const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(id);
      reject(new DOMException('aborted', 'AbortError'));
    });
  });

export async function runAndWait(name, { signal, poll = POLL_MS, onState } = {}) {
  let id = null;
  try {
    id = (await postJson(`/api/jobs/${encodeURIComponent(name)}/run`)).request_id;
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 409) throw e;
  }
  const end = Date.now() + WAIT_MS;
  while (Date.now() < end) {
    await sleep(poll, signal);
    const job = ((await getJson('/api/jobs', { signal })).jobs || []).find((j) => j.name === name);
    if (!job) throw new ApiError(404, 'The desk doesn’t know that job any more.');
    onState?.(job);
    const last = job.last_run;
    if (id ? last?.request_id === id && last.finished : !job.running && !job.queued && !job.waiting) return last;
  }
  throw new ApiError(0, 'Still going after 45 minutes. Settings › Jobs shows how it ends.');
}

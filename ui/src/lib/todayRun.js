import { jobWord } from './jobs.js';
import { etDate, etTime } from './format.js';

const ET = 'America/New_York';
const DOW = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

export const STAGES = [
  { id: 'accounts', title: 'Accounts', blurb: 'Balances and activity come in', match: (n) => n === 'mirror' },
  { id: 'numbers', title: 'Numbers', blurb: 'Values, drift, risk and plan checks', match: (n) => n === 'engine-daily' },
  { id: 'review', title: 'Review', blurb: 'The day’s results and debrief', match: (n) => /^engine-reviews?$/.test(n) || /debrief/.test(n) },
  { id: 'desks', title: 'Desks', blurb: 'Agent desks read the day', match: (n) => /^agents-run-/.test(n) && !/debrief/.test(n) },
  { id: 'paper', title: 'Paper', blurb: 'Paper strategies place their trades', match: (n) => n === 'engine-paper' },
];

export const STATE = {
  ok: { t: 'Done', tone: 'ok' },
  running: { t: 'Running', tone: 'info' },
  failed: { t: 'Needs a look', tone: 'watch' },
  waiting: { t: 'Later today', tone: '' },
  idle: { t: 'Not today', tone: '' },
  soon: { t: 'Not on this box yet', tone: '' },
};

// ---------- Eastern clock ----------
export function etParts(date) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', { timeZone: ET, weekday: 'short', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' }).formatToParts(date).map((p) => [p.type, p.value]),
  );
  return { dow: DOW[parts.weekday], month: Number(parts.month), day: Number(parts.day), minutes: Number(parts.hour) * 60 + Number(parts.minute), key: `${parts.year}-${parts.month}-${parts.day}` };
}

function field(text, lo, hi) {
  const out = new Set();
  for (const part of String(text).split(',')) {
    const m = /^(\*|\d+)(?:-(\d+))?(?:\/(\d+))?$/.exec(part);
    if (!m) return null;
    const from = m[1] === '*' ? lo : Number(m[1]);
    const to = m[1] === '*' ? hi : m[2] != null ? Number(m[2]) : m[3] != null ? hi : from;
    const step = m[3] != null ? Number(m[3]) : 1;
    if (!step || from > to) return null;
    for (let v = from; v <= to; v += step) out.add(v);
  }
  return out;
}

export function runsToday(line, now) {
  const f = String(line || '').trim().split(/\s+/);
  if (f.length !== 5) return [];
  const [mi, hr, dom, mon, dow] = [field(f[0], 0, 59), field(f[1], 0, 23), field(f[2], 1, 31), field(f[3], 1, 12), field(f[4], 0, 7)];
  if (!mi || !hr || !dom || !mon || !dow) return [];
  if (mi.size > 4) return [];
  const t = etParts(now);
  if (!mon.has(t.month) || !dom.has(t.day) || !(dow.has(t.dow) || (t.dow === 0 && dow.has(7)))) return [];
  const out = [];
  hr.forEach((h) => mi.forEach((m) => out.push(h * 60 + m)));
  return out.sort((a, b) => a - b);
}

export function clockText(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}

// ---------- one job today ----------
export function jobToday(job, now) {
  const today = etParts(now);
  const last = job.last_run;
  const at = last ? new Date(last.finished || last.started) : null;
  const ranToday = Boolean(at) && !Number.isNaN(at.getTime()) && etParts(at).key === today.key;
  const due = (job.schedules || []).flatMap((s) => runsToday(s, now)).filter((m) => m > today.minutes);
  const next = due.length ? Math.min(...due) : null;
  let state = 'idle';
  if (job.running || job.queued) state = 'running';
  else if (ranToday && last.result === 'failed') state = 'failed';
  else if (next != null) state = 'waiting';
  else if (ranToday) state = 'ok';
  return { job, title: jobWord(job).title, state, ranToday, at, result: last?.result || null, detail: last?.detail || null, next };
}

// ---------- stages ----------
function stageLine(state, rows) {
  const many = rows.length > 1;
  const ran = rows.filter((r) => r.ranToday && r.result !== 'failed');
  const latest = [...ran].sort((a, b) => b.at - a.at)[0];
  const ranText = many && ran.length ? `${ran.length} ran · ` : '';
  if (state === 'soon') return 'Arrives with the next desk update';
  if (state === 'running') {
    const r = rows.find((x) => x.state === 'running');
    return many ? `${r.title} is running` : 'Running now';
  }
  if (state === 'failed') {
    const r = rows.find((x) => x.state === 'failed');
    return `${many ? `${r.title} didn’t` : 'Didn’t'} finish ${etTime(r.at)}`;
  }
  if (state === 'waiting') {
    const r = rows.filter((x) => x.next != null).sort((a, b) => a.next - b.next)[0];
    const prior = !many && latest ? `Ran ${etTime(latest.at)} · ` : ranText;
    return `${prior}${many ? `${r.title} ` : 'Next '}${clockText(r.next)}`;
  }
  if (state === 'ok') {
    if (latest.result === 'skipped' && !many) return `Nothing new ${etTime(latest.at)}`;
    return many ? `${ran.length} ran, last ${etTime(latest.at)}` : `Ran ${etTime(latest.at)}`;
  }
  const seen = rows.filter((r) => r.at && !Number.isNaN(r.at.getTime())).sort((a, b) => b.at - a.at)[0];
  return seen ? `Last ran ${etDate(seen.at)}` : 'Nothing scheduled today';
}

export function stageToday(stage, jobs, now) {
  const rows = (jobs || []).filter((j) => stage.match(j.name)).map((j) => jobToday(j, now));
  let state = 'soon';
  if (rows.length) {
    const has = (s) => rows.some((r) => r.state === s);
    state = has('running') ? 'running' : has('failed') ? 'failed' : has('waiting') ? 'waiting' : has('ok') ? 'ok' : 'idle';
  }
  return { id: stage.id, title: stage.title, blurb: stage.blurb, state, word: STATE[state], line: stageLine(state, rows), jobs: rows.map((r) => r.job.name) };
}

export function todayRun(data, fallbackNow = new Date()) {
  const parsed = data?.now ? new Date(data.now) : null;
  const now = parsed && !Number.isNaN(parsed.getTime()) ? parsed : fallbackNow;
  const stages = STAGES.map((s) => stageToday(s, data?.jobs, now));
  const live = stages.filter((s) => s.state !== 'soon' && s.state !== 'idle');
  const done = live.filter((s) => s.state === 'ok').length;
  const failed = stages.filter((s) => s.state === 'failed').length;
  const running = stages.some((s) => s.state === 'running');
  let head = !live.length ? 'Quiet day' : done ? `${done} of ${live.length} done` : 'More to run today';
  let tone = '';
  if (data && data.scheduler_alive === false) {
    head = 'Scheduler isn’t answering';
    tone = 'watch';
  } else if (failed) {
    head = `${failed === 1 ? '1 stage needs' : `${failed} stages need`} a look`;
    tone = 'watch';
  } else if (running) {
    head = 'Running now';
    tone = 'info';
  } else if (live.length && done === live.length) {
    head = 'All done today';
    tone = 'ok';
  }
  return { stages, head, tone, done, total: live.length };
}

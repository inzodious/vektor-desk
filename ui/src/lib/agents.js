export const RUN_STATUS = {
  ok: { t: 'Ran fine', tone: 'ok' },
  running: { t: 'Running now', tone: 'info' },
  failed: { t: 'Failed', tone: 'watch' },
  timeout: { t: 'Timed out', tone: 'watch' },
  deferred: { t: 'Deferred', tone: '' },
  busy: { t: 'Skipped, desk busy', tone: '' },
  disabled: { t: 'Off', tone: '' },
  over_budget: { t: 'Over the weekly cap', tone: 'watch' },
  not_ready: { t: 'Not ready yet', tone: '' },
  unchanged: { t: 'Nothing new', tone: '' },
};

export const TRIGGER = { schedule: 'scheduled', after_proposal: 'after a proposal', console: 'from the Console', manual: 'run by hand' };

const WATCH = /\b(behind|drift(?:ed)?\s+(?:past|over)|over (?:the|its)|past (?:the|its)|margin|light|heavy|needs you|stale|late|breaks?|outside|cap)\b/i;
const GOOD = /\b(ahead|nothing needs you|all clear|inside the|on target|all \d+ rules|holds?)\b/i;
const MONEY = /\$\d|cash|deposit/i;

export function briefTone(line) {
  if (GOOD.test(line) && !/\bbehind\b/i.test(line)) return 'ok';
  if (WATCH.test(line)) return 'watch';
  if (MONEY.test(line)) return 'info';
  return 'info';
}

export function briefLines(summary) {
  if (!summary) return [];
  return summary
    .split(/\n+/)
    .map((l) => l.replace(/^\s*[-*•]\s*/, '').trim())
    .filter(Boolean)
    .slice(0, 6)
    .map((text) => {
      const m = text.match(/^(.{6,70}?[.:;])\s+(.+)$/);
      return { tone: briefTone(text), lead: m ? m[1] : text, rest: m ? m[2] : '' };
    });
}

export function usageShare(week) {
  if (!week || !week.cap) return 0;
  return Math.min(1, week.runs / week.cap);
}

const ET = 'America/New_York';
const dayKey = (d) => new Intl.DateTimeFormat('en-CA', { timeZone: ET, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);

export function whenLabel(iso, now = new Date()) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const time = new Intl.DateTimeFormat('en-US', { timeZone: ET, hour: 'numeric', minute: '2-digit' }).format(d);
  const days = Math.round((Date.parse(dayKey(d)) - Date.parse(dayKey(now))) / 86400000);
  if (days === 0) return `Today ${time}`;
  if (days === 1) return `Tomorrow ${time}`;
  if (days === -1) return `Yesterday ${time}`;
  if (Math.abs(days) < 7) return `${new Intl.DateTimeFormat('en-US', { timeZone: ET, weekday: 'short' }).format(d)} ${time}`;
  return `${new Intl.DateTimeFormat('en-US', { timeZone: ET, month: 'short', day: 'numeric' }).format(d)}, ${time}`;
}

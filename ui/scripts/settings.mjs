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
  const { starter, ...rest } = d;
  write(name, { ...rest, defaults: after(d.defaults || [], 'margin.rate_pct', 'growth.fi_target_from_plan'), margin: { rate_pct: RATE, source: 'default' }, starter });
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

// ---------- fields ----------
export const GROUPS = [
  {
    id: 'growth',
    title: 'Growth',
    sub: 'How far out the desk plans, and which way it leans.',
    fields: [
      { key: 'growth.horizon_years', label: 'Horizon, years', kind: 'num', min: 0, max: 80 },
      {
        key: 'growth.tilt',
        label: 'Tilt',
        kind: 'pick',
        options: [
          { v: 'growth', t: 'Growth' },
          { v: 'balanced', t: 'Balanced' },
          { v: 'income', t: 'Income' },
        ],
      },
    ],
  },
  {
    id: 'opportunity',
    title: 'New ideas',
    sub: 'How much room ideas get, how many, and how sure Research must be.',
    fields: [
      { key: 'opportunity.satellite_cap_pct', label: 'Room for ideas %', kind: 'num', min: 0, max: 100 },
      { key: 'opportunity.ideas_per_month', label: 'Ideas a month', kind: 'num', min: 0, max: 50, int: true },
      { key: 'opportunity.min_confidence', label: 'Least sure %', kind: 'pct', min: 0, max: 100 },
    ],
  },
  {
    id: 'tax',
    title: 'Taxes',
    sub: 'When a loss is worth harvesting and which lots sell first.',
    fields: [
      { key: 'tax.harvest_threshold_usd', label: 'Harvest over $', kind: 'num', min: 0 },
      {
        key: 'tax.lot_method',
        label: 'Sells',
        kind: 'pick',
        options: [
          { v: 'highest_cost', t: 'Highest cost' },
          { v: 'tax_efficient', t: 'Tax efficient' },
          { v: 'lowest_cost', t: 'Lowest cost' },
          { v: 'fifo', t: 'Oldest first' },
          { v: 'lifo', t: 'Newest first' },
        ],
      },
      { key: 'tax.year_end_start', label: 'Year-end review from (MM-DD)', kind: 'mmdd' },
    ],
  },
  {
    id: 'margin',
    title: 'Borrowing',
    sub: 'The yearly rate your broker charges on a margin loan. The desk uses it to cost what you borrow.',
    fields: [{ key: 'margin.rate_pct', label: 'Margin rate, % a year', kind: 'num', min: 0, max: 40 }],
  },
  {
    id: 'industry_focus',
    title: 'Focus',
    sub: 'Themes Research and Scout look at first, and what they leave out. Commas between.',
    fields: [
      { key: 'industry_focus.themes', label: 'Themes', kind: 'themes', placeholder: 'space, semiconductors' },
      { key: 'industry_focus.exclude', label: 'Leave out', kind: 'list', placeholder: 'tobacco, ACME' },
    ],
  },
  {
    id: 'alerts',
    title: 'Alerts',
    sub: 'The quietest alert that still reaches your phone.',
    fields: [
      {
        key: 'alerts.min_priority',
        label: 'Push from',
        kind: 'pick',
        options: [
          { v: 'min', t: 'Everything' },
          { v: 'low', t: 'Low and up' },
          { v: 'default', t: 'Normal and up' },
          { v: 'high', t: 'High and up' },
          { v: 'urgent', t: 'Urgent only' },
        ],
      },
    ],
  },
];

export const FIELDS = GROUPS.flatMap((g) => g.fields);

// ---------- reading ----------
export function getAt(obj, key) {
  return key.split('.').reduce((node, k) => (node && typeof node === 'object' ? node[k] : undefined), obj);
}

const split = (text) =>
  String(text || '')
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);

export function toText(field, value) {
  if (value == null) return '';
  if (field.kind === 'pct') return String(Math.round(Number(value) * 1000) / 10);
  if (field.kind === 'themes') return (value || []).map((t) => (typeof t === 'string' ? t : t?.name)).filter(Boolean).join(', ');
  if (field.kind === 'list') return (value || []).join(', ');
  return String(value);
}

export function formFrom(profile) {
  return Object.fromEntries(FIELDS.map((f) => [f.key, toText(f, getAt(profile, f.key))]));
}

// ---------- parsing ----------
export function parseField(field, text, current) {
  const t = String(text ?? '').trim();
  if (field.kind === 'pick') return { value: t };
  if (field.kind === 'list') return { value: split(t) };
  if (field.kind === 'themes') {
    const old = Object.fromEntries((current || []).filter((x) => x && typeof x === 'object').map((x) => [String(x.name).toLowerCase(), x]));
    const names = split(t).filter((name, i, all) => all.findIndex((x) => x.toLowerCase() === name.toLowerCase()) === i);
    return { value: names.map((name) => old[name.toLowerCase()] ? { ...old[name.toLowerCase()], name } : { name }) };
  }
  if (field.kind === 'mmdd') {
    const m = /^(\d{2})-(\d{2})$/.exec(t);
    if (!m || Number(m[1]) < 1 || Number(m[1]) > 12 || Number(m[2]) < 1 || Number(m[2]) > 31) return { error: 'Use MM-DD, like 12-01.' };
    return { value: t };
  }
  if (!t) return { error: 'Needs a number.' };
  const n = Number(t);
  if (!Number.isFinite(n)) return { error: 'Needs a number.' };
  if (field.int && !Number.isInteger(n)) return { error: 'Whole numbers only.' };
  if (field.min != null && n < field.min) return { error: `${field.min} or more.` };
  if (field.max != null && n > field.max) return { error: `${field.max} or less.` };
  return { value: field.kind === 'pct' ? Math.round(n * 10) / 1000 : n };
}

const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

export function changesFrom(profile, form, editable = null) {
  const changes = {};
  const errors = {};
  FIELDS.forEach((f) => {
    const [section, ...rest] = f.key.split('.');
    if (editable && !editable.includes(section)) return;
    const current = getAt(profile, f.key);
    if (form[f.key] === toText(f, current)) return;
    const out = parseField(f, form[f.key], current);
    if (out.error) {
      errors[f.key] = out.error;
      return;
    }
    if (same(out.value, current)) return;
    changes[section] = { ...(changes[section] || {}), [rest.join('.')]: out.value };
  });
  return { changes, errors };
}

export function changeCount(changes) {
  return Object.values(changes || {}).reduce((n, s) => n + Object.keys(s).length, 0);
}

export function lockedGroups(editable) {
  if (!editable) return [];
  return GROUPS.filter((g) => !editable.includes(g.id)).map((g) => g.id);
}

// ---------- words ----------
export function savedLine(r) {
  if (!r?.changed) return 'Nothing changed.';
  const n = (r.sections || []).length;
  return `Saved ${n === 1 ? '1 section' : `${n} sections`} as profile v${r.version}. A backup was kept.`;
}

export function pendingLine(n) {
  if (!n) return 'No changes yet';
  return n === 1 ? '1 change to save' : `${n} changes to save`;
}

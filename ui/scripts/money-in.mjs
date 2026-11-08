const free = (id, date, account, amount) => ({
  id: `money-in-${id}`,
  date,
  account,
  amount_usd: amount,
  status: 'landed',
  landed: { activity_id: id, date, accountKey: account, amount, activity_ids: [id] },
  scheduled: false,
  mode: 'auto',
});

// ---------- deposit scenarios: auto with a rhythm, auto with none, a listed schedule ----------
export function moneyInFixtures(profile, deposits) {
  const items = deposits.deposits || [];
  const series = Array.isArray(profile.profile?.deposits) ? profile.profile.deposits : [];
  const main = series.find((d) => /^individual/.test(d.account || '')) || series[0] || {};
  const account = main.account || 'individual-0001';
  const extra = [free('2026-11-05-transfer-1', '2026-11-05', account, 250), free('2026-10-28-transfer-1', '2026-10-28', account, 1200)];
  const byDate = (a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id);
  const listed = series.map((d) => ({ id: d.id, account: d.account, cadence: d.cadence, days: d.days, amount_usd: d.amount_usd }));
  const relabel = (d) => ({ ...d, mode: 'listed' });
  return {
    'decisions.profile': { ...profile, deposits_mode: 'auto' },
    'decisions.deposits': { deposits: [...items, extra[0]].sort(byDate) },
    'decisions.profile.quiet': { ...profile, deposits_mode: 'auto', profile: { ...profile.profile, deposits: [] } },
    'decisions.deposits.quiet': { deposits: extra.sort(byDate) },
    'decisions.profile.listed': { ...profile, deposits_mode: 'listed', profile: { ...profile.profile, deposits: listed } },
    'decisions.deposits.listed': {
      deposits: [
        ...items.filter((d) => d.scheduled !== false).map(relabel),
        { id: main.id || 'payday', date: '2026-10-20', account, amount_usd: main.amount_usd ?? 500, status: 'late', landed: null, scheduled: true, mode: 'listed' },
      ].sort(byDate),
    },
    'decisions.profile.fresh': { ...profile, deposits_mode: 'auto', profile: { ...profile.profile, deposits: [] } },
    'decisions.deposits.fresh': { deposits: [] },
  };
}

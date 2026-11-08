// ---------- inbox listing: one export waiting, empty ----------
export function inboxFixtures() {
  const base = { max_bytes: 25 * 1024 * 1024, suffixes: ['.json', '.csv'] };
  const files = [
    { name: 'lots-2026-11-09.csv', size: 18342, modified: '2026-11-09T14:05:00Z' },
    { name: 'lots-2026-10-12.csv', size: 17710, modified: '2026-10-12T13:30:00Z' },
  ];
  const at = (f) => ({ ...base, brokers: { fidelity: { import_job: 'engine-lots', files: f } } });
  return { inbox: at(files), 'inbox.fresh': at([]), 'inbox.empty': at([]) };
}

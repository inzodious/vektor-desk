import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from '@playwright/test';

const base = process.env.SCREENS_URL || 'http://localhost:4318';
const out = process.argv[2] || 'screens';
const only = process.argv[3] ? process.argv[3].split(',') : null;
const WIDTHS = [1920, 1440, 390];
const THEMES = ['light', 'dark'];
const MONDAY = new Date('2026-11-09T16:42:00Z');
const SHOTS = [
  { name: 'bridge', path: '/', fixtures: true, clock: MONDAY },
  { name: 'bridge-sheet', path: '/', fixtures: true, clock: MONDAY, act: async (p) => p.locator('.board-row[data-sym="FTEC"]').click() },
  { name: 'bridge-demo', path: '/' },
  { name: 'research', path: '/research', fixtures: true, clock: MONDAY, full: true },
  { name: 'research-acme', path: '/research?s=ACME', fixtures: true, clock: MONDAY, full: true },
  { name: 'research-nova', path: '/research?s=NOVA', fixtures: true, clock: MONDAY, full: true },
  { name: 'research-empty', path: '/research?scenario=empty', fixtures: true, clock: MONDAY },
  { name: 'research-sources', path: '/research/sources', fixtures: true, clock: MONDAY },
  { name: 'research-watchlist', path: '/research/watchlist', fixtures: true, clock: MONDAY },
  { name: 'research-calendar', path: '/research/calendar', fixtures: true, clock: MONDAY },
  { name: 'research-demo', path: '/research' },
  { name: 'console', path: '/research', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('console-open').click() },
  { name: 'console-refresh', path: '/research', fixtures: true, clock: MONDAY, act: async (p) => p.getByRole('button', { name: 'Refresh now' }).click() },
  { name: 'search', path: '/', fixtures: true, clock: MONDAY, act: async (p) => { await p.getByTestId('search-open').click(); await p.waitForTimeout(100); await p.keyboard.type('n'); } },
  { name: 'sheet-nova', path: '/research/watchlist', fixtures: true, clock: MONDAY, act: async (p) => p.locator('tr[data-watch="NOVA"] [data-sym]').click() },
  { name: 'decisions', path: '/decisions', fixtures: true, clock: MONDAY },
  { name: 'decisions-blocked', path: '/decisions', fixtures: true, clock: MONDAY, full: true, act: async (p) => p.locator('.prop', { hasText: 'ACME' }).first().click() },
  { name: 'decisions-flagged', path: '/decisions', fixtures: true, clock: MONDAY, full: true, act: async (p) => p.locator('.prop', { hasText: 'Trim' }).first().click() },
  { name: 'decisions-empty', path: '/decisions?scenario=empty', fixtures: true, clock: MONDAY },
  { name: 'decisions-demo', path: '/decisions' },
  { name: 'journal', path: '/decisions/journal', fixtures: true, clock: MONDAY },
  { name: 'journal-demo', path: '/decisions/journal' },
  { name: 'flight', path: '/decisions/flight' },
  { name: 'plan', path: '/plan', fixtures: true, clock: MONDAY },
  { name: 'plan-demo', path: '/plan' },
  { name: 'bridge-drift', path: '/', fixtures: true, clock: MONDAY, act: async (p) => p.locator('[data-kpi="plan.drift_max"]').click() },
  { name: 'bridge-excess', path: '/', fixtures: true, clock: MONDAY, act: async (p) => p.locator('[data-kpi="bm.excess"]').click() },
  { name: 'lab', path: '/lab', fixtures: true, clock: MONDAY, full: true },
  { name: 'lab-funds', path: '/lab?ids=FXAIX,FTEC,VXUS', fixtures: true, clock: MONDAY, full: true },
  { name: 'lab-add', path: '/lab', fixtures: true, clock: MONDAY, act: async (p) => p.getByRole('button', { name: 'Add an item' }).click() },
  { name: 'lab-one', path: '/lab?ids=portfolio', fixtures: true, clock: MONDAY },
  { name: 'lab-demo', path: '/lab' },
  { name: 'lab-risk', path: '/lab/risk', fixtures: true, clock: MONDAY, full: true },
  { name: 'lab-risk-drawer', path: '/lab/risk', fixtures: true, clock: MONDAY, act: async (p) => p.locator('[data-kpi="risk.vol"]').click() },
  { name: 'lab-risk-demo', path: '/lab/risk' },
  { name: 'lab-strategies', path: '/lab/strategies', fixtures: true, clock: MONDAY, full: true },
  { name: 'lab-strategies-empty', path: '/lab/strategies?scenario=empty', fixtures: true, clock: MONDAY },
  { name: 'lab-strategy-paper', path: '/lab/strategies/sector-momentum', fixtures: true, clock: MONDAY, full: true },
  { name: 'lab-strategy-lab', path: '/lab/strategies/low-vol-sectors', fixtures: true, clock: MONDAY, full: true },
  { name: 'lab-strategy-failed', path: '/lab/strategies/dip-buyer', fixtures: true, clock: MONDAY, full: true },
  { name: 'lab-rule', path: '/lab/strategies/dip-margin', fixtures: true, clock: MONDAY, full: true },
  { name: 'lab-strategy-rejected', path: '/lab/strategies/pick-one', fixtures: true, clock: MONDAY },
  { name: 'lab-strategy-missing', path: '/lab/strategies/nobody', fixtures: true, clock: MONDAY },
  { name: 'lab-boards', path: '/lab/boards', fixtures: true, clock: MONDAY, act: async (p) => { await p.goto(p.url().replace('/lab/boards?', '/lab?'), { waitUntil: 'networkidle' }); await p.getByTestId('save-board').click(); await p.goto(p.url().replace('/lab?', '/lab/boards?'), { waitUntil: 'networkidle' }); } },
  { name: 'lab-patterns', path: '/lab/patterns' },
  { name: 'settings', path: '/settings' },
  { name: 'settings-crew', path: '/settings', fixtures: true, clock: MONDAY },
  { name: 'plan-table', path: '/plan', fixtures: true, clock: MONDAY, full: true, act: async (p) => p.getByTestId('tax-calendar').getByRole('button', { name: 'Table view' }).click() },
  { name: 'bridge-nobrief', path: '/?scenario=empty', fixtures: true, clock: MONDAY },
  { name: 'settings-tables', path: '/settings', act: async (p) => p.getByTestId('mirror-row').click() },
  { name: 'settings-theme', path: '/settings', act: async (p) => p.getByRole('button', { name: /^Theme/ }).click() },
  { name: 'settings-failing', path: '/settings?scenario=failing', fixtures: true },
  { name: 'settings-offline', path: '/settings', offline: true },
];

mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined });
const report = [];
for (const shot of SHOTS.filter((s) => !only || only.includes(s.name))) {
  for (const width of WIDTHS) {
    for (const theme of THEMES) {
      const ctx = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 }, deviceScaleFactor: 1, hasTouch: width === 390, reducedMotion: 'reduce' });
      const page = await ctx.newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('console', (m) => m.type() === 'error' && !shot.offline && !m.text().includes('status of 404') && errors.push(m.text()));
      if (shot.clock) await page.clock.setFixedTime(shot.clock);
      if (shot.offline) await page.route('**/api/**', (r) => r.fulfill({ status: 503, body: '{}' }));
      const url = `${shot.fixtures ? process.env.SCREENS_FIXTURE_URL || base : base}${shot.path}${shot.path.includes('?') ? '&' : '?'}theme=${theme}`;
      await page.goto(url, { waitUntil: 'networkidle' });
      await page.evaluate(() => document.fonts.ready);
      if (shot.act) {
        await shot.act(page);
        await page.waitForTimeout(400);
      }
      const o = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, view: window.innerWidth }));
      const file = join(out, `${shot.name}-${width}-${theme}.png`);
      await page.screenshot({ path: file, fullPage: shot.full ?? !shot.act });
      report.push({ file, overflow: o.scroll > o.view, errors });
      await ctx.close();
    }
  }
}
await browser.close();
const bad = report.filter((r) => r.overflow || r.errors.length);
console.log(`${report.length} screens, ${bad.length} with problems`);
bad.forEach((b) => console.log(b.file, b.overflow ? 'OVERFLOW' : '', b.errors.join(' | ')));
process.exit(bad.length ? 1 : 0);

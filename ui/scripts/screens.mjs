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
  {
    name: 'sheet-acme',
    path: '/',
    fixtures: true,
    clock: MONDAY,
    act: async (p) => {
      await p.locator('.board-row[data-sym="ACME"]').click();
      await p.getByTestId('sheet-filing').scrollIntoViewIfNeeded();
    },
  },
  { name: 'sheet-nova', path: '/research/watchlist', fixtures: true, clock: MONDAY, act: async (p) => p.locator('tr[data-watch="NOVA"] [data-sym]').click() },
  { name: 'decisions', path: '/decisions', fixtures: true, clock: MONDAY },
  { name: 'decisions-blocked', path: '/decisions', fixtures: true, clock: MONDAY, full: true, act: async (p) => p.locator('.prop', { hasText: 'ACME' }).first().click() },
  { name: 'decisions-flagged', path: '/decisions', fixtures: true, clock: MONDAY, full: true, act: async (p) => p.locator('.prop', { hasText: 'Trim' }).first().click() },
  { name: 'decisions-empty', path: '/decisions?scenario=empty', fixtures: true, clock: MONDAY },
  { name: 'decisions-demo', path: '/decisions' },
  { name: 'journal', path: '/decisions/journal', fixtures: true, clock: MONDAY },
  { name: 'journal-demo', path: '/decisions/journal' },
  { name: 'flight', path: '/decisions/flight', fixtures: true, clock: MONDAY, full: true },
  { name: 'flight-empty', path: '/decisions/flight?scenario=empty', fixtures: true, clock: MONDAY },
  { name: 'flight-demo', path: '/decisions/flight' },
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
  { name: 'lab-patterns', path: '/lab/patterns', fixtures: true, clock: MONDAY, full: true },
  { name: 'lab-patterns-demo', path: '/lab/patterns' },
  { name: 'plan-full', path: '/plan', fixtures: true, clock: MONDAY, full: true },
  { name: 'plan-fi', path: '/plan', fixtures: true, clock: MONDAY, el: 'fi-path' },
  { name: 'plan-fi-table', path: '/plan', fixtures: true, clock: MONDAY, el: 'fi-path', act: async (p) => p.getByTestId('fi-path').getByRole('button', { name: 'Table view' }).click() },
  { name: 'plan-fi-empty', path: '/plan?scenario=empty', fixtures: true, clock: MONDAY, el: 'fi-path' },
  { name: 'plan-fi-history', path: '/plan?scenario=history', fixtures: true, clock: MONDAY, el: 'fi-path' },
  { name: 'plan-fi-demo', path: '/plan', el: 'fi-path' },
  { name: 'plan-deposits', path: '/plan', fixtures: true, clock: MONDAY, el: 'deposits' },
  { name: 'plan-deposits-quiet', path: '/plan?scenario=quiet', fixtures: true, clock: MONDAY, el: 'deposits' },
  { name: 'plan-deposits-listed', path: '/plan?scenario=listed', fixtures: true, clock: MONDAY, el: 'deposits' },
  { name: 'plan-deposits-demo', path: '/plan', el: 'deposits' },
  { name: 'lab-factors', path: '/lab/risk', fixtures: true, clock: MONDAY, el: 'factors' },
  { name: 'lab-factors-table', path: '/lab/risk', fixtures: true, clock: MONDAY, el: 'factors', act: async (p) => p.getByTestId('factors').getByRole('button', { name: 'Table view' }).last().click() },
  { name: 'lab-factors-empty', path: '/lab/risk?scenario=empty', fixtures: true, clock: MONDAY, el: 'factors' },
  { name: 'lab-factors-demo', path: '/lab/risk', el: 'factors' },
  { name: 'settings', path: '/settings' },
  { name: 'bridge-run', path: '/', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('today-run').scrollIntoViewIfNeeded() },
  { name: 'bridge-run-evening', path: '/?scenario=evening', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('today-run').scrollIntoViewIfNeeded() },
  { name: 'bridge-discounts', path: '/', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('discounts').scrollIntoViewIfNeeded() },
  { name: 'bridge-discounts-quiet', path: '/?scenario=quiet', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('discounts').scrollIntoViewIfNeeded() },
  { name: 'settings-box', path: '/settings', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('box').scrollIntoViewIfNeeded() },
  { name: 'settings-box-down', path: '/settings?scenario=down', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('box').scrollIntoViewIfNeeded() },
  { name: 'settings-box-off', path: '/settings?scenario=off', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('box').scrollIntoViewIfNeeded() },
  { name: 'settings-inbox', path: '/settings#inbox', fixtures: true, clock: MONDAY },
  { name: 'settings-keys', path: '/settings#keys', fixtures: true, clock: MONDAY },
  { name: 'settings-keys-open', path: '/settings#keys', fixtures: true, clock: MONDAY, act: async (p) => p.getByRole('button', { name: 'Set FINNHUB_API_KEY' }).or(p.getByRole('button', { name: 'Replace FRED_API_KEY' })).first().click() },
  { name: 'risk', path: '/settings/risk', fixtures: true, clock: MONDAY },
  { name: 'risk-convictions', path: '/settings/risk', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('convictions').scrollIntoViewIfNeeded() },
  { name: 'risk-convictions-edit', path: '/settings/risk', fixtures: true, clock: MONDAY, act: async (p) => p.locator('[data-cv="ACME"]').getByTestId('cv-edit').click() },
  { name: 'risk-convictions-add', path: '/settings/risk?scenario=empty', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('cv-add').click() },
  { name: 'settings-profile-edit', path: '/settings', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('profile-edit').click() },
  { name: 'mixes', path: '/lab/mixes', fixtures: true, clock: MONDAY },
  { name: 'mixes-noprofile', path: '/lab/mixes?scenario=noprofile', fixtures: true, clock: MONDAY },
  { name: 'mixes-table', path: '/lab/mixes', fixtures: true, clock: MONDAY, act: async (p) => p.locator('[data-mix="safe-mix"]').getByRole('button', { name: 'Table view' }).click() },
  { name: 'mixes-lower', path: '/lab/mixes?case=lower', fixtures: true, clock: MONDAY },
  { name: 'mixes-partial', path: '/lab/mixes?scenario=partial', fixtures: true, clock: MONDAY },
  { name: 'mixes-fi', path: '/lab/mixes', fixtures: true, clock: MONDAY, el: 'fi-time' },
  { name: 'mixes-fi-lower', path: '/lab/mixes', fixtures: true, clock: MONDAY, el: 'fi-time', act: async (p) => p.getByTestId('lower-switch').click() },
  { name: 'mixes-fi-table', path: '/lab/mixes', fixtures: true, clock: MONDAY, el: 'fi-time', act: async (p) => p.getByTestId('fi-ladder').getByRole('button', { name: 'Table view' }).click() },
  { name: 'mixes-hold-or-trim', path: '/lab/mixes', fixtures: true, clock: MONDAY, el: 'hold-or-trim' },
  { name: 'risk-fresh', path: '/settings/risk?scenario=fresh', fixtures: true, clock: MONDAY },
  { name: 'risk-bands', path: '/settings/risk', fixtures: true, clock: MONDAY, act: async (p) => p.getByRole('button', { name: 'See all five bands' }).click() },
  { name: 'settings-crew', path: '/settings', fixtures: true, clock: MONDAY },
  { name: 'plan-table', path: '/plan', fixtures: true, clock: MONDAY, full: true, act: async (p) => p.getByTestId('tax-calendar').getByRole('button', { name: 'Table view' }).click() },
  { name: 'bridge-nobrief', path: '/?scenario=empty', fixtures: true, clock: MONDAY },
  { name: 'settings-tables', path: '/settings', act: async (p) => p.getByTestId('mirror-row').click() },
  { name: 'settings-theme', path: '/settings', act: async (p) => p.getByRole('button', { name: /^Theme/ }).click() },
  { name: 'settings-failing', path: '/settings?scenario=failing', fixtures: true },
  { name: 'settings-offline', path: '/settings', offline: true },
  { name: 'not-found', path: '/nowhere' },
  { name: 'health-fail', path: '/?scenario=fail', fixtures: true, clock: MONDAY },
  { name: 'health-warn', path: '/plan?scenario=warn', fixtures: true, clock: MONDAY, act: async (p) => p.getByTestId('health-banner').getByText('1 more check').click() },
  { name: 'bridge-long', path: '/?scenario=long', fixtures: true, clock: MONDAY },
  { name: 'fresh-bridge', path: '/?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'fresh-research', path: '/research?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'fresh-decisions', path: '/decisions?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'fresh-journal', path: '/decisions/journal?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'fresh-flight', path: '/decisions/flight?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'fresh-plan', path: '/plan?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'fresh-lab-risk', path: '/lab/risk?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'fresh-lab-strategies', path: '/lab/strategies?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'fresh-settings', path: '/settings?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'settings-profile-error', path: '/settings?scenario=failing', fixtures: true, clock: MONDAY, el: 'profile' },
  { name: 'settings-jobs', path: '/settings', fixtures: true, clock: MONDAY, el: 'jobs' },
  { name: 'settings-jobs-more', path: '/settings', fixtures: true, clock: MONDAY, el: 'jobs', act: async (p) => p.getByTestId('jobs').getByText(/Agents and housekeeping/).click() },
  { name: 'settings-jobs-down', path: '/settings?scenario=down', fixtures: true, clock: MONDAY, el: 'jobs' },
  { name: 'settings-jobs-demo', path: '/settings', el: 'jobs' },
  { name: 'health-refresh', path: '/?scenario=fail', fixtures: true, clock: MONDAY, el: 'health-banner' },
  { name: 'health-refresh-warn', path: '/plan?scenario=warn', fixtures: true, clock: MONDAY, el: 'health-banner' },
  { name: 'lab-leaderboard', path: '/lab/strategies', fixtures: true, clock: MONDAY, el: 'leaderboard' },
  { name: 'lab-leaderboard-early', path: '/lab/strategies?scenario=early', fixtures: true, clock: MONDAY, el: 'leaderboard' },
  { name: 'lab-leaderboard-empty', path: '/lab/strategies?scenario=empty', fixtures: true, clock: MONDAY, el: 'leaderboard' },
  { name: 'settings-desks', path: '/settings', fixtures: true, clock: MONDAY, el: 'crew' },
  { name: 'settings-desks-ask', path: '/settings', fixtures: true, clock: MONDAY, el: 'crew', act: async (p) => p.getByTestId('guard').getByRole('button', { name: 'Lift the guard' }).click() },
  { name: 'settings-desks-lifted', path: '/settings?scenario=lifted', fixtures: true, clock: MONDAY, el: 'crew' },
  { name: 'first-run', path: '/settings/first-run', fixtures: true, clock: MONDAY, full: true },
  { name: 'first-run-fresh', path: '/settings/first-run?scenario=fresh', fixtures: true, clock: MONDAY, full: true },
  { name: 'first-run-demo', path: '/settings/first-run', full: true },
];

// ---------- contrast ----------
function lowContrast() {
  const cv = document.createElement('canvas');
  cv.width = 1;
  cv.height = 1;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = c;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, bottom) => [0, 1, 2].map((i) => top[i] * top[3] + bottom[i] * (1 - top[3])).concat(1);
  const lum = (c) => {
    const [r, g, b] = c.slice(0, 3).map((v) => {
      const x = v / 255;
      return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const backdrop = (el) => {
    const layers = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== 'none' && !cs.backgroundImage.startsWith('radial-gradient')) return null;
      const c = rgba(cs.backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    let bg = [255, 255, 255, 1];
    for (let k = layers.length - 1; k >= 0; k -= 1) bg = over(layers[k], bg);
    return bg;
  };
  const out = [];
  document.querySelectorAll('body *').forEach((el) => {
    const own = [...el.childNodes].some((t) => t.nodeType === 3 && t.textContent.trim());
    if (!own) return;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || Number(cs.opacity) === 0 || el.closest('[aria-hidden="true"], .sr-only, button[disabled], .hm-cell, .hm')) return;
    const svg = el instanceof SVGElement;
    const bg = backdrop(svg ? el.closest('svg').parentElement : el);
    if (!bg) return;
    let fg = rgba(svg ? cs.fill : cs.color);
    let op = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) op *= Number(getComputedStyle(n).opacity);
    fg = over([...fg.slice(0, 3), fg[3] * op], bg);
    const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    const ratio = (a + 0.05) / (b + 0.05);
    const size = parseFloat(cs.fontSize);
    const large = size >= 24 || (size >= 18.66 && Number(cs.fontWeight) >= 700);
    if (svg && ratio < 1.3) return;
    if (ratio < (large ? 3 : 4.5)) out.push(`${el.tagName.toLowerCase()}${el.className && typeof el.className === 'string' ? `.${el.className.split(' ')[0]}` : ''} "${el.textContent.trim().slice(0, 24)}" ${ratio.toFixed(2)}`);
  });
  return [...new Set(out)];
}


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
      const low = process.env.CONTRAST ? await page.evaluate(lowContrast) : [];
      const file = join(out, `${shot.name}-${width}-${theme}.png`);
      if (shot.el) await page.getByTestId(shot.el).screenshot({ path: file });
      else await page.screenshot({ path: file, fullPage: shot.full ?? !shot.act });
      report.push({ file, overflow: o.scroll > o.view, errors, low });
      await ctx.close();
    }
  }
}
await browser.close();
const bad = report.filter((r) => r.overflow || r.errors.length || r.low.length);
console.log(`${report.length} screens, ${bad.length} with problems`);
bad.forEach((b) => console.log(b.file, b.overflow ? 'OVERFLOW' : '', b.errors.join(' | '), b.low.length ? `LOW CONTRAST ${b.low.join(' ; ')}` : ''));
process.exit(bad.length ? 1 : 0);

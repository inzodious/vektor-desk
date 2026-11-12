import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('bridge shows live value, four KPI tiles, what changed and the steps due', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  await expect(page.locator('.ph-big b')).toHaveText('$16,308');
  await expect(page.getByTestId('bridge-kpis').locator('.kpi')).toHaveCount(4);
  await expect(page.locator('.kpi')).toHaveCount(4);
  await expect(page.locator('main .grid > .card')).toHaveCount(3);
  await expect(page.getByTestId('today-run')).toBeVisible();
  await expect(page.getByTestId('brief')).toContainText('What changed');
  await expect(page.getByTestId('steps-due')).toBeVisible();
  await expect(page.getByTestId('market-clock')).toHaveAttribute('data-feed', 'live');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('the Bridge fits one desktop screen and two phone screens', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('steps-due').locator('.sp-step').first()).toBeVisible();
  await expect(page.getByTestId('today-run').locator('.run-stage')).toHaveCount(5);
  const { height, wide } = await page.evaluate(() => ({ height: document.documentElement.scrollHeight, wide: window.innerWidth }));
  expect(height).toBeLessThanOrEqual(wide < 600 ? 844 * 2 : 1000);
});

test('the holdings drawer shows the departures board and links to Portfolio', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('open-holdings')).toContainText('Holdings · 5');
  await page.getByTestId('open-holdings').click();
  const drawer = page.getByRole('dialog', { name: 'Holdings' });
  await expect(drawer.getByRole('table', { name: 'Live holdings' }).getByRole('row')).toHaveCount(6);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await drawer.getByTestId('to-portfolio').click();
  await expect(page).toHaveURL(/\/portfolio$/);
  await expect(page.getByTestId('holdings-board').getByRole('table', { name: 'Live holdings' })).toBeVisible();
});

test('a board row opens the symbol sheet, Escape closes it', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('open-holdings').click();
  const row = page.getByRole('dialog', { name: 'Holdings' }).locator('.board-row[data-sym="FTEC"]');
  await row.click();
  const sheet = page.getByRole('dialog', { name: 'FTEC symbol sheet' });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByText('Live', { exact: true })).toBeVisible();
  await expect(sheet.getByRole('img', { name: 'FTEC price, one year' })).toBeVisible();
  await expect(sheet.getByRole('cell', { name: 'Dec 15, 2025' })).toBeVisible();
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await page.keyboard.press('Escape');
  await expect(sheet).toBeHidden();
});

test('the sheet opens from the URL and closes on an outside click', async ({ page }) => {
  await page.goto('/?sym=vxus');
  const sheet = page.getByRole('dialog', { name: 'VXUS symbol sheet' });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByText('No lot export yet', { exact: false })).toBeVisible();
  await page.mouse.click(5, 5);
  await expect(sheet).toBeHidden();
});

test('board rows open from the keyboard', async ({ page }) => {
  await page.goto('/portfolio');
  await page.locator('.board-row[data-sym="ACME"]').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog', { name: 'ACME symbol sheet' })).toBeVisible();
});

test('market value KPI drills into accounts', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Market value/ }).click();
  const drawer = page.getByRole('dialog', { name: 'Market value' });
  await expect(drawer.getByRole('cell', { name: 'HSA' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
});

test('market value drawer lists movers and hands off to the symbol sheet', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Market value/ }).click();
  await page.getByRole('dialog', { name: 'Market value' }).getByRole('button', { name: /FTEC/ }).click();
  await expect(page.getByRole('dialog', { name: 'FTEC symbol sheet' })).toBeVisible();
});

test('vs the safe mix drills into windows against both shadows', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-kpi="bm.excess"]').click();
  const drawer = page.getByRole('dialog', { name: 'Against the shadows' });
  await expect(drawer.getByRole('columnheader', { name: 'vs S&P 500' })).toBeVisible();
  await expect(drawer.getByRole('row', { name: /Year to date/ })).toContainText('$');
  await page.mouse.click(5, 5);
  await expect(drawer).toBeHidden();
});

test('the mix button reads the largest drift and opens drift rows that hand off to a fund', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('open-mix')).toContainText('1.3 pts');
  await page.getByTestId('open-mix').click();
  const drawer = page.getByRole('dialog', { name: 'Mix and instruments' });
  await expect(drawer.locator('.drift-row')).toHaveCount(4);
  await drawer.locator('.drift-row', { hasText: 'VXUS' }).click();
  await expect(page.getByRole('dialog', { name: 'VXUS symbol sheet' })).toBeVisible();
});

test('instruments show the drift and single stock gauges in the mix drawer', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('open-mix').click();
  const card = page.getByRole('dialog', { name: 'Mix and instruments' }).getByTestId('instruments');
  await expect(card.locator('.gauge')).toHaveCount(2);
  await expect(card).toContainText('Rebalance at 5');
  await expect(card).toContainText('Cap 10%');
  await expect(page.getByRole('dialog', { name: 'Mix and instruments' })).toContainText('FI progress 2.3%');
});

test('FI progress reads the FI number from the engine', async ({ page }) => {
  await page.goto('/portfolio');
  await expect(page.locator('[data-kpi="fi.progress"] .v')).toHaveText('2.3%');
  await expect(page.locator('[data-kpi="fi.progress"]')).toContainText('of the FI number');
});

test('the shadows drawer has the value chart with a table view and period combo', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-kpi="bm.excess"]').click();
  const card = page.getByRole('dialog', { name: 'Against the shadows' }).getByTestId('shadow-chart');
  await expect(card.getByRole('img', { name: 'Your value against the safe mix and S&P 500 shadows' })).toBeVisible();
  await expect(card.locator('.legend')).toContainText('S&P 500 shadow');
  await card.getByRole('button', { name: 'Table view' }).click();
  await expect(card.getByRole('columnheader', { name: 'Safe mix shadow' })).toBeVisible();
  await card.getByRole('button', { name: 'Chart view' }).click();
  await card.getByRole('button', { name: /^Period/ }).click();
  await page.getByRole('option', { name: '3 months' }).click();
  await expect(card.getByRole('button', { name: /^Period/ })).toContainText('3 months');
});

test('what changed lists the day’s movers and each opens its sheet', async ({ page }) => {
  await page.goto('/');
  const movers = page.getByTestId('movers');
  await expect(movers.locator('[data-sym]')).toHaveCount(3);
  await movers.locator('[data-sym]').first().click();
  await expect(page.getByRole('dialog', { name: /symbol sheet$/ })).toBeVisible();
});

test('stale quotes show as delayed', async ({ page }) => {
  await page.goto('/?scenario=stale');
  await expect(page.getByTestId('market-clock')).toHaveAttribute('data-feed', 'delayed');
  await expect(page.locator('.ph-foot')).toContainText('Stale');
});

test('a closed market uses last closes', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-11-07T16:00:00Z'));
  await page.goto('/?scenario=closed');
  await expect(page.getByTestId('market-clock')).toHaveAttribute('data-state', 'closed');
  await page.getByTestId('open-holdings').click();
  await page.locator('.board-row[data-sym="FTEC"]').click();
  await expect(page.getByRole('dialog', { name: 'FTEC symbol sheet' }).getByText('Close Nov 6')).toBeVisible();
});

test('no holdings yet says so', async ({ page }) => {
  await page.goto('/?scenario=empty');
  await expect(page.locator('.ph-big b')).toHaveText('Waiting on holdings');
});

test('bridge explains a dead API', async ({ page }) => {
  await page.route('**/api/live*', (route) => route.fulfill({ status: 503, body: '{}' }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText("The desk API didn't answer");
});

test('steps due lists the queue first and approves or opens a proposal', async ({ page }) => {
  let hit = null;
  await page.route('**/api/decisions/*/approve', async (route) => {
    hit = route.request().url();
    await route.fulfill({ json: { id: 'd_x', title: 'Approved', status: 'approved' } });
  });
  await page.goto('/');
  const q = page.getByTestId('steps-due');
  await expect(q).toHaveAttribute('data-queue', '4');
  await expect(q.locator('.sp-step')).toHaveCount(4);
  await expect(q.locator('[data-due="decision"]').first()).toBeVisible();
  await expect(q.locator('[data-due="step"]').first()).toBeVisible();
  await q.locator('[data-due="decision"]', { hasText: 'ACME' }).getByRole('button', { name: 'Review' }).click();
  await expect(page).toHaveURL(/\/decisions\?d=/);
  await expect(page.getByTestId('detail').getByRole('heading', { level: 2 })).toHaveText('Buy $400 ACME');
  await page.goBack();
  const first = q.locator('[data-due="decision"]').filter({ has: page.getByRole('button', { name: 'Approve' }) }).first();
  await first.getByRole('button', { name: 'Approve' }).click();
  await expect(q.getByRole('status')).toContainText('Approved');
  expect(hit).toMatch(/\/approve$/);
});

test('board symbols read the right way round and long codes fit their tiles', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/portfolio?scenario=long');
  const board = page.locator('.board');
  await expect(board.locator('.board-row[data-sym="0999999"] .flap')).toHaveAttribute('aria-label', '0999999');
  await expect(board.locator('.board-row[data-sym="LONGSYMBOL"] .flap span')).toHaveCount(7);
  await expect(board.locator('.board-row[data-sym="LONGSYMBOL"] .flap span').last()).toHaveText('…');
  const report = await board.evaluate((el) =>
    [...el.querySelectorAll('.board-row[data-sym]')].map((row) => {
      const flap = row.querySelector('.flap');
      const cell = flap.parentElement.getBoundingClientRect();
      const box = flap.getBoundingClientRect();
      const turned = [...flap.querySelectorAll('span')].filter((s) => getComputedStyle(s).transform !== 'none').length;
      return { sym: row.dataset.sym, fits: box.right <= cell.right + 0.5, turned };
    }),
  );
  expect(report.filter((r) => !r.fits || r.turned)).toEqual([]);
});

test('against the safe mix the Mix button and its gauge stay neutral', async ({ page }) => {
  await page.goto('/?scenario=yardstick');
  const mix = page.getByTestId('open-mix');
  await expect(mix).toContainText('Mix · SCHD −20.0 pts');
  await expect(mix).not.toHaveClass(/heads-up/);
  await mix.click();
  const drawer = page.getByRole('dialog', { name: 'Mix and instruments' });
  await expect(drawer).toContainText('as a yardstick');
  const card = drawer.getByTestId('instruments');
  await expect(card).toContainText('Vs the safe mix');
  await expect(card).toContainText('A yardstick, not a target');
  await expect(card).not.toContainText('Rebalance');
  await expect(drawer.locator('.drift-row.over')).toHaveCount(0);
  await expect(drawer.locator('.drift-band')).toHaveCount(0);
});

test('the brief’s “as of” reads as a day whatever shape the desk sends, and hides when it has none', async ({ page }) => {
  const { readFileSync } = await import('node:fs');
  const BRIEF = JSON.parse(readFileSync(new URL('../src/fixtures/agents.brief.json', import.meta.url), 'utf8'));
  let asOf = '2026-11-07T01:20:00Z';
  await page.route(/\/api\/agents\/brief(\?.*)?$/, (route) => route.fulfill({ json: { ...BRIEF, as_of: asOf } }));
  await page.goto('/');
  await expect(page.getByTestId('brief-foot')).toHaveText('Built from engine numbers as of Nov 6');
  asOf = 'not a day';
  await page.reload();
  await expect(page.getByTestId('brief')).toContainText('What changed');
  await expect(page.getByTestId('brief-foot')).toHaveCount(0);
  await expect(page.getByTestId('brief')).not.toContainText('NaN');
});

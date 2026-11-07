import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('bridge shows live value, KPI tiles and the departures board', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  await expect(page.locator('.ph-big b')).toHaveText('$16,308');
  await expect(page.locator('.kpi')).toHaveCount(7);
  await expect(page.getByRole('table', { name: 'Live holdings' }).getByRole('row')).toHaveCount(6);
  await expect(page.getByTestId('market-clock')).toHaveAttribute('data-feed', 'live');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a board row opens the symbol sheet, Escape closes it', async ({ page }) => {
  await page.goto('/');
  const row = page.locator('.board-row[data-sym="FTEC"]');
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
  await page.goto('/');
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

test('vs the plan drills into windows against both shadows', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-kpi="bm.excess"]').click();
  const drawer = page.getByRole('dialog', { name: 'Against the shadows' });
  await expect(drawer.getByRole('columnheader', { name: 'vs S&P 500' })).toBeVisible();
  await expect(drawer.getByRole('row', { name: /Year to date/ })).toContainText('$');
  await page.mouse.click(5, 5);
  await expect(drawer).toBeHidden();
});

test('largest drift drills into drift bullets and hands off to a fund', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-kpi="plan.drift_max"] .v')).toContainText('1.3');
  await page.locator('[data-kpi="plan.drift_max"]').click();
  const drawer = page.getByRole('dialog', { name: 'Drift by fund' });
  await expect(drawer.locator('.drift-row')).toHaveCount(4);
  await drawer.locator('.drift-row', { hasText: 'VXUS' }).click();
  await expect(page.getByRole('dialog', { name: 'VXUS symbol sheet' })).toBeVisible();
});

test('instruments show the drift and single stock gauges', async ({ page }) => {
  await page.goto('/');
  const card = page.locator('.card', { hasText: 'Instruments' });
  await expect(card.locator('.gauge')).toHaveCount(2);
  await expect(card).toContainText('Rebalance at 5');
  await expect(card).toContainText('Cap 10%');
});

test('FI progress reads the FI number from the engine', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-kpi="fi.progress"] .v')).toHaveText('2.3%');
  await expect(page.locator('[data-kpi="fi.progress"]')).toContainText('of the FI number');
});

test('value chart has a table view and period combo', async ({ page }) => {
  await page.goto('/');
  const card = page.locator('.card', { hasText: 'Value versus the plan' });
  await expect(card.getByRole('img', { name: 'Your value against the plan and S&P 500 shadows' })).toBeVisible();
  await expect(card.locator('.legend')).toContainText('S&P 500 shadow');
  await card.getByRole('button', { name: 'Table view' }).click();
  await expect(card.getByRole('columnheader', { name: 'Plan shadow' })).toBeVisible();
  await card.getByRole('button', { name: 'Chart view' }).click();
  await card.getByRole('button', { name: /^Period/ }).click();
  await page.getByRole('option', { name: '3 months' }).click();
  await expect(card.getByRole('button', { name: /^Period/ })).toContainText('3 months');
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

test('bridge shows the top three proposals and acts on them', async ({ page }) => {
  let hit = null;
  await page.route('**/api/decisions/*/dismiss', async (route) => {
    hit = route.request().url();
    await route.fulfill({ json: { id: 'd_x', title: 'Hold off on new BND until the rate decision', status: 'dismissed' } });
  });
  await page.goto('/');
  const q = page.getByTestId('bridge-queue');
  await expect(q.locator('.prop')).toHaveCount(3);
  await expect(q).toContainText('1 more in the queue');
  await expect(q.locator('.prop', { hasText: 'ACME' }).getByRole('link', { name: 'Review' })).toBeVisible();
  await q.getByRole('button', { name: /^Dismiss Hold off/ }).click();
  await expect(q.getByRole('status')).toContainText('Dismissed');
  expect(hit).toMatch(/\/dismiss$/);
  await q.locator('.prop', { hasText: 'ACME' }).getByRole('link', { name: 'Review' }).click();
  await expect(page).toHaveURL(/\/decisions\?d=/);
  await expect(page.getByTestId('detail').getByRole('heading', { level: 2 })).toHaveText('Buy $400 ACME');
});

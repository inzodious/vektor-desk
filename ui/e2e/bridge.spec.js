import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('bridge shows live value, KPI tiles and the departures board', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  await expect(page.locator('.ph-big b')).toHaveText('$19,505');
  await expect(page.locator('.kpi')).toHaveCount(4);
  await expect(page.getByRole('table', { name: 'Live holdings' }).getByRole('row')).toHaveCount(8);
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
  await page.locator('.board-row[data-sym="RKLB"]').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog', { name: 'RKLB symbol sheet' })).toBeVisible();
});

test('market value KPI drills into accounts', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Market value/ }).click();
  const drawer = page.getByRole('dialog', { name: 'Market value' });
  await expect(drawer.getByRole('cell', { name: 'HSA' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
});

test('today KPI lists movers and hands off to the symbol sheet', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /^Today/ }).click();
  await page.getByRole('dialog', { name: 'Today' }).getByRole('button', { name: /SMR/ }).click();
  await expect(page.getByRole('dialog', { name: 'SMR symbol sheet' })).toBeVisible();
});

test('value chart has a table view and period combo', async ({ page }) => {
  await page.goto('/');
  const card = page.locator('.card', { hasText: 'Value over time' });
  await expect(card.getByRole('img', { name: 'Portfolio value over time' })).toBeVisible();
  await card.getByRole('button', { name: 'Table view' }).click();
  await expect(card.getByRole('columnheader', { name: 'Value' })).toBeVisible();
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

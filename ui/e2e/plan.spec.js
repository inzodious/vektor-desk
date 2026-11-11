import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('holdings shows the board, KPIs, drift, rules, funds and the deposit split', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/portfolio');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Holdings');
  await expect(page.locator('.ph-big b')).toHaveText('$16,308');
  await expect(page.locator('.ph-big')).toContainText('5 holdings · largest drift 1.3 pts');
  await expect(page.getByRole('navigation', { name: 'Portfolio views' }).getByRole('link')).toHaveText(['Holdings', 'Stock plans', 'Risk', 'Tax']);
  await expect(page.getByTestId('holdings-board').getByRole('table', { name: 'Live holdings' }).getByRole('row')).toHaveCount(6);
  await expect(page.locator('.kpi')).toHaveCount(6);
  await expect(page.locator('[data-kpi="plan.rules"] .v')).toHaveText('3 of 3');
  await expect(page.locator('[data-kpi="plan.in_mix"] .v')).toContainText('98.7');
  await expect(page.getByTestId('tax-calendar')).toHaveCount(0);
  await expect(page.locator('.drift-row')).toHaveCount(4);
  await expect(page.locator('.rule', { hasText: 'Drift limit 5 points' })).toContainText('Passing');
  await expect(page.getByText('desk.yaml rules v1')).toBeVisible();
  const deposit = page.locator('.card', { hasText: 'Next deposit' }).last();
  await expect(deposit).toContainText('Modelled');
  await expect(deposit.getByTestId('split').locator('.row')).toHaveCount(3);
  await expect(deposit.locator('.row', { hasText: 'VXUS' })).toContainText('→');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('funds open their symbol sheet', async ({ page }) => {
  await page.goto('/portfolio');
  await page.locator('tr[data-sym="BND"]').click();
  await expect(page.getByRole('dialog', { name: 'BND symbol sheet' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.locator('tr[data-sym="ACME"]').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog', { name: 'ACME symbol sheet' })).toBeVisible();
});

test('single stocks carry no target', async ({ page }) => {
  await page.goto('/portfolio');
  await expect(page.locator('tr[data-sym="ACME"]')).toContainText('No target');
});

test('plan explains a dead API', async ({ page }) => {
  await page.route('**/api/engine/metrics*', (route) => route.fulfill({ status: 503, body: '{}' }));
  await page.goto('/portfolio');
  await expect(page.getByRole('alert')).toContainText("The desk API didn't answer");
});

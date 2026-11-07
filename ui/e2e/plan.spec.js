import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('plan shows KPIs, drift, rules, funds and the deposit split', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/plan');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Plan');
  await expect(page.locator('.ph-big b')).toHaveText('98.7% in the mix');
  await expect(page.locator('.kpi')).toHaveCount(6);
  await expect(page.locator('[data-kpi="plan.rules"] .v')).toHaveText('3 of 3');
  await expect(page.locator('[data-kpi="tax.harvestable"] .v')).toHaveText('Not yet');
  await expect(page.locator('.drift-row')).toHaveCount(4);
  await expect(page.locator('.rule', { hasText: 'Drift limit 5 points' })).toContainText('Passing');
  await expect(page.getByText('desk.yaml rules v1')).toBeVisible();
  const deposit = page.locator('.card', { hasText: 'Next deposit' }).last();
  await expect(deposit).toContainText('Modelled');
  await expect(deposit.locator('.row')).toHaveCount(3);
  await expect(deposit.locator('.row', { hasText: 'VXUS' })).toContainText('→');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('funds open their symbol sheet', async ({ page }) => {
  await page.goto('/plan');
  await page.locator('tr[data-sym="BND"]').click();
  await expect(page.getByRole('dialog', { name: 'BND symbol sheet' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.locator('tr[data-sym="ACME"]').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog', { name: 'ACME symbol sheet' })).toBeVisible();
});

test('single stocks sit outside the plan', async ({ page }) => {
  await page.goto('/plan');
  await expect(page.locator('tr[data-sym="ACME"]')).toContainText('Not in plan');
});

test('plan explains a dead API', async ({ page }) => {
  await page.route('**/api/engine/metrics*', (route) => route.fulfill({ status: 503, body: '{}' }));
  await page.goto('/plan');
  await expect(page.getByRole('alert')).toContainText("The desk API didn't answer");
});

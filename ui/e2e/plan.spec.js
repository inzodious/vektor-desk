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
  await expect(page.getByText('Profile rules v1')).toBeVisible();
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

test('with no plan loaded, drift reads as a comparison with the safe mix and prompts nothing', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/portfolio?scenario=yardstick');
  await expect(page.locator('.ph-big')).toContainText('up to 20.0 pts from the safe mix');
  const kpi = page.locator('.kpi').first();
  await expect(kpi).toContainText('Vs the safe mix');
  await expect(kpi).toContainText('A yardstick, not a target');
  await expect(kpi).not.toContainText('Rebalance');
  await expect(kpi.locator('.tone-watch')).toHaveCount(0);
  await expect(kpi).toContainText('20.0');
  const card = page.getByTestId('drift-card');
  await expect(card).toHaveAttribute('data-judged', 'no');
  await expect(card.locator('.drift-row')).toHaveCount(8);
  await expect(card.locator('.drift-row.over')).toHaveCount(0);
  await expect(card.locator('.drift-band')).toHaveCount(0);
  await expect(card.locator('.drift-legend')).not.toContainText('Outside band');
  await expect(card.locator('.drift-legend')).toContainText('Safe mix');
  await expect(card.getByTestId('reference-note')).toContainText('It is a yardstick, not a target');
  await expect(page.getByRole('columnheader', { name: 'Safe mix' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Gap' })).toBeVisible();
  await expect(page.locator('tr[data-sym="FXAIX"] td.dn')).toHaveCount(0);
  await expect(page.locator('tr[data-sym="VXUS"]')).toContainText('Not in the mix');
  const rule = page.getByTestId('rules-card').locator('[data-rule="drift-max"]');
  await expect(rule).toContainText('Not judged');
  await expect(rule).toContainText('The safe mix is a yardstick, not a target');
  await expect(rule).not.toContainText('Passing');
  await expect(page.locator('.kpi', { hasText: 'Rules' })).toContainText('2 of 2');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a loaded plan keeps the drift band, the tone and the rebalance line', async ({ page }) => {
  await page.goto('/portfolio');
  const kpi = page.locator('.kpi').first();
  await expect(kpi).toContainText('Largest drift');
  await expect(kpi).toContainText('Rebalance at 5');
  const card = page.getByTestId('drift-card');
  await expect(card).toHaveAttribute('data-judged', 'yes');
  await expect(card.locator('.drift-band')).toHaveCount(4);
  await expect(card.locator('.drift-legend')).toContainText('Outside band');
  await expect(card.getByTestId('reference-note')).toHaveCount(0);
  await expect(page.getByTestId('rules-card').locator('[data-rule="drift-max"]')).toContainText('Passing');
  await expect(page.locator('.kpi', { hasText: 'Rules' })).toContainText('3 of 3');
});

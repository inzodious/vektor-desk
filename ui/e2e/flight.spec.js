import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- flight record ----------
test('flight record scores each desk against the plan', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/decisions/flight');
  await expect(page.locator('.ph-big')).toContainText('+$946');
  await expect(page.locator('.ph-big')).toContainText('47 desk calls');
  const desks = page.getByTestId('desks');
  await expect(desks.locator('[data-desk]')).toHaveCount(4);
  await expect(desks.locator('[data-desk="scout"]')).toContainText('Keep it on');
  await expect(desks.locator('[data-desk="plan_keeper"]')).toContainText('Behind the plan');
  await expect(desks.locator('[data-desk="tax"]')).toContainText('No calls old enough');
  await expect(page.getByTestId('calibration').locator('[data-bin]')).toHaveCount(3);
  await expect(page.getByTestId('saves')).toContainText('$832');
  await expect(page.getByTestId('scored-table').locator('tbody tr')).toHaveCount(10);
  await page.getByTestId('scored').getByRole('button', { name: /^Show all/ }).click();
  await expect(page.getByTestId('scored-table').locator('tbody tr')).not.toHaveCount(10);
  expect(errors).toEqual([]);
});

test('groups switch by split and window', async ({ page }) => {
  await page.goto('/decisions/flight');
  const g = page.getByTestId('groups');
  await g.getByRole('button', { name: /^Group/ }).click();
  await page.getByRole('option', { name: 'By desk' }).click();
  await expect(g).toContainText('Plan keeper');
  await g.getByRole('button', { name: /^Window/ }).click();
  await page.getByRole('option', { name: '30 days' }).click();
  await g.getByRole('button', { name: 'Table view' }).click();
  await expect(g.locator('table')).toContainText('Scout');
});

test('an empty record says how scoring works', async ({ page }) => {
  await page.goto('/decisions/flight?scenario=empty');
  await expect(page.locator('.ph-big')).toContainText('No record yet');
  await expect(page.getByTestId('calibration')).toContainText('needs 30 scored calls');
});

// ---------- patterns ----------
test('patterns show market context, holdings, drawdowns and habits', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/lab/patterns');
  await expect(page.locator('.ph-big')).toContainText('S&P 500 below its high');
  await expect(page.getByTestId('market').locator('[data-pattern]')).toHaveCount(4);
  await expect(page.getByTestId('market').locator('[data-pattern="pat.mkt_drawdown"]')).toContainText('past cases were higher 12 months later');
  const h = page.getByTestId('holdings');
  await expect(h.locator('[data-scope="ACME"]').first()).toBeVisible();
  await h.getByRole('button', { name: /^Holding/ }).click();
  await page.getByRole('option', { name: 'BND' }).click();
  await expect(h.locator('[data-scope="BND"]').first()).toBeVisible();
  await expect(page.getByTestId('drawdowns').locator('[data-dd]')).toHaveCount(4);
  await expect(page.getByTestId('seasonality').locator('svg')).toBeVisible();
  await expect(page.getByTestId('corr-shifts')).toContainText('Shifts of 0.3 or more');
  await expect(page.getByTestId('behavior')).toContainText('After a 5% rise');
  await expect(page.getByRole('note')).toContainText('Left out on purpose');
  expect(errors).toEqual([]);
});

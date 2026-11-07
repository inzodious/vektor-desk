import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- FI path ----------
test('the FI path shows the odds, the date range and the fan', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/plan');
  const card = page.getByTestId('fi-path');
  await expect(card).toHaveAttribute('data-state', 'ok');
  await expect(card.locator('[data-fi="number"]')).toContainText('$700,000');
  await expect(card.locator('[data-fi="number"]')).toContainText('2.3% of the way');
  await expect(card.locator('[data-fi="target"]')).toContainText('Mar 2051');
  await expect(card.locator('[data-fi="target"]')).toContainText('9.7% a year');
  await expect(card.locator('[data-fi="on-time"]')).toContainText('19%');
  await expect(card.locator('[data-fi="date"]')).toContainText('Feb 2058');
  await expect(card.getByTestId('fi-range')).toContainText('Fast 10% of paths by Sep 2048');
  await expect(card.getByTestId('fi-range')).toContainText('Slow 10% beyond 34 years');
  await expect(card.getByRole('img', { name: /market paths toward \$700,000/ })).toBeVisible();
  await expect(card.locator('svg text', { hasText: 'Target' })).toHaveCount(1);
  await card.getByRole('button', { name: 'Table view' }).click();
  await expect(card.getByRole('columnheader', { name: 'Middle' })).toBeVisible();
  await expect(card.locator('tbody tr').first()).toContainText('Nov 2060');
  await card.getByText('How the paths are drawn').click();
  await expect(card.locator('.lamp-notes li')).toHaveCount(4);
  await expect(card.locator('.lamp-notes li').first()).toBeVisible();
  expect(errors).toEqual([]);
});

test('without a goal the FI path says where to set one', async ({ page }) => {
  await page.goto('/plan?scenario=empty');
  const card = page.getByTestId('fi-path');
  await expect(card).toHaveAttribute('data-state', 'no_goal');
  await expect(card).toContainText('Set yearly spend and a target age in Escape Vektor');
});

test('without market history the goal still shows', async ({ page }) => {
  await page.goto('/plan?scenario=history');
  const card = page.getByTestId('fi-path');
  await expect(card).toHaveAttribute('data-state', 'no_history');
  await expect(card.locator('[data-fi="number"]')).toContainText('$700,000');
  await expect(card).toContainText('French monthly market history');
  await expect(card.getByRole('img')).toHaveCount(0);
});

// ---------- factors ----------
test('factor exposure shows the portfolio lean and each holding', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/lab/risk');
  const card = page.getByTestId('factors');
  await expect(card.getByTestId('lean')).toContainText('Mostly the market');
  await expect(card.getByTestId('lean')).toContainText('covers 99% of value');
  await expect(card).toContainText('2023 to 2026');
  await card.getByRole('button', { name: 'Table view' }).first().click();
  await expect(card.locator('table').first()).toContainText('Market');
  await expect(card.locator('table').first()).toContainText('0.81');
  await card.getByRole('button', { name: 'Table view' }).click();
  await expect(card.locator('table').last().locator('tbody tr')).toHaveCount(5);
  await expect(card.locator('table').last().locator('tbody tr').first()).toContainText('FXAIX');
  expect(errors).toEqual([]);
});

test('factor exposure waits for the factor library', async ({ page }) => {
  await page.goto('/lab/risk?scenario=empty');
  await expect(page.getByTestId('factors')).toContainText('No French factors yet.');
});

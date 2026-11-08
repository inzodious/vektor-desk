import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('the bridge shows discount days with the research case', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  const card = page.getByTestId('discounts');
  await expect(card).toHaveAttribute('data-count', '5');
  await expect(card.getByTestId('disc-lede')).toContainText('5 names on sale · 2 you hold · 1 with a case to buy');
  await expect(card.locator('.disc-rows').first().locator('.disc-row')).toHaveCount(4);
  const ftec = card.locator('[data-disc="FTEC"]');
  await expect(ftec).toContainText('−3.2% today, 2.4× its usual swing');
  await expect(ftec.getByTestId('disc-verdict')).toHaveText('Case to buy');
  await ftec.locator('summary').click();
  await expect(ftec).toContainText('Risks: Rates could keep pressing');
  await expect(card.locator('[data-disc="MSFT"]')).toContainText('Research is reading this one.');
  await card.getByText('1 more from the last 10 days').click();
  await expect(card.locator('[data-disc="COST"]')).toBeVisible();
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a discount symbol opens its sheet', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('discounts').locator('[data-disc="MSFT"] [data-sym]').click();
  await expect(page.getByRole('dialog', { name: 'MSFT symbol sheet' })).toBeVisible();
});

test('a quiet week says what the scan looks for', async ({ page }) => {
  await page.goto('/?scenario=quiet');
  const card = page.getByTestId('discounts');
  await expect(card.getByTestId('disc-empty')).toContainText('No discounts in the last 10 days.');
  await expect(card.getByTestId('disc-empty')).toContainText('52-week high');
});

test('the card stays away until the engine serves the scan', async ({ page }) => {
  await page.route(/\/api\/engine\/discounts/, (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/');
  await expect(page.getByTestId('brief')).toBeVisible();
  await expect(page.getByTestId('discounts')).toHaveCount(0);
});

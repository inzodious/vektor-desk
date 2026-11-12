import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('a healthy engine shows no banner', async ({ page }) => {
  await page.goto('/portfolio');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByTestId('health-banner')).toHaveCount(0);
});

test('a failing engine says look, do not act, on every page, in one line with nothing to press', async ({ page }) => {
  for (const path of ['/?scenario=fail', '/decisions?scenario=fail', '/portfolio/risk?scenario=fail']) {
    await page.goto(path);
    const b = page.getByTestId('health-banner');
    await expect(b).toHaveAttribute('data-level', 'fail');
    await expect(b).toContainText('Look, don’t act yet.');
    await expect(b).toContainText('Values against the broker: Desk value is 4.1% off the broker');
    await expect(b.getByRole('button')).toHaveCount(0);
    await expect(b.locator('details')).toHaveCount(0);
    await expect(b).not.toContainText('more check');
  }
});

test('checks that are only worth a read never put a banner on a page', async ({ page }) => {
  const errors = watchErrors(page);
  for (const path of ['/?scenario=warn', '/research?scenario=warn', '/portfolio?scenario=warn', '/decisions?scenario=warn', '/strategies?scenario=warn']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByTestId('health-banner')).toHaveCount(0);
    await expect(page.getByText('Worth a look before you act')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Refresh data' })).toHaveCount(0);
  }
  expect(errors).toEqual([]);
});

test('Settings, Box keeps the checks in a closed fold', async ({ page }) => {
  await page.goto('/settings/box?scenario=warn');
  const card = page.getByTestId('data-checks');
  await expect(card).toHaveJSProperty('open', false);
  await expect(card.locator('summary')).toContainText('2 to read');
  await card.locator('summary').click();
  await expect(card.locator('li')).toHaveCount(2);
  await expect(card.locator('li').first()).toContainText('Tax rate');
  await expect(card.locator('li').nth(1)).toContainText('No lot export yet');
  await expect(card).toContainText('5 other checks are fine.');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);

  await page.goto('/settings/box');
  await expect(page.getByTestId('data-checks').locator('summary')).toContainText('All clear');
});

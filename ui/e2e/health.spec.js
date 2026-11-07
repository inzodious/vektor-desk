import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('a healthy engine shows no banner', async ({ page }) => {
  await page.goto('/plan');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByTestId('health-banner')).toHaveCount(0);
});

test('a failing engine says look, do not act, on every page', async ({ page }) => {
  for (const path of ['/?scenario=fail', '/decisions?scenario=fail', '/lab/risk?scenario=fail']) {
    await page.goto(path);
    const b = page.getByTestId('health-banner');
    await expect(b).toHaveAttribute('data-level', 'fail');
    await expect(b).toContainText('Look, don’t act yet.');
    await expect(b).toContainText('Values against the broker: Desk value is 4.1% off the broker');
    await expect(b.getByRole('button', { name: /Hide/ })).toHaveCount(0);
  }
});

test('a warning lists every check and hides until the next run', async ({ page }) => {
  await page.goto('/research?scenario=warn');
  const b = page.getByTestId('health-banner');
  await expect(b).toHaveAttribute('data-level', 'warn');
  await expect(b).toContainText('Tax rate:');
  await b.getByText('1 more check').click();
  await expect(b.locator('li')).toContainText('No lot export yet');
  await b.getByRole('button', { name: 'Hide until the next run' }).click();
  await expect(b).toHaveCount(0);
  await page.goto('/plan?scenario=warn');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByTestId('health-banner')).toHaveCount(0);
});

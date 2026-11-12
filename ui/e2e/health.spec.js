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
    await expect(b).toContainText('Your broker’s positions and account totals for Friday do not add up, so values cannot be trusted yet. The desk is reading your accounts again.');
    await expect(b).not.toContainText('Values against the broker');
    await expect(b).not.toContainText('re-run');
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

test('a check the desk is fixing by itself shows nowhere but Settings', async ({ page }) => {
  const errors = watchErrors(page);
  for (const path of ['/?scenario=healing', '/portfolio?scenario=healing', '/decisions?scenario=healing']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByTestId('health-banner')).toHaveCount(0);
  }
  await page.goto('/settings/box?scenario=healing');
  const card = page.getByTestId('data-checks');
  await expect(card.locator('> summary')).toContainText('Fixing itself');
  await card.locator('> summary').click();
  await expect(card.locator('.check-group')).toHaveCount(1);
  await expect(card.locator('.check-group h3')).toHaveText('Fixing itself');
  await expect(card.locator('.check-list li')).toContainText('Two fund prices for Monday are not out yet. The desk checks every hour.');
  await expect(card.locator('.check-list li')).toContainText('The desk has asked once.');
  await expect(card.locator('.check-more')).toHaveJSProperty('open', false);
  expect(errors).toEqual([]);
});

test('Settings, Box keeps the checks in a closed fold, grouped by who fixes them', async ({ page }) => {
  await page.goto('/settings/box?scenario=fail');
  const card = page.getByTestId('data-checks');
  await expect(card).toHaveJSProperty('open', false);
  await expect(card.locator('> summary')).toContainText('1 blocking');
  await card.locator('> summary').click();
  await expect(card.locator('.check-group h3')).toHaveText(['Blocking', 'Needs you']);
  await expect(card.locator('.check-group[data-kind="needs_you"] li')).toHaveCount(2);
  await expect(card.locator('.check-group[data-kind="needs_you"] li').first()).toContainText('Tax rate');
  await expect(card.locator('.check-group[data-kind="needs_you"] li').nth(1)).toContainText('No tax lots yet');
  await expect(card).toContainText('4 other checks are fine.');
  await card.locator('.check-group[data-kind="blocks"] .check-more summary').click();
  await expect(card.locator('.check-group[data-kind="blocks"] .check-more')).toContainText('4.1% off the broker');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);

  await page.goto('/settings/box');
  await expect(page.getByTestId('data-checks').locator('> summary')).toContainText('All clear');
});

test('what only he can fix is one plain line each on the first-run page, behind the Setup chip', async ({ page }) => {
  await page.goto('/?scenario=warn');
  const chip = page.getByTestId('setup-chip');
  await expect(chip).toHaveAttribute('data-needs', '2');
  await chip.click();
  await expect(page).toHaveURL(/\/settings\/first-run/);
  await page.goto('/settings/first-run?scenario=warn');
  const needs = page.getByTestId('needs-you');
  await expect(needs.locator('li')).toHaveCount(2);
  await expect(needs.locator('li').nth(1)).toHaveText('No tax lots yet, so tax and wash-sale checks are off. Upload your Fidelity history or a lot export in Settings, Data, Inbox.');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await page.goto('/settings/first-run');
  await expect(page.getByTestId('first-run')).toBeVisible();
  await expect(page.getByTestId('needs-you')).toHaveCount(0);
});

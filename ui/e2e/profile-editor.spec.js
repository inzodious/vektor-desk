import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('the profile editor opens from Settings with today’s values', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings');
  await page.getByTestId('profile-edit').click();
  const dlg = page.getByRole('dialog', { name: 'Edit the profile' });
  const form = dlg.getByTestId('profile-form');
  await expect(form).toHaveAttribute('data-changes', '0');
  await expect(form.locator('[data-group]')).toHaveCount(6);
  await expect(form.locator('[data-group="margin"] legend')).toHaveText('Borrowing');
  await expect(dlg.getByLabel('Margin rate, % a year')).toHaveValue('12');
  await expect(dlg.getByLabel('Horizon, years')).toHaveValue('10');
  await expect(dlg.getByLabel('Least sure %')).toHaveValue('55');
  await expect(form.locator('[data-field="growth.tilt"]')).toContainText('Growth');
  await expect(dlg.getByTestId('profile-save')).toBeDisabled();
  await expect(dlg.getByTestId('profile-pending')).toHaveText('No changes yet');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await page.keyboard.press('Escape');
  await expect(dlg).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('no Edit button before desk.yaml exists', async ({ page }) => {
  await page.goto('/settings?scenario=empty');
  await expect(page.getByTestId('starter')).toBeVisible();
  await expect(page.getByTestId('profile-edit')).toHaveCount(0);
});

test('saving sends only the changed fields and says what it wrote', async ({ page }) => {
  let sent = null;
  await page.route('**/api/decisions/profile', (route) => {
    if (route.request().method() !== 'PATCH') return route.fallback();
    sent = route.request().postDataJSON();
    return route.fulfill({ json: { changed: true, path: '/data/desk.yaml', backup: '/data/desk.yaml.bak', sections: ['growth', 'opportunity'], version: 3, status: {} } });
  });
  await page.goto('/settings');
  await page.getByTestId('profile-edit').click();
  const dlg = page.getByRole('dialog', { name: 'Edit the profile' });
  await dlg.getByLabel('Horizon, years').fill('15');
  await dlg.getByLabel('Least sure %').fill('60');
  await dlg.locator('[data-field="growth.tilt"] button').click();
  await dlg.getByRole('option', { name: 'Balanced' }).click();
  await expect(dlg.getByTestId('profile-pending')).toHaveText('3 changes to save');
  await dlg.getByTestId('profile-save').click();
  await expect(dlg.getByTestId('profile-msg')).toHaveText('Saved 2 sections as profile v3. desk.yaml kept a backup.');
  expect(sent).toEqual({ changes: { growth: { horizon_years: 15, tilt: 'balanced' }, opportunity: { min_confidence: 0.6 } } });
});

test('the margin rate shows on the profile card and saves as its own section', async ({ page }) => {
  let sent = null;
  let saved = false;
  await page.route('**/api/decisions/profile', (route) => {
    if (route.request().method() !== 'PATCH') return route.fallback();
    sent = route.request().postDataJSON();
    saved = true;
    return route.fulfill({ json: { changed: true, path: '/data/desk.yaml', backup: '/data/desk.yaml.bak', sections: ['margin'], version: 3, status: {} } });
  });
  await page.route('**/api/decisions/profile/status*', async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ response: res, json: saved ? { ...body, margin: { rate_pct: 12.075, source: 'profile' } } : body });
  });
  await page.goto('/settings');
  const tile = page.getByTestId('profile-margin');
  await expect(tile).toHaveAttribute('data-source', 'default');
  await expect(tile).toContainText('12%');
  await expect(tile).toContainText('A typical rate until you set your own');
  await page.getByTestId('profile-edit').click();
  const dlg = page.getByRole('dialog', { name: 'Edit the profile' });
  await dlg.getByLabel('Margin rate, % a year').fill('50');
  await expect(dlg.locator('[data-field="margin.rate_pct"]')).toContainText('40 or less.');
  await expect(dlg.getByTestId('profile-save')).toBeDisabled();
  await dlg.getByLabel('Margin rate, % a year').fill('12.075');
  await expect(dlg.getByTestId('profile-pending')).toHaveText('1 change to save');
  await dlg.getByTestId('profile-save').click();
  await expect(dlg.getByTestId('profile-msg')).toHaveText('Saved 1 section as profile v3. desk.yaml kept a backup.');
  expect(sent).toEqual({ changes: { margin: { rate_pct: 12.075 } } });
  await page.keyboard.press('Escape');
  await expect(tile).toHaveAttribute('data-source', 'yours');
  await expect(tile).toContainText('12.075%');
  await expect(tile).toContainText('Your rate, a year');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

test('a bad field blocks the save and a refusal is shown in words', async ({ page }) => {
  await page.route('**/api/decisions/profile', (route) => {
    if (route.request().method() !== 'PATCH') return route.fallback();
    return route.fulfill({ status: 422, json: { detail: 'That change doesn’t validate, so nothing was written: tax.harvest_threshold_usd must be at least 0' } });
  });
  await page.goto('/settings');
  await page.getByTestId('profile-edit').click();
  const dlg = page.getByRole('dialog', { name: 'Edit the profile' });
  await dlg.getByLabel('Ideas a month').fill('2.5');
  await expect(dlg.locator('[data-field="opportunity.ideas_per_month"]')).toContainText('Whole numbers only.');
  await expect(dlg.getByTestId('profile-pending')).toHaveText('1 field needs a fix');
  await expect(dlg.getByTestId('profile-save')).toBeDisabled();
  await dlg.getByLabel('Ideas a month').fill('3');
  await dlg.getByTestId('profile-save').click();
  await expect(dlg.getByTestId('profile-msg')).toContainText('nothing was written');
});

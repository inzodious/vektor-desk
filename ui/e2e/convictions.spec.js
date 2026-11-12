import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- list ----------
test('conviction holds show each band, the weight and a trim nudge above the ceiling', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/risk');
  const card = page.getByTestId('convictions');
  await expect(card).toHaveAttribute('data-count', '2');
  await expect(card.locator('.card-head')).toContainText('Band 4 ceiling 10%');
  const acme = card.locator('[data-cv="ACME"]');
  await expect(acme).toHaveAttribute('data-status', 'above');
  await expect(acme).toContainText('0% to 10%');
  await expect(acme).toContainText('12.4% of the portfolio');
  await expect(acme.getByTestId('cv-status')).toHaveText('Above the ceiling');
  await expect(acme).toContainText('The desk suggests a trim once a week');
  await expect(acme.locator('.cv-meter')).toHaveAttribute('aria-label', 'ACME: band 0% to 10%, weight 12.4%');
  await expect(card.locator('[data-cv="ORBT"]')).toHaveAttribute('data-status', 'inside');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('with no holds and no risk check the card asks for a ceiling', async ({ page }) => {
  await page.goto('/settings/risk?scenario=fresh');
  const card = page.getByTestId('convictions');
  await expect(card).toHaveAttribute('data-count', '0');
  await expect(card.getByTestId('cv-empty')).toContainText('Take the risk check for a suggested ceiling');
  await card.getByTestId('cv-add').click();
  await expect(card.getByTestId('cv-max')).toHaveValue('');
  await card.getByTestId('cv-symbol').fill('ACME');
  await card.getByTestId('cv-save').click();
  await expect(card.getByTestId('cv-err')).toHaveText('Give it a ceiling.');
});

// ---------- writes ----------
test('adding a hold sends the band from the suggestion and reloads', async ({ page }) => {
  let sent = null;
  await page.route('**/api/decisions/convictions/*', (route) => {
    sent = { symbol: route.request().url().split('/').pop(), method: route.request().method(), body: route.request().postDataJSON() };
    route.fulfill({ json: { changed: true, path: '/data/desk.yaml', backup: '/data/desk.yaml.bak', sections: ['rules'], version: 4, item: { symbol: 'NOVA', band_min_pct: 0, band_max_pct: 10, status: null }, suggested: null } });
  });
  await page.goto('/settings/risk?scenario=empty');
  const card = page.getByTestId('convictions');
  await card.getByTestId('cv-add').click();
  await expect(card.getByTestId('cv-new')).toContainText('suggests 0% to 10%');
  await expect(card.getByTestId('cv-symbol')).toBeFocused();
  await card.getByTestId('cv-symbol').fill('nova');
  await card.getByTestId('cv-note-input').fill('  Fresh idea  ');
  await card.getByTestId('cv-save').click();
  await expect(card.getByTestId('cv-msg')).toHaveText('Saved. NOVA now holds 0% to 10%. A backup was kept.');
  expect(sent).toEqual({ symbol: 'NOVA', method: 'PUT', body: { band_min_pct: 0, band_max_pct: 10, note: 'Fresh idea' } });
});

test('editing a band shows the refusal and removing asks twice', async ({ page }) => {
  const calls = [];
  await page.route('**/api/decisions/convictions/*', (route) => {
    const method = route.request().method();
    calls.push(method);
    if (method === 'PUT') route.fulfill({ status: 422, json: { detail: 'band_min_pct must be at most band_max_pct' } });
    else route.fulfill({ json: { changed: true, path: '/data/desk.yaml', backup: '/data/desk.yaml.bak', sections: ['rules'], version: 5 } });
  });
  await page.goto('/settings/risk');
  const row = page.getByTestId('convictions').locator('[data-cv="ORBT"]');
  await row.getByTestId('cv-edit').click();
  await expect(row.getByTestId('cv-min')).toHaveValue('2');
  await row.getByTestId('cv-max').fill('1');
  await row.getByTestId('cv-save').click();
  await expect(row.getByTestId('cv-err')).toHaveText('The floor sits above the ceiling.');
  expect(calls).toEqual([]);
  await row.getByTestId('cv-max').fill('9');
  await row.getByTestId('cv-save').click();
  await expect(row.getByTestId('cv-err')).toHaveText('band_min_pct must be at most band_max_pct');
  await row.getByTestId('cv-drop').click();
  await expect(row.getByTestId('cv-drop')).toHaveText('Yes, remove ORBT');
  expect(calls).toEqual(['PUT']);
  await row.getByTestId('cv-drop').click();
  await expect(page.getByTestId('cv-msg')).toHaveText('Removed ORBT’s band. The single-stock cap covers it again.');
  expect(calls).toEqual(['PUT', 'DELETE']);
});

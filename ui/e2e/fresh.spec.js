import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- desk profile ----------
test('the profile card shows version, source, desks and what is still default', async ({ page }) => {
  await page.goto('/settings');
  const card = page.getByTestId('profile');
  await expect(card).toHaveAttribute('data-source', 'file');
  await expect(card).toContainText('v3');
  await expect(card).toContainText('desk.yaml');
  await expect(card).toContainText('4 on');
  await expect(card).toContainText('Plan keeper, Risk desk');
  await expect(card.getByTestId('still-default').locator('.chip')).toHaveCount(12);
  await expect(card.getByTestId('still-default')).toContainText('Lot method');
  await expect(card.getByTestId('starter')).toHaveCount(0);
});

test('without desk.yaml the card offers the starter command', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']).catch(() => {});
  await page.goto('/settings?scenario=empty');
  const card = page.getByTestId('profile');
  await expect(card).toHaveAttribute('data-source', 'defaults');
  await expect(card).toContainText('Built-in defaults');
  await expect(card.getByTestId('starter').locator('code')).toHaveText('docker exec vektor-desk-cron python -m desk.decisions.profile init');
  await expect(card.getByTestId('still-default')).toContainText('Every setting is still the default.');
  await card.getByRole('button', { name: 'Draft desk.yaml from your data' }).click();
  await expect(card.getByRole('button', { name: /Copied|Copy failed/ })).toBeVisible();
});

test('a broken desk.yaml shows a heads-up and the warnings', async ({ page }) => {
  await page.goto('/settings?scenario=failing');
  const card = page.getByTestId('profile');
  await expect(card.locator('.prof-error')).toContainText('must be a number');
  await expect(card.locator('.lamp-notes li')).toContainText('never runs');
});

// ---------- first day with real-shaped data ----------
test('a first-day desk reads calmly on every page', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/?scenario=fresh');
  await expect(page.getByTestId('health-banner')).toHaveAttribute('data-level', 'warn');
  await expect(page.getByTestId('steps-due')).toBeVisible();
  await page.getByTestId('open-holdings').click();
  await expect(page.locator('.board-row[data-sym="0999999"] .flap')).toBeVisible();
  await page.goto('/decisions?scenario=fresh');
  await expect(page.locator('.ph-big')).toBeVisible();
  await page.goto('/decisions/flight?scenario=fresh');
  await expect(page.locator('.ph-big')).toContainText('No record yet');
  await page.goto('/portfolio?scenario=fresh');
  await expect(page.getByTestId('fi-path')).toHaveAttribute('data-state', 'no_goal');
  await page.goto('/portfolio/risk?scenario=fresh');
  await expect(page.getByTestId('factors')).toContainText('three years of prices');
  await page.goto('/settings?scenario=fresh');
  await expect(page.getByTestId('profile').getByTestId('starter')).toBeVisible();
  await page.goto('/settings/crew?scenario=fresh');
  await expect(page.getByTestId('crew')).toBeVisible();
  expect(errors).toEqual([]);
});

import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- desk profile ----------
test('the profile card shows version, source, desks and what is still default', async ({ page }) => {
  await page.goto('/settings');
  const card = page.getByTestId('profile');
  await expect(card).toHaveAttribute('data-source', 'file');
  await expect(card).toContainText('v3');
  await expect(card).toContainText('Your profile');
  await expect(card).not.toContainText('desk.yaml');
  await expect(card).toContainText('4 on');
  await expect(card).toContainText('Plan keeper, Risk desk');
  await expect(card.getByTestId('still-default').locator('.chip')).toHaveCount(13);
  await expect(card.getByTestId('still-default')).toContainText('Lot method');
  await expect(card.getByTestId('still-default')).toContainText('Margin rate');
  await expect(card.getByTestId('starter')).toHaveCount(0);
});

test('without a profile the card sets one up from a button, with no command to copy', async ({ page }) => {
  const errors = watchErrors(page);
  const READY = JSON.parse(readFileSync(new URL('../src/fixtures/decisions.profile.status.json', import.meta.url), 'utf8'));
  let posts = 0;
  await page.route('**/api/decisions/profile/init', (route) => {
    posts += 1;
    expect(route.request().method()).toBe('POST');
    return route.fulfill({ json: { changed: true, message: 'Your profile is set up from your data.', status: READY } });
  });
  await page.goto('/settings?scenario=empty');
  const card = page.getByTestId('profile');
  await expect(card).toHaveAttribute('data-source', 'defaults');
  await expect(card).toContainText('Built-in defaults');
  await expect(card.getByTestId('still-default')).toContainText('Every setting is still the default.');
  const starter = card.getByTestId('starter');
  await expect(starter).toContainText('No profile yet.');
  await expect(starter.locator('code')).toHaveCount(0);
  await expect(starter).not.toContainText('docker');
  await card.getByRole('button', { name: 'Set up my profile from my data' }).click();
  await expect(card.getByTestId('profile-init-msg')).toHaveText('Your profile is set up from your data.');
  await expect(card.getByTestId('starter')).toHaveCount(0);
  await expect(card).toHaveAttribute('data-source', 'file');
  await expect(card.getByTestId('profile-edit')).toBeVisible();
  expect(posts).toBe(1);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a refused set-up shows the desk sentence as given', async ({ page }) => {
  await page.route('**/api/decisions/profile/init', (route) => route.fulfill({ status: 422, json: { detail: 'The mirror has no positions yet, so there is nothing to build a profile from.' } }));
  await page.goto('/settings?scenario=empty');
  const card = page.getByTestId('profile');
  await card.getByTestId('profile-init').click();
  await expect(card.getByTestId('profile-init-msg')).toHaveText('The mirror has no positions yet, so there is nothing to build a profile from.');
  await expect(card.getByTestId('profile-init')).toBeEnabled();
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
  await expect(page.getByTestId('health-banner')).toHaveCount(0);
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

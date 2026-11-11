import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- you versus the capped you ----------
test('the replay opens on the capped you', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/strategies/habits/replay');
  await expect(page.locator('.ph-big')).toContainText('+$2,424');
  await expect(page.locator('.ph-big')).toContainText('the capped you finishes ahead of you');
  const v = page.getByTestId('versus');
  await expect(v).toHaveAttribute('data-rule', 'house');
  await expect(v).toContainText('You versus the capped you');
  await expect(v).toContainText('Aug 2, 2023 to Nov 9, 2026');
  await expect(page.getByTestId('rule-end')).toContainText('$77,460');
  await expect(page.getByTestId('rule-end')).toContainText('+$2,424 against you');
  await expect(page.getByTestId('rule-picks')).toContainText('+$11,205');
  await expect(page.getByTestId('split-read')).toContainText('Going bigger cost $2,424');
  await expect(v.locator('svg').first()).toBeVisible();
  await expect(page.getByTestId('effects')).toContainText('It helped most on ORBT (+$26,129) and cost most on HELX (−$10,486).');
  await expect(page.getByTestId('events').locator('tbody tr')).toHaveCount(6);
  await expect(page.getByTestId('events')).toContainText('Stepped in 28 times');
  await expect(page.getByTestId('events')).toContainText('The 6 largest of 28.');
  await expect(page.getByTestId('rules').locator('[data-group]')).toHaveCount(3);
  await expect(page.getByTestId('sizing')).toContainText('2 partly on margin');
  await expect(page.getByTestId('replay-note')).toContainText('As of Nov 9, 2026');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('the rule and level combos replay another rule', async ({ page }) => {
  await page.goto('/strategies/habits/replay');
  const v = page.getByTestId('versus');
  await v.getByRole('button', { name: /^Rule/ }).click();
  await page.getByRole('option', { name: 'Sell when it drops' }).click();
  await expect(v).toHaveAttribute('data-rule', 'stop-20');
  await expect(page).toHaveURL(/rule=stop-20/);
  await expect(v).toContainText('You versus the rule');
  await expect(page.getByTestId('rule-acts')).toContainText('7');
  await expect(page.getByTestId('events').locator('tbody tr').first()).toContainText('Stopped out');
  await v.getByRole('button', { name: /^Level/ }).click();
  await page.getByRole('option', { name: '30%' }).click();
  await expect(v).toHaveAttribute('data-rule', 'stop-30');
  await v.getByRole('button', { name: /^Rule/ }).click();
  await page.getByRole('option', { name: 'Hold a year and a day' }).click();
  await expect(v).toHaveAttribute('data-rule', 'long-term');
  await expect(v.getByRole('button', { name: /^Level/ })).toHaveCount(0);
  await expect(page.getByTestId('rule-tax')).toContainText('$46');
  await expect(page.getByTestId('tax-read')).toContainText('28% short-term, 19% long-term');
});

test('a bar in the side by side replays that rule', async ({ page }) => {
  await page.goto('/strategies/habits/replay?rule=no-margin');
  const v = page.getByTestId('versus');
  await expect(v).toHaveAttribute('data-rule', 'no-margin');
  await expect(page.getByTestId('events').locator('tbody tr').first()).toContainText('Not borrowed');
  await page.getByTestId('rules').locator('[data-group="size"]').getByRole('button', { name: /Name cap 5%/ }).click();
  await expect(v).toHaveAttribute('data-rule', 'position-cap-5');
  await expect(page.getByTestId('rule-end')).toContainText('−$91 against you');
  await page.goto('/strategies/habits/replay?rule=nope');
  await expect(v).toHaveAttribute('data-rule', 'house');
});

test('missing prices are named and the replay still runs', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/strategies/habits/replay?scenario=partial');
  await expect(page.getByTestId('versus')).toContainText('Pro forma');
  await expect(page.getByTestId('replay-note')).toContainText('No prices yet for ZEPH');
  expect(errors).toEqual([]);
});

test('no history yet points at the upload', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/strategies/habits/replay?scenario=fresh');
  await expect(page.locator('.ph-big')).toContainText('Warming up');
  const empty = page.getByTestId('replay-empty');
  await expect(empty).toContainText('No Fidelity history yet');
  await expect(empty.getByRole('link', { name: 'Upload the history' })).toHaveAttribute('href', '/settings/data#inbox');
  await expect(page.getByTestId('versus')).toHaveCount(0);
  expect(errors).toEqual([]);
});

// ---------- the way in ----------
test('my habits leads with the replay', async ({ page }) => {
  await page.goto('/strategies/habits');
  const tease = page.getByTestId('replay-tease');
  await expect(tease).toContainText('+$2,424');
  await tease.getByRole('link', { name: 'Open the replay' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Replay');
  await expect(page.getByRole('navigation', { name: 'Strategies views' }).getByRole('link', { name: 'My habits' })).toHaveAttribute('aria-current', 'page');
  await page.getByRole('link', { name: 'Back to My habits' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('My habits');
  await page.goto('/strategies/habits?scenario=fresh');
  await expect(page.getByTestId('replay-tease').getByRole('link', { name: 'See the replay' })).toBeVisible();
});

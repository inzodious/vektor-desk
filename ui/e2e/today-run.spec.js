import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('the Bridge shows today’s run stage by stage', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  const card = page.getByTestId('today-run');
  await expect(card.locator('.run-stage')).toHaveCount(5);
  await expect(card.getByTestId('run-head')).toHaveText('More to run today');
  await expect(card.locator('[data-stage="mirror"]')).toHaveAttribute('data-state', 'waiting');
  await expect(card.locator('[data-stage="engine"]')).toContainText('Ran 8:24 AM · Next 5:20 PM');
  await expect(card.locator('[data-stage="review"]')).toContainText('Arrives with the next desk update');
  await expect(card.locator('[data-stage="desks"]')).toContainText('Next 5:30 PM');
  await expect(card.locator('[data-stage="paper"]')).toContainText('Next 4:45 PM');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('in the evening the strip shows what ran and what is running', async ({ page }) => {
  await page.goto('/?scenario=evening');
  const card = page.getByTestId('today-run');
  await expect(card.getByTestId('run-head')).toHaveText('Running now');
  await expect(card.locator('[data-stage="mirror"]')).toHaveAttribute('data-state', 'ok');
  await expect(card.locator('[data-stage="review"]')).toContainText('Ran 5:36 PM');
  await expect(card.locator('[data-stage="desks"]')).toHaveAttribute('data-state', 'running');
  await expect(card.locator('[data-stage="desks"]')).toContainText('Debrief desk is running');
  await expect(card.locator('[data-stage="paper"]')).toContainText('Ran 4:46 PM');
});

test('a stopped scheduler is called out and All jobs opens Settings at the jobs card', async ({ page }) => {
  await page.goto('/?scenario=down');
  const card = page.getByTestId('today-run');
  await expect(card.getByTestId('run-head')).toHaveText('Scheduler isn’t answering');
  await card.getByTestId('run-jobs').click();
  await expect(page).toHaveURL(/\/settings#jobs$/);
  await expect(page.getByTestId('jobs')).toBeInViewport();
});

test('the strip stays off the Bridge when the jobs API is missing', async ({ page }) => {
  await page.route('**/api/jobs*', (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/');
  await expect(page.getByTestId('discounts')).toBeVisible();
  await expect(page.getByTestId('today-run')).toHaveCount(0);
});

import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- deposits read from activity ----------
test('auto deposits show the rhythm found in activity and money in', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/portfolio');
  const card = page.getByTestId('deposits');
  await expect(card).toHaveAttribute('data-mode', 'auto');
  await expect(card.getByText('From your activity')).toBeVisible();
  await expect(card.getByTestId('rhythm')).toContainText('$500 every month on the 1st to individual-0001');
  await expect(card.getByTestId('rhythm')).toContainText('seen 6 times');
  const free = card.locator('[data-scheduled="false"]');
  await expect(free).toHaveCount(1);
  await expect(free).toContainText('Money in');
  await expect(free).toContainText('Landed Nov 5');
  await expect(free).toHaveAttribute('data-status', 'landed');
  await expect(card.locator('[data-status="late"]')).toHaveCount(0);
  await expect(card.locator('[data-status="expected"]').first()).toContainText('Expected Dec 1');
  expect(errors).toEqual([]);
});

test('auto with no steady rhythm says activity does the talking', async ({ page }) => {
  await page.goto('/portfolio?scenario=quiet');
  const card = page.getByTestId('deposits');
  await expect(card.getByTestId('rhythm-empty')).toContainText('Deposits are read from your activity. None on a steady rhythm right now.');
  await expect(card.getByTestId('rhythm-empty')).not.toContainText('desk.yaml');
  const rows = card.getByTestId('money-in').locator('.row');
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText('$250');
  await expect(card.locator('[data-status="late"], [data-status="expected"]')).toHaveCount(0);
  await expect(page.locator('.kpi', { hasText: 'Next deposit' })).not.toContainText('Nothing scheduled');
});

test('a listed schedule still flags a deposit that has not landed', async ({ page }) => {
  await page.goto('/portfolio?scenario=listed');
  const card = page.getByTestId('deposits');
  await expect(card).toHaveAttribute('data-mode', 'listed');
  await expect(card.getByText('From your activity')).toHaveCount(0);
  const late = card.locator('[data-status="late"]');
  await expect(late).toHaveCount(1);
  await expect(late).toContainText('Not seen yet, due Oct 20');
});

test('settings says deposits come from activity', async ({ page }) => {
  await page.goto('/settings');
  await expect(page.getByTestId('profile')).toContainText('2 deposits read from activity');
});

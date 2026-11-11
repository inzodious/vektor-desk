import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('the day review leads with the change, the debrief and next steps', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/results');
  await expect(page).toHaveURL(/\/results\/day$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Results');
  await expect(page.getByTestId('rs-change')).toHaveText('+$53');
  await expect(page.getByTestId('rs-pct')).toHaveText('+0.31%');
  await expect(page.getByTestId('rs-state')).toHaveText('May restate once');
  await expect(page.getByTestId('rs-label')).toHaveText('Fri Nov 6, 2026');
  await expect(page.getByTestId('rs-debrief')).toContainText('Up $53 on a quiet Friday');
  await expect(page.getByTestId('rs-steps')).toHaveAttribute('data-count', '2');
  await expect(page.getByTestId('rs-versus').locator('[data-vs="spy"]')).toContainText('You’re $32 ahead');
  await expect(page.getByTestId('rs-movers').locator('[data-mover="FXAIX"]')).toContainText('+$114');
  await expect(page.getByTestId('rs-ledger')).toContainText('No deposits, withdrawals or trades');
  await expect(page.getByTestId('rs-risk')).toContainText('One day is too short');
  const phone = test.info().project.name === 'phone';
  await expect(page.getByRole('navigation', { name: phone ? 'Areas, phone' : 'Areas', exact: true }).getByRole('link', { name: 'Results' })).toHaveAttribute('aria-current', 'page');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('the week adds deposits, trades, risk and scores that came due', async ({ page }) => {
  await page.goto('/results/day');
  await page.getByRole('navigation', { name: 'Results views' }).getByRole('link', { name: 'Week' }).click();
  await expect(page.getByTestId('results')).toHaveAttribute('data-kind', 'week');
  await expect(page.getByTestId('rs-change')).toHaveText('+$933');
  await expect(page.locator('.ph-big')).toContainText('+$333 from the market, +$600 you put in');
  await expect(page.getByTestId('rs-kpis').locator('[data-kpi="flows"]')).toContainText('+$600');
  await expect(page.getByTestId('rs-versus')).toContainText('0.34 pts behind the S&P 500');
  const ledger = page.getByTestId('rs-ledger');
  await expect(ledger).toHaveAttribute('data-count', '10');
  await expect(ledger.locator('.rs-lg-row').first()).toContainText('Deposit');
  await expect(ledger.locator('summary')).toHaveText('2 more');
  await expect(page.getByTestId('rs-risk')).toContainText('Deepest dip');
  await expect(page.getByTestId('rs-decisions')).toContainText('90 days on: helped by $230');
  await expect(page.getByTestId('rs-paper')).toContainText('Aggressive tech tilt');
  await expect(page.getByTestId('rs-events')).toContainText('Discount day');
});

test('the stepper walks back a period and Latest returns', async ({ page }) => {
  await page.goto('/results/day');
  await page.getByTestId('rs-older').click();
  await expect(page).toHaveURL(/\/results\/day\?end=2026-11-05$/);
  await expect(page.getByTestId('rs-label')).toHaveText('Thu Nov 5, 2026');
  await expect(page.getByTestId('results')).toHaveAttribute('data-end', '2026-11-05');
  await expect(page.getByTestId('rs-state')).toHaveText('Final');
  await expect(page.getByTestId('rs-debrief-wait')).toBeVisible();
  await page.getByTestId('rs-newer').click();
  await expect(page).toHaveURL(/\/results\/day$/);
  await page.getByTestId('rs-older').click();
  await page.getByTestId('rs-latest').click();
  await expect(page.getByTestId('rs-label')).toHaveText('Fri Nov 6, 2026');
});

test('an open month says so far and waits for its debrief', async ({ page }) => {
  await page.goto('/results/month');
  await expect(page.getByTestId('rs-state')).toHaveText('So far');
  await expect(page.getByTestId('rs-label')).toHaveText('November 2026');
  await expect(page.getByTestId('rs-debrief-wait')).toContainText('The debrief lands when the month closes.');
});

test('a debrief written before the final numbers says so', async ({ page }) => {
  await page.goto('/results/year');
  await expect(page.getByTestId('rs-debrief')).toHaveAttribute('data-state', 'stale');
  await expect(page.getByTestId('rs-debrief')).toContainText('Written before the final numbers.');
});

test('before the first run the page is armed, not empty', async ({ page }) => {
  await page.goto('/results/day?scenario=fresh');
  await expect(page.locator('.ph-big')).toContainText('First run tonight');
  await expect(page.getByTestId('rs-first')).toContainText('The first one runs after tonight’s numbers.');
  await expect(page.getByTestId('results')).toHaveCount(0);
});

test('an older desk without reviews explains itself, and unknown kinds go to Day', async ({ page }) => {
  await page.route('**/api/engine/reviews**', (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/results/decade');
  await expect(page).toHaveURL(/\/results\/day$/);
  await expect(page.getByTestId('rs-first')).toContainText('switch on with the next desk update');
});

test('Results opens from the menu and from the Review stage on the Bridge', async ({ page }) => {
  await page.goto('/?scenario=evening');
  await page.getByTestId('run-results').click();
  await expect(page).toHaveURL(/\/results\/day/);
  await page.goto('/');
  await expect(page.getByTestId('results-link')).toHaveCount(0);
  const phone = test.info().project.name === 'phone';
  await page.getByRole('navigation', { name: phone ? 'Areas, phone' : 'Areas', exact: true }).getByRole('link', { name: 'Results' }).click();
  await expect(page).toHaveURL(/\/results\/day$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Results');
});

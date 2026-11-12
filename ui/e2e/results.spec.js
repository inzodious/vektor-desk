import { readFileSync } from 'node:fs';
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

test('a debrief whose rewrite is late or failed says so in the desk\'s own sentence', async ({ page }) => {
  await page.goto('/results/year');
  await expect(page.getByTestId('rs-debrief')).toHaveAttribute('data-state', 'stale');
  await expect(page.getByTestId('rs-debrief').locator('.rs-stale')).toHaveText('Heads up Written before the final numbers. The rewrite is running late; the next try is tomorrow at 1:40 AM.');
  await page.goto('/results/day?scenario=rewritefail');
  await expect(page.getByTestId('rs-debrief')).toHaveAttribute('data-state', 'stale');
  await expect(page.getByTestId('rs-debrief').locator('.rs-stale')).toHaveText('Heads up Written before the final numbers. The rewrite did not finish; the desk tries again at 5:46 PM.');
});

test('a debrief the desk is about to rewrite shows no warning', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/results/day?scenario=rewriting');
  const card = page.getByTestId('rs-debrief');
  await expect(card).toHaveAttribute('data-state', 'rewriting');
  await expect(card.locator('.rs-headline')).toBeVisible();
  await expect(card.locator('.rs-stale')).toHaveCount(0);
  await expect(card).not.toContainText('Heads up');
  await expect(card).not.toContainText('Written before the final numbers');
  expect(errors).toEqual([]);
});

test('a review that does not carry the rewrite yet asks the debrief desk, once', async ({ page }) => {
  const day = JSON.parse(readFileSync(new URL('../src/fixtures/engine.reviews.day.json', import.meta.url), 'utf8'));
  delete day.debrief.rewrite;
  day.debrief.stale = true;
  let asked = 0;
  let answer = { kind: 'day', end: day.end, stale: true, rewrite: { state: 'due', due_at: '2026-11-09T22:46:00+00:00', words: null } };
  await page.route('**/api/engine/reviews?kind=day*', (route) => route.fulfill({ json: day }));
  await page.route('**/api/agents/debrief?*', (route) => {
    asked += 1;
    return route.fulfill({ json: answer });
  });
  await page.goto('/results/day');
  const card = page.getByTestId('rs-debrief');
  await expect(card).toHaveAttribute('data-state', 'rewriting');
  await expect(card.locator('.rs-stale')).toHaveCount(0);
  expect(asked).toBe(1);
  answer = { ...answer, rewrite: { state: 'late', due_at: null, words: 'Written before the final numbers. The Debrief desk is switched off, so it stays as written.' } };
  await page.reload();
  await expect(card.locator('.rs-stale')).toHaveText('Heads up Written before the final numbers. The Debrief desk is switched off, so it stays as written.');
  await page.goto('/results/week');
  await expect(page.getByTestId('rs-debrief')).toHaveAttribute('data-state', 'ok');
  expect(asked).toBe(2);
});

test('before the first run the page is armed, not empty', async ({ page }) => {
  await page.goto('/results/day?scenario=fresh');
  await expect(page.locator('.ph-big')).toContainText('Nothing to show yet');
  const empty = page.getByTestId('empty-state');
  await expect(empty).toHaveAttribute('data-key', 'results.day');
  await expect(empty).toContainText('The first one runs after tonight’s numbers.');
  await expect(page.getByTestId('results')).toHaveCount(0);
});

test('an older desk without reviews explains itself, and unknown kinds go to Day', async ({ page }) => {
  await page.route('**/api/engine/reviews**', (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/results/decade');
  await expect(page).toHaveURL(/\/results\/day$/);
  await expect(page.getByTestId('empty-state')).toContainText('switch on with the next desk update');
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

import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('the lab list shows stages, strategies with paper progress and rule tests', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/lab/strategies');
  await expect(page.locator('.ph-big')).toContainText('on paper');
  await expect(page.getByTestId('stages').locator('[data-stage="paper"]')).toContainText('1');
  await expect(page.getByTestId('stages').locator('.stage.lit')).toHaveCount(2);
  const list = page.getByTestId('strategies');
  await expect(list.locator('[data-strategy]')).toHaveCount(3);
  await expect(list.locator('[data-strategy]').first()).toHaveAttribute('data-strategy', 'sector-momentum');
  await expect(list.locator('[data-strategy="sector-momentum"]')).toContainText('Day 129 of 182');
  await expect(list.locator('[data-strategy="sector-momentum"]')).toContainText('keep leading');
  await expect(page.getByTestId('rules').locator('[data-rule]')).toHaveCount(3);
  await expect(page.getByTestId('rules').locator('[data-rule="dip-margin"]')).toContainText('Hurts');
  expect(errors).toEqual([]);
});

test('an empty lab says how to start', async ({ page }) => {
  await page.route('**/api/lab/strategies', (r) => r.fulfill({ json: { strategies: [], rules: [], features: [], grammar: {} } }));
  await page.goto('/lab/strategies');
  await expect(page.getByTestId('strategies')).toContainText('Nothing in the lab yet');
  await expect(page.getByTestId('rules')).toContainText('No rule tests yet');
  await expect(page.getByTestId('stages').locator('.stage.lit')).toHaveCount(0);
});

test('a paper strategy shows its idea, verdict lamps, paper money and tear sheet', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/lab/strategies');
  await page.getByTestId('strategies').locator('[data-strategy="sector-momentum"]').click();
  await expect(page).toHaveURL(/\/lab\/strategies\/sector-momentum$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Sector momentum' })).toBeVisible();
  await expect(page.getByTestId('spec')).toContainText('return over 126 days ranked high to low');
  await expect(page.getByTestId('verdict')).toContainText('Passed');
  await expect(page.getByTestId('verdict').locator('[data-lamp]')).toHaveCount(7);
  await expect(page.getByTestId('verdict').locator('[data-lamp="factor"]')).toHaveAttribute('data-status', 'watch');
  const paper = page.getByTestId('paper');
  await expect(paper).toContainText('Day 129 of 182');
  await expect(paper.getByTestId('paper-trades').locator('tbody tr')).toHaveCount(6);
  await paper.getByRole('button', { name: /Show all/ }).click();
  await expect(paper.getByTestId('paper-trades').locator('tbody tr')).not.toHaveCount(6);
  await expect(page.getByTestId('walk-forward').locator('[data-tile]')).toHaveCount(6);
  await expect(page.getByTestId('folds')).toContainText('2016');
  await expect(page.getByTestId('horizons').locator('[data-horizon]')).toHaveCount(3);
  await expect(page.getByTestId('analyses').locator('[data-analysis]')).toHaveCount(5);
  await expect(page.getByTestId('caveats')).toContainText('mostly noise');
  expect(errors).toEqual([]);
});

test('a strategy still in the lab keeps its holdout sealed', async ({ page }) => {
  await page.goto('/lab/strategies/low-vol-sectors');
  await expect(page.getByTestId('verdict')).toContainText('stay sealed');
  await expect(page.getByTestId('paper')).toContainText('Not on paper');
});

test('a rule test compares every setting with never selling', async ({ page }) => {
  await page.goto('/lab/strategies/dip-margin');
  await expect(page.getByRole('heading', { level: 1, name: 'Margin in a dip' })).toBeVisible();
  await expect(page.locator('.ph-big')).toContainText('Hurts');
  await expect(page.getByTestId('setup')).toContainText('$1,000 a month');
  await expect(page.getByTestId('variant-table').locator('[data-variant]')).toHaveCount(2);
  await expect(page.getByTestId('variant-table')).toContainText('Interest');
  await expect(page.getByTestId('baseline')).toContainText('$177,000');
});

test('a spec the lab sent back lists the reasons', async ({ page }) => {
  await page.goto('/lab/strategies/pick-one');
  await expect(page.locator('.ph-big')).toContainText('Sent back');
  await expect(page.getByTestId('rejected')).toContainText('hand-picked');
});

test('an unknown id says so and links back', async ({ page }) => {
  await page.route('**/api/lab/strategies/nobody', (r) => r.fulfill({ status: 404, json: { detail: 'No lab results for this id.' } }));
  await page.goto('/lab/strategies/nobody');
  await expect(page.getByRole('alert')).toContainText('No lab results for this id.');
  await page.getByRole('link', { name: 'All strategies' }).click();
  await expect(page).toHaveURL(/\/lab\/strategies$/);
});

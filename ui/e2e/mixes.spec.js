import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('mixes run safe to risky with bands, reward to risk and a fit badge', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/lab/mixes');
  const cards = page.locator('[data-mix]');
  await expect(cards).toHaveCount(4);
  expect(await cards.evaluateAll((els) => els.map((e) => e.dataset.rank))).toEqual(['2', '3', '4', '5']);
  const held = page.locator('[data-mix="as-held"]');
  await expect(held).toHaveAttribute('data-fit', 'above');
  await expect(held.getByTestId('mix-fit')).toHaveText('Riskier than your band');
  await expect(held).toContainText('your band takes −33%');
  await expect(page.locator('[data-mix="safe-mix"]').getByTestId('mix-fit')).toHaveText('Fits your band');
  await expect(page.locator('[data-mix="tech-tilt"]').getByTestId('mix-chance')).toHaveText('53%');
  await expect(page.locator('[data-mix="tech-tilt"]')).toContainText('Sharpe, fair');
  await expect(page.locator('[data-mix="dip-buy"] svg[role="img"] g[data-years]')).toHaveCount(5);
  await expect(page.getByTestId('mix-assume')).toContainText('FI at $1M by 2035');
  await expect(page.getByText('Best odds of FI:')).toContainText('Aggressive tech tilt at 53%');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('every band chart has a table view', async ({ page }) => {
  await page.goto('/lab/mixes');
  const card = page.locator('[data-mix="safe-mix"]');
  await card.getByRole('button', { name: 'Table view' }).click();
  await expect(card.locator('tbody tr')).toHaveCount(5);
  await expect(card.locator('tbody tr').nth(2)).toContainText('10 years');
});

test('a mix on paper links to its race', async ({ page }) => {
  await page.goto('/lab/mixes');
  const race = page.locator('[data-mix="tech-tilt"]').getByTestId('mix-race');
  await expect(race).toContainText('Day 4 of 182');
  await race.click();
  await expect(page.getByTestId('leaderboard').locator('[data-row="tech-tilt"]')).toContainText('Mix');
  await expect(page.getByTestId('leaderboard').locator('[data-row="low-vol-sectors"] [data-testid="lb-reward"]')).toContainText('Reward to risk 1.12 Sharpe');
});

test('without a risk band or FI goal the cards say what to set', async ({ page }) => {
  await page.goto('/lab/mixes?scenario=noprofile');
  const card = page.locator('[data-mix="safe-mix"]');
  await expect(card.getByRole('link', { name: 'Take the risk check' })).toHaveAttribute('href', '/settings/risk');
  await expect(card.getByTestId('mix-chance')).toHaveText('—');
  await expect(card).toContainText('set an FI goal');
});

test('a mix short on history waits quietly, and a fresh desk explains', async ({ page }) => {
  await page.goto('/lab/mixes?scenario=partial');
  await expect(page.locator('[data-mix="tech-tilt"]')).toHaveAttribute('data-status', 'not_ready');
  await expect(page.locator('[data-mix="tech-tilt"]')).toContainText('has 14');
  await page.goto('/lab/mixes?scenario=fresh');
  await expect(page.getByTestId('mixes-empty')).toContainText('after the first run');
});

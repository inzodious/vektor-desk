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
  await expect(page.locator('[data-mix="tech-tilt"]').getByTestId('mix-fi')).toHaveText('31 years');
  await expect(page.locator('[data-mix="tech-tilt"]').getByTestId('mix-chance')).toHaveText('1% by 2035');
  await expect(page.locator('[data-mix="tech-tilt"]')).toContainText('Fees 0.08% a year');
  await expect(page.locator('[data-mix="tech-tilt"]')).toContainText('Sharpe, fair');
  await expect(page.locator('[data-mix="dip-buy"] svg[role="img"] g[data-years]')).toHaveCount(5);
  await expect(page.getByTestId('mix-assume')).toContainText('FI at $1M by 2035');
  await expect(page.getByText('Best odds of FI')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('time to FI leads the page: the deposit moves it far more than the mix', async ({ page }) => {
  await page.goto('/lab/mixes');
  const head = page.getByTestId('fi-time');
  await expect(head.getByTestId('fi-big')).toContainText('About 32 years');
  await expect(head.getByTestId('fi-big')).toContainText('to $1M at $600 a month, around 2059');
  await expect(head.getByTestId('fi-deposit')).toContainText('28 years');
  await expect(head.getByTestId('fi-deposit')).toContainText('$500 a month takes 34, $10K takes 6.7');
  await expect(head.getByTestId('fi-mix')).toContainText('2.5 years');
  await expect(head.getByTestId('fi-other')).toContainText('39 years');
  await expect(head.getByTestId('fi-chance')).toContainText('Under 1%');
  await expect(head.locator('svg[role="img"] g[data-current="yes"]')).toHaveAttribute('data-deposit', '600');
  await head.getByTestId('fi-ladder').getByRole('button', { name: 'Table view' }).click();
  await expect(head.locator('tbody tr')).toHaveCount(11);
  await expect(head.locator('tr[data-deposit="600"]')).toContainText('$600 (you)');
  await expect(head.locator('tr[data-deposit="10000"]')).toContainText('6.7 years');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

test('the lower-returns switch redraws the headline and every card', async ({ page }) => {
  await page.goto('/lab/mixes');
  const safe = page.locator('[data-mix="safe-mix"]');
  const before = await safe.locator('.mix-kpis b').first().textContent();
  const flip = page.getByTestId('lower-switch');
  await expect(flip).toHaveAttribute('aria-checked', 'false');
  await flip.click();
  await expect(flip).toHaveAttribute('aria-checked', 'true');
  await expect(page).toHaveURL(/case=lower/);
  await expect(page.getByTestId('fi-big')).toContainText('About 39 years');
  await expect(page.getByTestId('fi-other')).toContainText('At normal returns');
  await expect(page.getByTestId('fi-other')).toContainText('32 years');
  await expect(page.getByTestId('fi-deposit')).toContainText('33+ years');
  await expect(safe.getByTestId('mix-fi')).toHaveText('39 years');
  expect(await safe.locator('.mix-kpis b').first().textContent()).not.toBe(before);
  await expect(page.locator('[data-mix="as-held"]').getByTestId('mix-fi')).toHaveText('40+ years');
  await flip.click();
  await expect(page).not.toHaveURL(/case=lower/);
  await expect(page.getByTestId('fi-big')).toContainText('About 32 years');
});

test('as held is a drifting hold, with the topped-up version beside it', async ({ page }) => {
  await page.goto('/lab/mixes');
  const held = page.locator('[data-mix="as-held"]');
  await expect(held).toContainText('left to drift, new money to the safe mix');
  await expect(held.getByTestId('mix-variant')).toContainText('Topped back up to today’s weights');
  await expect(held.getByTestId('mix-variant')).toContainText('bad year −41.8%, past your band');
  await expect(page.locator('[data-mix="safe-mix"]').getByTestId('mix-variant')).toHaveCount(0);
});

test('a conviction hold shows hold, rebalance and trim side by side', async ({ page }) => {
  await page.goto('/lab/mixes');
  const card = page.locator('[data-conviction="ACME"]');
  await expect(card).toContainText('ACME: hold, rebalance or trim');
  await expect(card).toContainText('24% of the book');
  await expect(card.getByRole('link', { name: 'Band 5–15%' })).toHaveAttribute('href', '/settings/risk');
  expect(await card.locator('[data-policy]').evaluateAll((els) => els.map((e) => e.dataset.policy))).toEqual(['hold', 'rebalance', 'trim']);
  await expect(card.locator('[data-policy="hold"]').getByTestId('policy-share')).toHaveText('8%');
  await expect(card.locator('[data-policy="rebalance"]')).toContainText('held there');
  await expect(card.locator('[data-policy="trim"]')).toContainText('2% to 14%');
  await expect(card.locator('[data-policy="trim"] svg[role="img"] g[data-years]')).toHaveCount(4);
  await page.goto('/lab/mixes?scenario=partial');
  await expect(page.locator('[data-conviction="ACME"]')).toHaveAttribute('data-status', 'not_ready');
  await expect(page.locator('[data-conviction="ACME"]')).toContainText('Needs 36 months of ACME prices');
  await page.goto('/lab/mixes?scenario=noprofile');
  await expect(page.locator('[data-conviction]')).toHaveCount(0);
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
  await expect(card.getByTestId('mix-fi')).toHaveText('—');
  await expect(card).toContainText('set an FI goal');
  await expect(page.getByTestId('fi-none')).toContainText('Set an FI goal');
  await expect(page.getByTestId('lower-switch')).toBeVisible();
});

test('a mix short on history waits quietly, and a fresh desk explains', async ({ page }) => {
  await page.goto('/lab/mixes?scenario=partial');
  await expect(page.locator('[data-mix="tech-tilt"]')).toHaveAttribute('data-status', 'not_ready');
  await expect(page.locator('[data-mix="tech-tilt"]')).toContainText('has 14');
  await page.goto('/lab/mixes?scenario=fresh');
  await expect(page.getByTestId('mixes-empty')).toContainText('after the first run');
});

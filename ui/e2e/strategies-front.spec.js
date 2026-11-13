import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- leaderboard ----------
test('the leaderboard groups racers under their own benchmark and ranks on lead against noise', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/strategies');
  const board = page.getByTestId('leaderboard');
  await expect(board.getByTestId('lb-lede')).toContainText('Calm sectors has the firmest lead: +3.7 pts against Plan mix, 6% chance it’s luck.');
  await expect(board.locator('.card-head')).toContainText('Checked at day 182, then every 91 days');
  await expect(board.locator('.lb-row')).toHaveCount(8);
  await expect(board.locator('.lb-group')).toHaveCount(3);
  await expect(board.locator('[data-group="IWM"] .lb-bench')).toContainText('4 racers');
  await expect(board.locator('[data-group="Plan mix"] .lb-bench')).toContainText('2 racers, 1 retired');
  await expect(board.locator('[data-group="IVV"] [data-row="tech-tilt"] .lb-edge')).toContainText('vs IVV');
  await expect(board.locator('[data-group="Plan mix"] [data-row="low-vol-sectors"] .lb-edge')).toContainText('vs Plan mix');
  const top = board.locator('[data-row="insider-cluster-3"]');
  await expect(top.locator('.lb-rank')).toHaveText('1');
  await expect(top.getByTestId('lb-luck')).toHaveText('27% chance it’s luck');
  await expect(top).toContainText('noise band ±9.6 pts');
  await expect(board.locator('[data-row="filings-lane-strong"]')).toContainText('Lane');
  const lane = board.locator('[data-row="filings-lane"]');
  await expect(lane).toContainText('Lane');
  await expect(lane).toContainText('Day 32 of 182 · first check Apr 5, 2027');
  await expect(lane).toHaveAttribute('data-young', 'true');
  await expect(lane.locator('.lb-rank')).toHaveText('·');
  await expect(lane.locator('.lb-edge .chip')).toHaveText('Too new to rank');
  await expect(lane.getByRole('link')).toHaveCount(0);
  await expect(lane.getByTestId('lb-account')).toBeHidden();
  await expect(board.locator('.lb-stat:visible')).toHaveCount(0);
  await lane.getByTestId('lb-more').locator('> summary').click();
  await expect(lane.getByTestId('lb-account')).toBeVisible();
  await expect(lane.getByTestId('lb-account')).toHaveText('Paper account $1,012 of $1,000 (+1.2%) · $906 cash');
  await expect(board.locator('[data-row="low-vol-sectors"]')).toContainText('passed the day 182 check');
  await expect(board.locator('[data-row="sector-momentum"] .lb-edge b')).toHaveClass(/dn/);
  await expect(board.locator('[data-row="sector-momentum"]').getByTestId('lb-luck')).toHaveText('No lead to test');
  await expect(board.locator('[data-row="dip-buyer"] .lb-rank')).toHaveText('—');
  await expect(board.locator('[data-row="dip-buyer"]')).toContainText('Retired at the day 182 check · behind by more than noise');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await board.locator('[data-row="sector-momentum"]').getByRole('link').click();
  await expect(page).toHaveURL(/\/strategies\/sector-momentum/);
  expect(errors).toEqual([]);
});

test('an empty leaderboard explains what starts it', async ({ page }) => {
  await page.goto('/strategies?scenario=empty');
  await expect(page.getByTestId('lb-empty')).toContainText('The filings lane starts the morning after the first filing is scored.');
});

test('a brand-new racer shows too early, not zeros', async ({ page }) => {
  await page.goto('/strategies?scenario=early');
  const row = page.getByTestId('leaderboard').locator('[data-row="filings-lane"]');
  await expect(row).toContainText('Too early');
  await expect(page.getByTestId('lb-lede')).toContainText('just off the line');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

// ---------- desks ----------
test('desks show where each switch comes from and wait for the guard', async ({ page }) => {
  await page.goto('/settings/crew');
  const card = page.getByTestId('crew');
  await expect(card.getByText('Desks', { exact: true })).toBeVisible();
  await expect(card.getByTestId('guard')).toHaveAttribute('data-on', 'true');
  await expect(card.getByTestId('guard')).toContainText('Only Plan keeper and Tax desk run for now');
  await expect(card.locator('[data-desk="risk"]')).toHaveAttribute('data-guarded', 'true');
  await expect(card.locator('[data-desk="risk"]')).toContainText('Next: When the guard lifts');
  await expect(card.locator('[data-desk="tax"] .crew-src')).toHaveText('From your profile');
  await expect(card.locator('[data-desk="filings"]')).toBeVisible();
});

test('lifting the guard asks once, warns, then calls the API', async ({ page }) => {
  const calls = [];
  await page.route('**/api/agents/guard', (route) => {
    calls.push(route.request().postDataJSON());
    route.fulfill({ json: { guard: false, allowed: ['plan_keeper', 'tax'] } });
  });
  await page.goto('/settings/crew');
  const guard = page.getByTestId('guard');
  await guard.getByRole('button', { name: 'Lift the guard' }).click();
  await expect(guard.getByTestId('guard-why')).toContainText('Heads up: Tax desk hasn’t finished a run yet.');
  await guard.getByRole('button', { name: 'Not yet' }).click();
  expect(calls).toEqual([]);
  await guard.getByRole('button', { name: 'Lift the guard' }).click();
  await guard.getByRole('button', { name: 'Lift it' }).click();
  await expect.poll(() => calls).toEqual([{ enabled: false }]);
});

test('a lifted guard can go back, and an app switch can follow desk.yaml again', async ({ page }) => {
  const calls = [];
  await page.route('**/api/agents/**', (route) => {
    const req = route.request();
    if (req.method() === 'GET') return route.fallback();
    calls.push(`${req.method()} ${new URL(req.url()).pathname}`);
    return route.fulfill({ json: {} });
  });
  await page.goto('/settings/crew?scenario=lifted');
  const card = page.getByTestId('crew');
  await expect(card.getByTestId('guard')).toContainText('Guard lifted.');
  await expect(card.locator('[data-desk="risk"]')).not.toContainText('When the guard lifts');
  await card.locator('[data-desk="scout"]').getByRole('button', { name: 'Follow your profile (off)' }).click();
  await card.getByRole('button', { name: 'Put the guard back' }).click();
  await expect.poll(() => calls).toEqual(['DELETE /api/agents/scout/enabled', 'PUT /api/agents/guard']);
});

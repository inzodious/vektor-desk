import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- leaderboard ----------
test('the leaderboard ranks paper strategies against IWM with the filings lane as a row', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/lab/strategies');
  const board = page.getByTestId('leaderboard');
  await expect(board.getByTestId('lb-lede')).toContainText('Calm sectors leads at +3.7 pts against IWM.');
  await expect(board.locator('.lb-row')).toHaveCount(4);
  const lane = board.locator('[data-row="filings-lane"]');
  await expect(lane).toContainText('Lane');
  await expect(lane).toContainText('Day 32 of 182 · 150 to go');
  await expect(lane.getByRole('link')).toHaveCount(0);
  await expect(board.locator('[data-row="sector-momentum"] .lb-edge b')).toHaveClass(/dn/);
  await expect(board.locator('[data-row="dip-buyer"] .lb-rank')).toHaveText('—');
  await board.locator('[data-row="sector-momentum"]').getByRole('link').click();
  await expect(page).toHaveURL(/\/lab\/strategies\/sector-momentum/);
  expect(errors).toEqual([]);
});

test('an empty leaderboard explains what starts it', async ({ page }) => {
  await page.goto('/lab/strategies?scenario=empty');
  await expect(page.getByTestId('lb-empty')).toContainText('The filings lane starts the morning after the first filing is scored.');
});

test('a brand-new racer shows too early, not zeros', async ({ page }) => {
  await page.goto('/lab/strategies?scenario=early');
  const row = page.getByTestId('leaderboard').locator('[data-row="filings-lane"]');
  await expect(row).toContainText('Too early');
  await expect(page.getByTestId('lb-lede')).toContainText('just off the line');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

// ---------- desks ----------
test('desks show where each switch comes from and wait for the guard', async ({ page }) => {
  await page.goto('/settings');
  const card = page.getByTestId('crew');
  await expect(card.getByText('Desks', { exact: true })).toBeVisible();
  await expect(card.getByTestId('guard')).toHaveAttribute('data-on', 'true');
  await expect(card.getByTestId('guard')).toContainText('Only Plan keeper and Tax desk run for now');
  await expect(card.locator('[data-desk="risk"]')).toHaveAttribute('data-guarded', 'true');
  await expect(card.locator('[data-desk="risk"]')).toContainText('Next: When the guard lifts');
  await expect(card.locator('[data-desk="tax"] .crew-src')).toHaveText('From desk.yaml');
  await expect(card.locator('[data-desk="filings"]')).toBeVisible();
});

test('lifting the guard asks once, warns, then calls the API', async ({ page }) => {
  const calls = [];
  await page.route('**/api/agents/guard', (route) => {
    calls.push(route.request().postDataJSON());
    route.fulfill({ json: { guard: false, allowed: ['plan_keeper', 'tax'] } });
  });
  await page.goto('/settings');
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
  await page.goto('/settings?scenario=lifted');
  const card = page.getByTestId('crew');
  await expect(card.getByTestId('guard')).toContainText('Guard lifted.');
  await expect(card.locator('[data-desk="risk"]')).not.toContainText('When the guard lifts');
  await card.locator('[data-desk="scout"]').getByRole('button', { name: 'Follow desk.yaml (off)' }).click();
  await card.getByRole('button', { name: 'Put the guard back' }).click();
  await expect.poll(() => calls).toEqual(['DELETE /api/agents/scout/enabled', 'PUT /api/agents/guard']);
});

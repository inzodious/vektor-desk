import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('keys list what is set without ever showing a value', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/data');
  const card = page.getByTestId('keys');
  await expect(card).toHaveAttribute('data-ready', 'true');
  await expect(card.getByText('11 of 13 set')).toBeVisible();
  await expect(card.locator('[data-key="FINNHUB_API_KEY"]')).toHaveAttribute('data-state', 'pending');
  await expect(card.locator('[data-key="TIINGO_API_KEY"]')).toContainText('Saved 9:00 AM');
  await expect(card.locator('[data-key="TS_AUTHKEY"]')).toContainText('The box turned it down 8:10 AM: That value has a line break.');
  const tiingo = card.locator('[data-key="TIINGO_API_KEY"]');
  await expect(tiingo.getByTestId('key-word')).toHaveText('Tiingo prices key');
  await expect(tiingo.locator('.key-name')).toHaveText('TIINGO_API_KEY');
  const word = await tiingo.getByTestId('key-word').evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  const variable = await tiingo.locator('.key-name').evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(variable).toBeLessThan(word);
  await expect(card.getByTestId('key-word')).toHaveText(['Claude token', 'Claude token expiry date', 'Tiingo prices key', 'Finnhub quotes key', 'FRED rates key', 'SEC contact line', 'Alpaca paper key ID', 'Alpaca paper secret', 'Escape Vektor project', 'Escape Vektor user ID', 'Porkbun key', 'Porkbun secret', 'Tailscale sign-in key']);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('setting a key seals it, clears the box and says it is on its way', async ({ page }) => {
  let sent = null;
  await page.route('**/api/box/keys/*', (route) => {
    sent = { name: route.request().url().split('/').pop(), method: route.request().method(), body: route.request().postDataJSON() };
    route.fulfill({ status: 202, json: { ok: true, name: 'FRED_API_KEY', request_id: 'r1', requested_at: '2026-11-09T16:42:00Z', message: 'Sealed.' } });
  });
  await page.goto('/settings/data');
  const row = page.getByTestId('keys').locator('[data-key="FRED_API_KEY"]');
  await row.getByRole('button', { name: 'Replace FRED rates key' }).click();
  const input = row.getByTestId('key-input');
  await expect(input).toHaveAttribute('type', 'password');
  await expect(input).toBeFocused();
  await input.fill('synthetic-fred-key');
  await row.getByRole('button', { name: 'Seal and send' }).click();
  await expect(row).toContainText('Sealed and sent. The box saves it within 5 min.');
  await expect(row.getByTestId('key-input')).toHaveCount(0);
  expect(sent).toEqual({ name: 'FRED_API_KEY', method: 'PUT', body: { value: 'synthetic-fred-key' } });
});

test('a live Alpaca key never leaves the browser', async ({ page }) => {
  let sent = false;
  await page.route('**/api/box/keys/*', (route) => {
    sent = true;
    route.abort();
  });
  await page.goto('/settings/data');
  const row = page.getByTestId('keys').locator('[data-key="ALPACA_API_KEY_ID"]');
  await row.getByRole('button', { name: 'Replace Alpaca paper key ID' }).click();
  await row.getByTestId('key-input').fill('AKLIVE123');
  await row.getByRole('button', { name: 'Seal and send' }).click();
  await expect(row.getByRole('alert')).toHaveText('Paper key IDs start with PK. Live keys are never accepted.');
  await expect(row.getByTestId('key-input')).toHaveValue('AKLIVE123');
  expect(sent).toBe(false);
});

test('a refused key shows the box’s reason', async ({ page }) => {
  await page.route('**/api/box/keys/*', (route) => route.fulfill({ status: 400, json: { ok: false, error: 'refused', message: 'That URL isn’t the paper API.' } }));
  await page.goto('/settings/data');
  const row = page.getByTestId('keys').locator('[data-key="DESK_UID"]');
  await row.getByRole('button', { name: 'Replace Escape Vektor user ID' }).click();
  await expect(row.getByTestId('key-input')).toHaveAttribute('type', 'text');
  await row.getByTestId('key-input').fill('synthetic-uid');
  await row.getByRole('button', { name: 'Seal and send' }).click();
  await expect(row.getByRole('alert')).toHaveText('That URL isn’t the paper API.');
});

test('keys wait until the box shares its lock', async ({ page }) => {
  await page.goto('/settings/data?scenario=down');
  const card = page.getByTestId('keys');
  await expect(card).toHaveAttribute('data-ready', 'false');
  await expect(card.getByTestId('keys-wait')).toBeVisible();
  await expect(card.getByRole('button', { disabled: false })).toHaveCount(0);
});

test('first run sends a missing token to Keys', async ({ page }) => {
  await page.route(/\/api\/status(\?.*)?$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    route.fulfill({ json: { ...body, claude_token: { state: 'unknown' } } });
  });
  await page.goto('/start');
  await page.getByTestId('first-run').locator('[data-step="token"]').getByRole('link', { name: 'Add the token' }).click();
  await expect(page).toHaveURL(/\/settings\/data#keys$/);
  await expect(page.getByTestId('keys')).toBeInViewport();
});

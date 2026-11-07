import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

const SCENARIOS = [
  { name: 'ok', big: 'All fresh', chips: ['Mirror · Fresh', 'Token · Good'] },
  { name: 'stale', big: '2 to look at', chips: ['Mirror · Stale', 'Token · Renew soon'] },
  { name: 'failing', big: '2 to look at', chips: ['Mirror · Last pull failed', 'Token · Expired'] },
  { name: 'empty', big: '2 to look at', chips: ['Mirror · Not yet', 'Token · Not set'] },
];

for (const s of SCENARIOS) {
  test(`settings shows the ${s.name} desk`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto(`/settings${s.name === 'ok' ? '' : `?scenario=${s.name}`}`);
    await expect(page.locator('.ph-big b')).toHaveText(s.big);
    for (const c of s.chips) await expect(page.getByText(c, { exact: true })).toBeVisible();
    const o = await overflow(page);
    expect(o.scroll).toBeLessThanOrEqual(o.view);
    expect(errors).toEqual([]);
  });
}

test('settings explains a dead API and recovers on retry', async ({ page }) => {
  let down = true;
  await page.route('**/api/status*', (route) => (down ? route.fulfill({ status: 503, body: '{}' }) : route.fallback()));
  await page.goto('/settings');
  await expect(page.getByRole('alert')).toContainText("The desk API didn't answer");
  await expect(page.getByRole('alert')).toContainText('replied with 503');
  down = false;
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.locator('.ph-big b')).toHaveText('All fresh');
});

test('mirror drawer closes on Escape and on an outside click', async ({ page }) => {
  await page.goto('/settings');
  await page.getByTestId('mirror-row').click();
  const dialog = page.getByRole('dialog', { name: 'Mirror tables' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('cell', { name: 'transactions' })).toBeVisible();
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(page.getByTestId('mirror-row')).toBeFocused();
  await page.getByTestId('mirror-row').click();
  await expect(dialog).toBeVisible();
  await page.mouse.click(5, 5);
  await expect(dialog).toBeHidden();
});

test('theme combo picks dark and closes on outside click and Escape', async ({ page }) => {
  await page.goto('/settings');
  const combo = page.getByRole('button', { name: /^Theme/ });
  await combo.click();
  await expect(combo).toHaveAttribute('aria-expanded', 'true');
  await page.locator('.ph-title').click();
  await expect(combo).toHaveAttribute('aria-expanded', 'false');
  await combo.click();
  await page.keyboard.press('Escape');
  await expect(combo).toHaveAttribute('aria-expanded', 'false');
  await combo.click();
  await page.getByRole('option', { name: 'Graphite dark' }).click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await expect(combo).toContainText('Graphite dark');
});

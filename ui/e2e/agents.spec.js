import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('bridge shows the plan keeper brief beside the queue', async ({ page }) => {
  await page.goto('/');
  const brief = page.getByTestId('brief');
  await expect(brief.locator('p')).toHaveCount(4);
  await expect(brief.locator('p[data-tone="watch"]').first()).toContainText('behind the plan shadow');
  await expect(brief.locator('p[data-tone="ok"]').last()).toContainText('Nothing needs you today');
  await expect(brief).toContainText('Plan keeper · Fri 5:33 PM');
  await expect(brief).toContainText('as of Nov 6');
});

test('no brief yet says so instead of guessing', async ({ page }) => {
  await page.route('**/api/agents/brief*', (route) => route.fulfill({ json: { summary: null } }));
  await page.goto('/');
  await expect(page.getByTestId('brief')).toContainText('No brief yet');
});

test('settings shows the crew, usage and run log', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/crew');
  const crew = page.getByTestId('crew');
  await expect(crew.locator('.crew-tile')).toHaveCount(8);
  await expect(crew.locator('.crew-tile[data-desk="risk"]')).toContainText('Not ready yet');
  await expect(crew.locator('.crew-tile[data-desk="tax"]')).toContainText('Nothing new');
  await expect(crew.locator('.crew-tile[data-desk="plan_keeper"]')).toContainText('3 of 7 runs this week');
  await expect(page.getByTestId('usage').getByRole('row')).toHaveCount(8);
  await expect(page.getByTestId('run-log')).toContainText('Timed out');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a desk switch sends the change and reloads', async ({ page }) => {
  let sent = null;
  await page.route('**/api/agents/scout/enabled', async (route) => {
    sent = { method: route.request().method(), body: route.request().postDataJSON() };
    await route.fulfill({ json: { desk: 'scout', enabled: false } });
  });
  await page.goto('/settings/crew');
  await page.getByRole('switch', { name: 'Scout on' }).click();
  await expect.poll(() => sent).toEqual({ method: 'PUT', body: { enabled: false } });
});

test('the kill switch pauses every desk', async ({ page }) => {
  let off = false;
  await page.route('**/api/agents/status', async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ json: off ? { ...body, enabled: false } : body });
  });
  await page.route('**/api/agents/*/enabled', async (route) => {
    off = route.request().url().includes('/%2A/') || route.request().url().includes('/*/');
    await route.fulfill({ json: { desk: '*', enabled: false } });
  });
  await page.goto('/settings/crew');
  await page.getByRole('switch', { name: 'All desks on' }).click();
  await expect(page.getByTestId('crew')).toContainText('All desks are paused');
  await expect(page.getByRole('switch', { name: 'All desks on' })).toHaveAttribute('aria-checked', 'false');
  await expect(page.locator('.crew-tile[data-desk="plan_keeper"]')).toContainText('Next: Off');
});

test('a refused switch explains itself', async ({ page }) => {
  await page.route('**/api/agents/tax/enabled', (route) => route.fulfill({ status: 404, json: { detail: 'unknown desk tax' } }));
  await page.goto('/settings/crew');
  await page.getByRole('switch', { name: 'Tax desk on' }).click();
  await expect(page.getByTestId('crew').getByRole('alert')).toHaveText('unknown desk tax');
});

test('the Tax tab shows the tax calendar with wash windows and dates, plus a table view', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/portfolio/tax');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tax');
  await expect(page.locator('.kpi')).toHaveCount(4);
  const cal = page.getByTestId('tax-calendar');
  await expect(cal.locator('[data-wash]')).toHaveCount(4);
  await expect(cal.locator('.tax-diamond')).toHaveCount(3);
  await expect(cal.locator('.tax-list li')).toHaveCount(3);
  await expect(cal).toContainText('Year-end tax window opens');
  await expect(page.locator('.kpi').first()).toContainText('Needs a lot export');
  await cal.getByRole('button', { name: 'Table view' }).click();
  await expect(cal.getByRole('row', { name: /FTEC window clears/ })).toBeVisible();
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

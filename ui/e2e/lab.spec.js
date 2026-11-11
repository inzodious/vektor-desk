import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- compare ----------
test('compare opens on you against both shadows with every view', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/research/compare');
  await expect(page.getByTestId('slots').locator('.slot[data-slot]')).toHaveCount(3);
  await expect(page.locator('.ph-big')).toContainText('led over 1 year');
  await expect(page.getByTestId('growth').locator('svg')).toBeVisible();
  await expect(page.getByTestId('overlap')).toHaveCount(0);
  await expect(page.getByTestId('multiples').locator('[data-metric]').first()).toBeVisible();
  await expect(page.getByTestId('multiples').locator('[data-metric="expense_pct"]')).toHaveCount(0);
  await expect(page.getByTestId('side-by-side').locator('tbody tr')).toHaveCount(3);
  expect(errors).toEqual([]);
});

test('funds show overlap with the first and a slot can be removed', async ({ page }) => {
  await page.goto('/research/compare?ids=FXAIX,FTEC,VXUS');
  const overlap = page.getByTestId('overlap');
  await expect(overlap).toContainText('Overlap with FXAIX');
  await expect(overlap).toContainText('FTEC');
  await expect(overlap).toContainText('21%');
  await page.getByRole('button', { name: 'Remove VXUS' }).click();
  await expect(page).toHaveURL(/ids=FXAIX%2CFTEC(&|$)/);
  await expect(page.getByTestId('slots').locator('.slot[data-slot]')).toHaveCount(2);
});

test('adding an item takes a ticker or a quick pick and closes on Escape', async ({ page }) => {
  await page.goto('/research/compare');
  const add = page.getByRole('button', { name: 'Add an item' });
  await add.click();
  const pop = page.getByRole('dialog', { name: 'Add an item' });
  await expect(pop).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(pop).toHaveCount(0);
  await add.click();
  await pop.getByRole('textbox', { name: 'Ticker to add' }).fill('bnd');
  await pop.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page).toHaveURL(/ids=portfolio%2Cshadow%3Aplan_shadow%2Cshadow%3Asp500_shadow%2CBND/);
  await add.click();
  await pop.locator('.slot-quick button').first().click();
  await expect(page.getByTestId('slots').locator('.slot[data-slot]')).toHaveCount(5);
  await expect(page.getByTestId('slots')).toContainText('Five is the most at once');
});

test('the window combo lands in the URL', async ({ page }) => {
  await page.goto('/research/compare');
  await page.getByRole('button', { name: /^Window/ }).click();
  await page.getByRole('option', { name: '3 years' }).click();
  await expect(page).toHaveURL(/w=3Y/);
});

test('one item asks for another instead of calling the API', async ({ page }) => {
  let called = false;
  await page.route('**/api/compare**', (r) => {
    called = true;
    return r.continue();
  });
  await page.goto('/research/compare?ids=portfolio');
  await expect(page.locator('.empty-hint').first()).toContainText('Compare needs two to five items');
  expect(called).toBe(false);
});

test('a refused comparison shows the server reason', async ({ page }) => {
  await page.route('**/api/compare**', (r) => r.fulfill({ status: 400, json: { detail: 'Unknown id: ZZZZ' } }));
  await page.goto('/research/compare?ids=FXAIX,ZZZZ');
  const alert = page.getByRole('alert');
  await expect(alert).toContainText("Can't compare that");
  await expect(alert).toContainText('Unknown id: ZZZZ');
});

// ---------- risk ----------
test('risk shows the drop, six instruments and every chart', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/portfolio/risk');
  await expect(page.locator('.ph-big')).toContainText('below the high');
  await expect(page.getByTestId('risk-kpis').locator('[data-kpi]')).toHaveCount(6);
  await expect(page.getByTestId('risk-return').locator('[data-point]')).toHaveCount(7);
  await expect(page.getByTestId('correlation').locator('svg')).toBeVisible();
  await expect(page.getByTestId('drawdowns').locator('svg')).toBeVisible();
  await expect(page.getByTestId('scenarios')).toContainText('Needs older prices');
  await expect(page.getByTestId('scenarios')).toContainText('Market −20%');
  await expect(page.getByTestId('lookthrough')).toContainText('AAA');
  await expect(page.getByTestId('lookthrough')).toContainText('Technology');
  await expect(page.getByTestId('months').locator('svg')).toBeVisible();
  expect(errors).toEqual([]);
});

test('a risk instrument opens its windows and closes on Escape', async ({ page }) => {
  await page.goto('/portfolio/risk');
  await page.locator('[data-kpi="risk.vol"]').click();
  const panel = page.getByRole('dialog', { name: 'Volatility' });
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('3 months');
  await page.keyboard.press('Escape');
  await expect(panel).toBeHidden();
});

test('charts flip to a table view', async ({ page }) => {
  await page.goto('/portfolio/risk');
  const card = page.getByTestId('scenarios');
  await card.getByRole('button', { name: 'Table view' }).click();
  await expect(card.locator('table')).toContainText('Rates +2 points');
});

// ---------- boards ----------
test('a saved board lists, opens and can be removed', async ({ page }) => {
  await page.goto('/research/compare?ids=FXAIX,FTEC');
  await page.getByTestId('save-board').click();
  await expect(page.getByTestId('save-board')).toHaveText('Saved to boards');
  await page.getByRole('link', { name: 'Boards', exact: true }).click();
  const link = page.getByRole('link', { name: /Compare FXAIX, FTEC/ });
  await expect(link).toBeVisible();
  await link.click();
  await expect(page).toHaveURL(/\/research\/compare\?ids=FXAIX%2CFTEC|\/research\/compare\?ids=FXAIX,FTEC/);
  await page.goto('/research/boards');
  await page.getByRole('button', { name: /^Remove Compare/ }).click();
  await expect(page.locator('.empty-hint')).toContainText('No boards yet');
});

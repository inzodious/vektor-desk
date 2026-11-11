import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, record, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

const card = (page, text) => page.locator('.prop', { hasText: text }).first();

test('queue lists proposals and opens the first in the detail', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/decisions');
  await expect(page.locator('.ph-big b')).toHaveText('4');
  await expect(page.locator('.ph-big')).toContainText('2 need a reason');
  await expect(page.locator('.prop')).toHaveCount(4);
  const detail = page.getByTestId('detail');
  await expect(detail.getByRole('heading', { level: 2 })).toHaveText('Buy $400 ACME');
  await expect(page.locator('.lamp')).toHaveCount(6);
  await expect(page.locator('.lamp[data-lamp="funding"]')).toHaveAttribute('data-status', 'act');
  await expect(page.getByTestId('override')).toContainText('2 lights need a reason');
  await expect(page.locator('.ticket .stamp')).toHaveText('DRAFT');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('approve over a lit lamp asks for a reason first, then logs the override', async ({ page }) => {
  let body = null;
  await page.route('**/api/decisions/*/approve', async (route) => {
    body = route.request().postDataJSON();
    await route.fulfill({ json: record({ title: 'Buy $400 ACME', override: true }) });
  });
  await page.goto('/decisions');
  await page.getByRole('button', { name: 'Approve with reason' }).click();
  await expect(page.getByRole('alert')).toContainText('one-line reason');
  expect(body).toBeNull();
  await expect(page.getByRole('textbox', { name: 'One-line reason' })).toBeFocused();
  await page.getByRole('textbox', { name: 'One-line reason' }).fill('Small, and I accept the margin cost');
  await page.getByRole('button', { name: 'Approve with reason' }).click();
  await expect(page.locator('.act-note')).toContainText('Approved: Buy $400 ACME');
  expect(body).toEqual({ reason: 'Small, and I accept the margin cost' });
});

test('pass and log it needs a reason too', async ({ page }) => {
  let hit = false;
  await page.route('**/api/decisions/*/pass', async (route) => {
    hit = true;
    await route.fulfill({ json: record({ status: 'passed', title: 'Buy $400 ACME' }) });
  });
  await page.goto('/decisions');
  await page.getByRole('button', { name: 'Pass and log it' }).click();
  await expect(page.getByRole('alert')).toContainText('A pass needs a one-line reason');
  await page.getByRole('textbox', { name: 'One-line reason' }).fill('Not on margin');
  await page.getByRole('button', { name: 'Pass and log it' }).click();
  await expect(page.locator('.act-note')).toContainText('Passed and logged');
  expect(hit).toBe(true);
});

test('a clean proposal approves without a reason box', async ({ page }) => {
  await page.route('**/api/decisions/*/approve', (route) => route.fulfill({ json: record({ title: 'Route deposit to $180 VXUS' }) }));
  await page.goto('/decisions');
  await card(page, 'Route deposit').click();
  await expect(page).toHaveURL(/\?d=/);
  await expect(page.getByTestId('override')).toHaveCount(0);
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.locator('.act-note')).toContainText('It is on the To place list');
});

test('server refusals show as plain sentences', async ({ page }) => {
  await page.route('**/api/decisions/*/snooze', (route) => route.fulfill({ status: 409, json: { detail: 'This decision is already dismissed.' } }));
  await page.goto('/decisions');
  await page.getByRole('button', { name: 'Snooze a day' }).click();
  await expect(page.getByRole('alert')).toHaveText('This decision is already dismissed.');
});

test('a heads up lamp explains itself and the desk combo filters', async ({ page }) => {
  await page.goto('/decisions');
  await card(page, 'Trim').click();
  await expect(page.locator('.lamp[data-lamp="lots_tax"]')).toHaveAttribute('data-status', 'watch');
  await expect(page.locator('.lamp-notes')).toContainText('No lot export');
  await expect(page.getByTestId('detail')).toContainText('Skeptic · flag');
  await page.getByRole('button', { name: /^Desk/ }).click();
  await page.getByRole('option', { name: 'Risk desk' }).click();
  await expect(page.locator('.prop')).toHaveCount(1);
  await expect(page.getByTestId('detail').getByRole('heading', { level: 2 })).toContainText('Hold off');
  await expect(page.getByText('Advice only')).toBeVisible();
});

test('the order ticket copies fields', async ({ page, context, browserName }) => {
  test.skip(browserName !== 'chromium');
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/decisions');
  await page.getByRole('button', { name: 'Copy symbol' }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('ACME');
  await page.getByRole('button', { name: 'Copy the whole ticket' }).click();
  await expect(page.getByRole('button', { name: 'Copied' })).toBeVisible();
});

test('approved trades wait in To place until marked placed', async ({ page }) => {
  let hit = false;
  await page.route('**/api/decisions/*/placed', async (route) => {
    hit = true;
    await route.fulfill({ json: record({ status: 'placed' }) });
  });
  await page.goto('/decisions');
  const box = page.getByTestId('to-place');
  await expect(box).toContainText('BND');
  await box.getByRole('button', { name: 'Mark placed' }).click();
  await expect(page.locator('.act-note')).toContainText('Marked placed');
  expect(hit).toBe(true);
});

test('an empty queue says so', async ({ page }) => {
  await page.goto('/decisions?scenario=empty');
  await expect(page.getByText('Queue is clear')).toBeVisible();
});

test('the queue explains a dead API', async ({ page }) => {
  await page.route('**/api/decisions/queue*', (route) => route.fulfill({ status: 503, body: '{}' }));
  await page.goto('/decisions');
  await expect(page.getByRole('alert')).toContainText("The desk API didn't answer");
});

test('journal shows the stamped ledger, streak and unmatched trades', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/decisions/journal');
  await expect(page.locator('.stamp-day').first()).toBeVisible();
  await expect(page.locator('.ledger-row[data-status="dismissed"]', { hasText: '“Too small to bother with”' }).first()).toBeVisible();
  await expect(page.locator('.ledger-row[data-status="approved"]').first()).toContainText('To place');
  await expect(page.locator('.ledger-row [data-score="90D"]').first()).toContainText('vs the safe mix, 90 days');
  await expect(page.getByTestId('streak')).toContainText('days without an unlogged trade');
  await expect(page.getByTestId('unmatched').locator('.um')).toHaveCount(5);
  await page.getByRole('button', { name: /^Show \d+ more$/ }).click();
  await expect(page.getByTestId('unmatched').locator('.um')).toHaveCount(24);
  await page.getByRole('button', { name: /^Status/ }).click();
  await page.getByRole('option', { name: 'Dismissed' }).click();
  await expect(page.locator('.ledger-row[data-status="dismissed"]').first()).toBeVisible();
  await expect(page.locator('.ledger-row:not([data-status="dismissed"])')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('the journal pages twenty entries at a time and keeps the page in the URL', async ({ page }) => {
  await page.goto('/decisions/journal');
  const card = page.getByTestId('journal');
  await expect(card).toHaveAttribute('data-total', '84');
  await expect(card).toHaveAttribute('data-pages', '5');
  await expect(card.locator('.ledger-row')).toHaveCount(20);
  await expect(card.getByTestId('journal-count')).toHaveText('84 entries');
  const pager = card.getByTestId('journal-pager');
  await expect(pager).toContainText('1–20 of 84 · page 1 of 5');
  await expect(pager.getByRole('button', { name: 'Newer' })).toBeDisabled();
  await pager.getByRole('button', { name: 'Older' }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(pager).toContainText('21–40 of 84 · page 2 of 5');
  await page.goto('/decisions/journal?page=5');
  await expect(card.locator('.ledger-row')).toHaveCount(4);
  await expect(pager.getByRole('button', { name: 'Older' })).toBeDisabled();
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

test('journal filters stack, reset the page and clear in one press', async ({ page }) => {
  await page.goto('/decisions/journal?page=3');
  const card = page.getByTestId('journal');
  await card.getByRole('button', { name: /^Symbol/ }).click();
  await page.getByRole('option', { name: 'NOVA' }).click();
  await expect(page).toHaveURL(/symbol=NOVA/);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page).not.toHaveURL(/page=/);
  await expect(card).toHaveAttribute('data-total', '14');
  await expect(card.getByTestId('journal-count')).toHaveText('14 of 84 entries');
  await expect(card.getByTestId('journal-pager')).toHaveCount(0);
  await card.getByRole('button', { name: /^Origin/ }).click();
  await page.getByRole('option', { name: 'You' }).click();
  await expect(page).toHaveURL(/origin=you/);
  await expect(card).toHaveAttribute('data-total', '6');
  await page.reload();
  await expect(card).toHaveAttribute('data-total', '6');
  await expect(card.getByTestId('journal-count')).toHaveText('6 of 84 entries');
  await card.getByTestId('journal-clear').click();
  await expect(card).toHaveAttribute('data-total', '84');
  await expect(page).not.toHaveURL(/symbol=/);
});

test('logging an unmatched trade posts the reason', async ({ page }) => {
  let body = null;
  await page.route('**/api/decisions/unmatched/*/log', async (route) => {
    body = route.request().postDataJSON();
    await route.fulfill({ json: record({ status: 'filled' }) });
  });
  await page.goto('/decisions/journal');
  const box = page.getByTestId('unmatched');
  await box.getByRole('button', { name: 'Log it' }).first().click();
  await box.getByRole('textbox').fill('Monthly deposit routine');
  await box.getByRole('button', { name: 'Save to the journal' }).click();
  await expect.poll(() => body).toEqual({ thesis: 'Monthly deposit routine', reason: 'Monthly deposit routine' });
});

test('ledger rows open the symbol sheet', async ({ page }) => {
  await page.goto('/decisions/journal');
  await page.locator('.ledger-row[data-sym="FXAIX"]').first().click();
  await expect(page.getByRole('dialog', { name: 'FXAIX symbol sheet' })).toBeVisible();
});

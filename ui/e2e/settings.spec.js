import { readFileSync } from 'node:fs';
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
  await page.goto('/settings/data');
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

test('Data freshness lists the names whose prices are behind, and says so when none are', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/data');
  const card = page.getByTestId('price-history');
  await expect(card).toHaveAttribute('data-state', 'behind');
  await expect(card).toContainText('8 names still waiting on the close for Fri Nov 6, 1 of them yours. The desk asks every hour, day and night.');
  await expect(card.locator('.chip')).toHaveText('8 behind');
  await expect(card.locator('li')).toHaveCount(4);
  await expect(card.locator('li').first()).toContainText('FXAIX');
  await expect(card.locator('li').first()).toContainText('You hold it · Last close Thu Nov 5, asked Today, 6:13 AM ET');
  await expect(card.locator('li[data-sym="NOVA"] .ph-note')).toHaveText('Tiingo did not answer for NOVA');
  await expect(card.locator('li[data-sym="ZZNEW"]')).toContainText('No price history yet');
  await expect(card.locator('li[data-sym="ZZNEW"] .ph-note')).toHaveText('Set aside until Mon Nov 16, 6:13 AM ET: Tiingo has no prices for ZZNEW');
  await expect(card.locator('li[data-sym="ACME"]')).toHaveCount(0);
  await card.getByRole('button', { name: 'Show all 8' }).click();
  await expect(card.locator('li')).toHaveCount(8);
  await expect(card).toContainText('Last ask, Today, 11:13 AM ET: Asked Tiingo for 8 names.');
  await expect(card).not.toContainText('{');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);

  await page.goto('/settings/data?scenario=current');
  await expect(page.getByTestId('price-history')).toHaveAttribute('data-state', 'ok');
  await expect(page.getByTestId('price-history')).toContainText('Every name the desk follows daily has its close for Fri Nov 6.');
  await expect(page.getByTestId('price-history').locator('li')).toHaveCount(0);
  expect(errors).toEqual([]);

  await page.route('**/api/engine/backfill*', (route) => route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not Found"}' }));
  await page.goto('/settings/data');
  await expect(page.getByTestId('freshness')).toBeVisible();
  await expect(page.getByTestId('price-history')).toHaveCount(0);
});

test('the gear opens Settings and the six entries reach every section', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  await expect(page.getByRole('navigation', { name: /^Areas/ }).filter({ visible: true }).getByRole('link', { name: 'Settings' })).toHaveCount(0);
  await page.getByTestId('settings-open').click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByTestId('settings-open')).toHaveAttribute('aria-current', 'page');
  const tabs = page.getByRole('navigation', { name: 'Settings views' });
  await expect(tabs.getByRole('link')).toHaveText(['Desk', 'Crew', 'Data', 'Box', 'Risk check', 'First run']);
  await expect(page.getByTestId('profile')).toBeVisible();
  await expect(page.getByTestId('start-here')).toBeVisible();
  await expect(page.getByTestId('jobs')).toHaveCount(0);
  await tabs.getByRole('link', { name: 'Crew' }).click();
  await expect(page.getByTestId('settings-tab')).toHaveAttribute('data-tab', 'crew');
  await expect(page.getByTestId('crew')).toBeVisible();
  await expect(page.getByTestId('profile')).toHaveCount(0);
  await tabs.getByRole('link', { name: 'Data' }).click();
  await expect(page.getByTestId('freshness')).toBeVisible();
  await expect(page.getByTestId('inbox')).toBeVisible();
  await expect(page.getByTestId('keys')).toBeVisible();
  await tabs.getByRole('link', { name: 'Box' }).click();
  await expect(page.getByTestId('jobs')).toBeVisible();
  await expect(page.getByTestId('box')).toBeVisible();
  await expect(page.getByTestId('token')).toBeVisible();
  await tabs.getByRole('link', { name: 'Risk check' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Risk check');
  await expect(page.getByRole('navigation', { name: 'Settings views' }).getByRole('link', { name: 'Risk check' })).toHaveAttribute('aria-current', 'page');
  await page.getByRole('navigation', { name: 'Settings views' }).getByRole('link', { name: 'First run' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('First run');
  expect(errors).toEqual([]);
});

test('old settings section links land on the tab that holds the section', async ({ page }) => {
  await page.goto('/settings#jobs');
  await expect(page).toHaveURL(/\/settings\/box#jobs$/);
  await expect(page.getByTestId('jobs')).toBeVisible();
  await page.goto('/settings#inbox');
  await expect(page).toHaveURL(/\/settings\/data#inbox$/);
  await expect(page.getByTestId('inbox')).toBeInViewport();
  await page.goto('/settings#keys');
  await expect(page).toHaveURL(/\/settings\/data#keys$/);
});

test('each settings tab stays within three phone screens and two desktop screens', async ({ page }, info) => {
  const phone = info.project.name === 'phone';
  for (const path of ['/settings', '/settings/crew', '/settings/data']) {
    await page.goto(path);
    await expect(page.getByTestId('settings-tab')).toBeVisible();
    await page.waitForLoadState('networkidle');
    const m = await page.evaluate(() => ({ h: document.documentElement.scrollHeight, v: window.innerHeight }));
    expect(m.h / m.v, path).toBeLessThanOrEqual(phone ? 3.6 : 2.2);
  }
});

test('Box lists each service as up or down in words, closed until opened', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/box');
  const card = page.getByTestId('services');
  await expect(card).toHaveJSProperty('open', false);
  await expect(card.locator('summary')).toContainText('All running');
  await expect(card.locator('summary')).toContainText('All 5 desk services are running.');
  await card.locator('summary').click();
  await expect(card.locator('.job-row')).toHaveCount(5);
  await expect(card.locator('[data-service="api"]')).toContainText('The app');
  await expect(card.locator('[data-service="api"]')).toContainText('Up');
  await expect(card.locator('[data-service="api"]')).toContainText('The app has been running for 3 hours.');
  await expect(card).not.toContainText('vektor-desk-');
  await expect(card).not.toContainText('100.64.0.10');
  await expect(card.getByTestId('services-link')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);

  await page.goto('/settings/box?scenario=trouble');
  await expect(card.locator('summary')).toContainText('Needs a look');
  await card.locator('summary').click();
  await expect(card.locator('[data-service="tailscale"]')).toContainText('Restarting');
  await expect(card.locator('[data-service="tailscale"]')).toContainText('The Tailscale link keeps stopping and starting.');
  await expect(card.locator('summary')).toContainText('The box is signed out of your tailnet. Add a new auth key in Settings, then Redeploy.');
  await expect(card.getByTestId('services-link')).toHaveCount(0);
  await expect(card).not.toContainText('login-state');
  const t = await overflow(page);
  expect(t.scroll).toBeLessThanOrEqual(t.view);
  expect(errors).toEqual([]);
});

test('an older desk that sends no services draws no Services card', async ({ page }) => {
  const { containers, ...older } = JSON.parse(readFileSync(new URL('../src/fixtures/status.json', import.meta.url), 'utf8'));
  expect(containers.services).toHaveLength(5);
  await page.route('**/api/status*', (route) => route.fulfill({ json: older }));
  await page.goto('/settings/box');
  await expect(page.getByTestId('jobs')).toBeVisible();
  await expect(page.getByTestId('services')).toHaveCount(0);
});

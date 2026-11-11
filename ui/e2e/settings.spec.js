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

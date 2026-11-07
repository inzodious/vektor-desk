import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, ROUTES, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

for (const r of ROUTES) {
  test(`${r.path} loads cleanly and fits the screen`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto(r.path);
    await expect(page.getByRole('heading', { level: 1, name: r.h1 })).toBeVisible();
    await page.waitForLoadState('networkidle');
    const o = await overflow(page);
    expect(o.scroll).toBeLessThanOrEqual(o.view);
    expect(errors).toEqual([]);
  });
}

test('nav marks the current area and moves between pages', async ({ page, isMobile }, info) => {
  await page.goto('/plan');
  const phone = info.project.name === 'phone' || isMobile;
  const nav = page.getByRole('navigation', { name: phone ? 'Areas, phone' : 'Areas', exact: true });
  await expect(nav).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Plan' })).toHaveAttribute('aria-current', 'page');
  await nav.getByRole('link', { name: /Lab/ }).click();
  await expect(page).toHaveURL(/\/lab$/);
  await expect(page).toHaveTitle('Lab · Vektor Desk');
  const other = page.getByRole('navigation', { name: phone ? 'Areas' : 'Areas, phone', exact: true });
  await expect(other).toBeHidden();
});

test('theme toggle switches to graphite dark and sticks after reload', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('html')).not.toHaveClass(/dark/);
  await page.getByRole('button', { name: 'Switch to dark mode' }).click();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await expect(page.getByRole('button', { name: 'Switch to light mode' })).toBeVisible();
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0d0e10');
});

test('market clock reads the session from Eastern time', async ({ page }) => {
  await page.goto('/');
  const clock = page.getByTestId('market-clock');
  await expect(clock).toHaveAttribute('data-state', 'open');
  await expect(clock).toContainText('11:42 AM ET');
});

test('market clock shows closed on the weekend', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-11-07T16:00:00Z'));
  await page.goto('/');
  await expect(page.getByTestId('market-clock')).toHaveAttribute('data-state', 'closed');
  await expect(page.getByTestId('market-clock')).toHaveAttribute('title', 'Opens Mon 9:30 AM ET');
});

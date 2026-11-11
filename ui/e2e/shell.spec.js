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
  await page.goto('/portfolio');
  const phone = info.project.name === 'phone' || isMobile;
  const nav = page.getByRole('navigation', { name: phone ? 'Areas, phone' : 'Areas', exact: true });
  await expect(nav).toBeVisible();
  await expect(nav.getByRole('link')).toHaveText([/Bridge/, /Results/, /Portfolio/, /Strategies/, /Deci/, /Research/]);
  await expect(nav.getByRole('link', { name: 'Portfolio' })).toHaveAttribute('aria-current', 'page');
  await nav.getByRole('link', { name: /Strategies/ }).click();
  await expect(page).toHaveURL(/\/strategies$/);
  await expect(page).toHaveTitle('Strategies · Vektor Desk');
  await nav.getByRole('link', { name: /Results/ }).click();
  await expect(page).toHaveURL(/\/results\/day$/);
  await expect(nav.getByRole('link', { name: /Results/ })).toHaveAttribute('aria-current', 'page');
  await expect(nav.getByRole('link', { name: /Bridge/ })).not.toHaveAttribute('aria-current', 'page');
  const other = page.getByRole('navigation', { name: phone ? 'Areas' : 'Areas, phone', exact: true });
  await expect(other).toBeHidden();
});

test('old Plan and Lab links land on their new pages and keep their query', async ({ page }) => {
  const moves = [
    ['/plan', /\/portfolio$/],
    ['/plan/stocks?symbol=BND', /\/portfolio\/stocks\?symbol=BND$/],
    ['/lab', /\/strategies$/],
    ['/lab?ids=FXAIX,FTEC', /\/research\/compare\?ids=FXAIX,FTEC$/],
    ['/lab/risk', /\/portfolio\/risk$/],
    ['/lab/mixes?case=lower', /\/strategies\/mixes\?case=lower$/],
    ['/lab/strategies/sector-momentum', /\/strategies\/sector-momentum$/],
    ['/lab/patterns', /\/strategies\/habits$/],
    ['/lab/patterns/replay?rule=stop-20', /\/strategies\/habits\/replay\?rule=stop-20$/],
    ['/lab/boards', /\/research\/boards$/],
  ];
  for (const [from, to] of moves) {
    await page.goto(from);
    await expect(page, from).toHaveURL(to);
  }
  await page.goto('/lab/nowhere');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Lost in orbit');
});

test('each area shows its own subtabs', async ({ page }) => {
  const groups = [
    ['/portfolio', 'Portfolio views', ['Holdings', 'Stock plans', 'Risk', 'Tax']],
    ['/portfolio/risk', 'Portfolio views', ['Holdings', 'Stock plans', 'Risk', 'Tax']],
    ['/strategies', 'Strategies views', ['Race', 'Mixes', 'My habits']],
    ['/strategies/sector-momentum', 'Strategies views', ['Race', 'Mixes', 'My habits']],
    ['/research/compare', 'Research views', ['Dossiers', 'Sources', 'Watchlist', 'Calendar', 'Compare', 'Boards']],
  ];
  for (const [path, label, tabs] of groups) {
    await page.goto(path);
    await expect(page.getByRole('navigation', { name: label }).getByRole('link'), path).toHaveText(tabs);
  }
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

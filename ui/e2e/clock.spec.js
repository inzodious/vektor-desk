import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

const WALK = ['/', '/results/day', '/portfolio', '/decisions', '/research'];

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

async function clock(page) {
  const line = page.getByTestId('asof');
  await expect(line).toBeVisible();
  return {
    day: await line.getAttribute('data-day'),
    words: (await page.getByTestId('asof-day').innerText()).trim(),
    change: (await page.getByTestId('asof-change').innerText()).trim(),
    cash: (await page.getByTestId('asof-cash').innerText()).trim(),
    margin: (await page.getByTestId('asof-margin').innerText()).trim(),
  };
}

async function walk(page, scenario) {
  const seen = [];
  for (const path of WALK) {
    await page.goto(`${path}${scenario ? `?scenario=${scenario}` : ''}`);
    seen.push(await clock(page));
    const o = await overflow(page);
    expect(o.scroll, path).toBeLessThanOrEqual(o.view);
  }
  return seen;
}

test('Bridge, Results, Portfolio, Decisions and Research agree on the day, its change, cash ready and margin', async ({ page }) => {
  const errors = watchErrors(page);
  const seen = await walk(page, 'evening');
  seen.forEach((c) => expect(c).toEqual({ day: '2026-11-09', words: 'As of Mon Nov 9, 5:21 PM ET', change: '+$87', cash: '$142', margin: '$1,500' }));

  await page.goto('/?scenario=evening');
  await expect(page.getByTestId('asof')).toContainText('Provisional');
  await expect(page.getByTestId('bridge-value')).toHaveText('$16,480');
  await expect(page.getByTestId('bridge-change')).toHaveText('+$87 · +0.53% today');
  const kpis = page.getByTestId('bridge-kpis');
  await expect(kpis.locator('[data-kpi="value.market"]')).toContainText('+$87 today');
  await expect(kpis.locator('[data-kpi="cash.ready"] .v')).toHaveText(seen[0].cash);
  await expect(kpis.locator('[data-kpi="margin.debit"] .v')).toHaveText(seen[0].margin);
  await expect(kpis).not.toContainText('engine');
  await expect(kpis).not.toContainText('from ');
  await expect(page.getByTestId('movers')).toHaveCount(0);

  await page.goto('/results/day?scenario=evening');
  await expect(page.getByTestId('rs-label')).toHaveText('Mon Nov 9, 2026');
  await expect(page.getByTestId('results')).toHaveAttribute('data-end', seen[0].day);
  await expect(page.getByTestId('rs-change')).toHaveText(seen[0].change);
  await expect(page.getByTestId('rs-written')).toContainText('About Mon Nov 9 · written Nov 9');
  await expect(page.getByTestId('rs-behind')).toHaveCount(0);
  await expect(page.getByTestId('rs-provisional')).toHaveText('Provisional');
  await expect(page.getByTestId('rs-provisional-note')).toHaveText('Mon Nov 9 uses closing quotes until the official closes land overnight. FXAIX carries its last price.');
  expect(errors).toEqual([]);
});

test('with the market open every page leads with the live day and its change, never the day before', async ({ page }) => {
  const errors = watchErrors(page);
  const seen = await walk(page, '');
  seen.forEach((c) => expect(c).toEqual({ day: '2026-11-09', words: 'As of Mon Nov 9, 11:40 AM ET', change: '−$86', cash: '$142', margin: 'none' }));
  await expect(page.getByTestId('asof')).toContainText('Live');
  await expect(page.getByTestId('asof-book')).toHaveText('Book as of Fri Nov 6, at the close');
  await expect(page.getByTestId('asof')).not.toContainText('+$53');

  await page.goto('/');
  await expect(page.locator('.ph-kick')).toHaveText('Bridge · Live, Mon Nov 9, 11:40 AM ET');
  await expect(page.getByTestId('bridge-value')).toHaveText('$16,308');
  await expect(page.getByTestId('bridge-change')).toHaveText('−$86 · −0.52% today');
  await expect(page.getByTestId('movers')).toBeVisible();
  await expect(page.getByTestId('bridge-kpis').locator('[data-kpi="margin.debit"] .v')).toHaveText('$0');

  await page.goto('/results/day');
  await expect(page.getByTestId('rs-change')).toHaveText('+$53');
  await expect(page.getByTestId('results')).toHaveAttribute('data-end', '2026-11-06');
  await expect(page.getByTestId('rs-provisional')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('after the close, with the closing run still to come, every page shows the newest quotes and no Behind flag', async ({ page }) => {
  const errors = watchErrors(page);
  const seen = await walk(page, 'afterclose');
  seen.forEach((c) => expect(c).toEqual({ day: '2026-11-09', words: 'As of Mon Nov 9, last quotes 6:40 PM ET', change: '+$121', cash: '$142', margin: 'none' }));
  const line = page.getByTestId('asof');
  await expect(line).not.toContainText('Behind');
  await expect(line).not.toContainText('+$53');
  await expect(page.getByTestId('asof-book')).toHaveText('Book as of Fri Nov 6, at the close');
  await expect(line).toHaveAttribute('title', /Closing quotes are in for Mon Nov 9/);

  await page.goto('/?scenario=afterclose');
  await expect(page.getByTestId('bridge-change')).toHaveText('+$121 · +0.74% today');
  expect(errors).toEqual([]);
});

test('funds still waiting on a close are named on the line in the desk’s words, on every page', async ({ page }) => {
  const errors = watchErrors(page);
  const seen = await walk(page, 'waiting');
  seen.forEach((c) => expect(c).toMatchObject({ day: '2026-11-09', words: 'As of Mon Nov 9, at the close' }));
  const wait = page.getByTestId('asof-waiting');
  await expect(wait).toHaveText('Waiting on the official close for FXAIX and FTEC; the day is restated when it lands.');
  await expect(page.getByTestId('asof')).toContainText('Provisional');
  const line = await page.getByTestId('asof').boundingBox();
  const box = await wait.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(line.x - 1);
  expect(box.x + box.width).toBeLessThanOrEqual(line.x + line.width + 1);
  expect(box.height).toBeLessThanOrEqual(64);

  await page.goto('/?scenario=evening');
  await expect(page.getByTestId('asof')).toBeVisible();
  await expect(page.getByTestId('asof-waiting')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a number from an older day carries its day in words', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/?scenario=lagging');
  await expect(page.getByTestId('asof-day')).toHaveText('As of Mon Nov 9, at the close');
  const kpis = page.getByTestId('bridge-kpis');
  await expect(kpis.locator('[data-kpi="bm.excess"]')).toContainText('from Fri Nov 6');
  await expect(kpis.locator('[data-kpi="cash.ready"]')).not.toContainText('from ');

  await page.goto('/results/day?scenario=lagging');
  await expect(page.getByTestId('rs-label')).toHaveText('Fri Nov 6, 2026');
  await expect(page.getByTestId('rs-behind')).toHaveText('This is the review for Fri Nov 6. The one for Mon Nov 9 is not in yet; it follows the next numbers run.');
  await expect(page.getByTestId('rs-written')).toContainText('About Fri Nov 6');

  await page.goto('/portfolio?scenario=lagging');
  await expect(page.locator('[data-kpi="plan.drift_max"]')).toContainText('from Fri Nov 6');
  expect(errors).toEqual([]);
});

test('the line warns when the book is behind, and a desk without the endpoint still names its day', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/?scenario=behind');
  await expect(page.getByTestId('asof')).toContainText('Behind');
  await expect(page.getByTestId('asof')).toHaveAttribute('title', /No closing quotes or official closes for Mon Nov 9 yet/);
  expect(errors).toEqual([]);

  await page.route('**/api/asof*', (route) => route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"Not Found"}' }));
  await page.goto('/');
  await expect(page.getByTestId('asof-day')).toHaveText('As of Fri Nov 6');
  await expect(page.getByTestId('asof-change')).toHaveCount(0);
  await expect(page.locator('.ph-kick')).toContainText('Market open');
  await expect(page.getByTestId('bridge-change')).toHaveText('−$86 · −0.52% today');

  await page.goto('/?scenario=never');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Bridge');
  await expect(page.getByTestId('asof')).toHaveCount(0);
});

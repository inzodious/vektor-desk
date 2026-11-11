import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

const fixture = (name) => JSON.parse(readFileSync(fileURLToPath(new URL(`../src/fixtures/${name}.json`, import.meta.url)), 'utf8'));
const JOB_NAMES = /engine-|agents-run|agents-queue|\bmirror\b|decisions-sync/;
const EMPTY_PAGES = [
  ['/', 'bridge.value'],
  ['/results/day', 'results.day'],
  ['/results/year', 'results.year'],
  ['/portfolio', 'portfolio.holdings'],
  ['/portfolio/stocks', 'portfolio.stock_plans'],
  ['/portfolio/risk', 'portfolio.risk'],
  ['/portfolio/tax', 'portfolio.tax'],
  ['/strategies', 'strategies.race'],
  ['/strategies/mixes', 'strategies.mixes'],
  ['/strategies/habits', 'strategies.habits'],
  ['/decisions', 'decisions.queue'],
  ['/research', 'research.feed'],
  ['/research/boards', 'research.boards'],
];

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('a desk that has never run opens on one banner and one button', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/?scenario=never');
  const panel = page.getByTestId('start-panel');
  await expect(panel).toHaveAttribute('data-mode', 'never');
  await expect(panel.getByRole('heading', { name: 'The desk hasn’t run yet' })).toBeVisible();
  await expect(panel.getByTestId('start-desk')).toHaveText(/Start the desk/);
  await expect(panel.locator('.sd-plan li')).toHaveCount(10);
  await expect(panel.locator('.sd-plan li').first()).toHaveText('Pull your accounts');
  await expect(page.getByTestId('health-banner')).toHaveCount(0);
  const empty = page.getByTestId('empty-state');
  await expect(empty).toHaveAttribute('data-key', 'bridge.value');
  await expect(empty).toContainText('The desk hasn’t run yet, so there are no holdings to show.');
  await expect(empty.getByTestId('start-desk')).toBeVisible();
  const chip = page.getByTestId('setup-chip');
  await expect(chip).toHaveAttribute('data-left', '10');
  await expect(chip).toHaveAttribute('href', '/settings/first-run');
  expect(await page.locator('main').innerText()).not.toMatch(JOB_NAMES);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('Start the desk shows each step live, then says the desk is up', async ({ page }) => {
  let posted = 0;
  let polls = 0;
  const running = fixture('start.starting');
  await page.route(/\/api\/start(\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') {
      posted += 1;
      return route.fulfill({ status: 202, json: { ...running, ok: true } });
    }
    if (!posted) return route.fulfill({ json: fixture('start.never') });
    polls += 1;
    return route.fulfill({ json: polls > 2 ? fixture('start') : running });
  });
  await page.goto('/?scenario=never');
  const panel = page.getByTestId('start-panel');
  await panel.getByTestId('start-desk').click();
  await expect(panel).toHaveAttribute('data-mode', 'running');
  await expect(panel.getByRole('heading', { name: 'Starting the desk' })).toBeVisible();
  await expect(panel).toContainText('Step 4 of 10: Fetch market history. You can leave and come back.');
  const steps = panel.getByTestId('start-steps');
  await expect(steps.locator('[data-step="accounts"]')).toHaveAttribute('data-state', 'ok');
  await expect(steps.locator('[data-step="accounts"]')).toContainText('Done · 17 s');
  await expect(steps.locator('[data-step="prices"]')).toContainText('Price history is already complete.');
  await expect(steps.locator('[data-step="market"]')).toHaveAttribute('data-state', 'running');
  await expect(steps.locator('[data-step="paper"]')).toHaveAttribute('data-state', 'waiting');
  await expect(panel.getByTestId('start-desk')).toHaveCount(0);
  await expect(page.getByTestId('empty-filling')).toBeVisible();
  await expect(panel).toHaveAttribute('data-mode', 'ok', { timeout: 20000 });
  await expect(panel.getByRole('heading', { name: 'The desk is up' })).toBeVisible();
  await panel.getByRole('button', { name: 'Got it' }).click();
  await expect(panel).toHaveCount(0);
  expect(posted).toBe(1);
});

test('a refused start says why', async ({ page }) => {
  await page.route(/\/api\/start(\?.*)?$/, async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ status: 503, json: { ok: false, error: 'scheduler_down', message: 'The scheduler is off, so nothing would run. Settings, Box can restart it.' } });
    return route.fulfill({ json: fixture('start.never') });
  });
  await page.goto('/?scenario=never');
  await page.getByTestId('start-panel').getByTestId('start-desk').click();
  await expect(page.getByTestId('start-error')).toHaveText('The scheduler is off, so nothing would run. Settings, Box can restart it.');
  await expect(page.getByTestId('start-panel')).toHaveAttribute('data-mode', 'never');
});

test('other pages carry a slim strip while the desk has not run', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/portfolio?scenario=never');
  const strip = page.getByTestId('start-strip');
  await expect(strip).toHaveAttribute('data-mode', 'never');
  await expect(strip).toContainText('The desk hasn’t run yet.');
  await expect(strip.getByTestId('start-desk')).toBeVisible();
  await expect(page.getByTestId('start-panel')).toHaveCount(0);
  await expect(page.locator('.kpis')).toHaveCount(0);
  await expect(page.getByTestId('empty-state')).toHaveAttribute('data-key', 'portfolio.holdings');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('while the desk starts, the strip shows the step and empties wait for it', async ({ page }) => {
  await page.goto('/results/day?scenario=starting');
  const strip = page.getByTestId('start-strip');
  await expect(strip).toHaveAttribute('data-mode', 'running');
  await expect(strip).toContainText('Step 4 of 10: Fetch market history');
  await expect(strip.getByTestId('start-desk')).toHaveCount(0);
  await expect(strip.getByTestId('start-watch')).toHaveAttribute('href', '/settings/first-run');
  const empty = page.getByTestId('empty-state');
  await expect(empty).toHaveAttribute('data-key', 'results.day');
  await expect(empty.getByTestId('empty-filling')).toContainText('The desk is starting');
  await expect(empty.getByTestId('empty-act')).toHaveCount(0);
});

test('a run with loose ends lists only the steps that need him, each with its fix', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/?scenario=loose');
  const panel = page.getByTestId('start-panel');
  await expect(panel).toHaveAttribute('data-mode', 'partial');
  await expect(panel).toContainText('7 of 10 steps done. 3 need you.');
  await expect(panel.getByTestId('start-desk')).toHaveText(/Start again/);
  const steps = panel.locator('.sd-step');
  await expect(steps).toHaveCount(3);
  await expect(panel.locator('[data-step="discounts"]')).toContainText('It stopped with an error.');
  await expect(panel.locator('[data-step="discounts"]').getByTestId('start-fix')).toHaveAttribute('href', '/settings/box');
  await expect(panel.locator('[data-step="debrief"]').getByTestId('start-fix')).toHaveText(/Switch it on/);
  await expect(panel.locator('[data-step="debrief"]').getByTestId('start-fix')).toHaveAttribute('href', '/settings/crew');
  await expect(page.locator('.kpis')).toHaveCount(1);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
  await panel.getByTestId('start-hide').click();
  await expect(panel).toHaveCount(0);
  await page.goto('/portfolio?scenario=loose');
  await expect(page.locator('.kpis').first()).toBeVisible();
  await expect(page.getByTestId('start-strip')).toHaveCount(0);
  await page.goto('/settings/first-run?scenario=loose');
  await expect(page.getByTestId('start-panel')).toHaveAttribute('data-mode', 'partial');
  await expect(page.getByTestId('start-panel').locator('.sd-step')).toHaveCount(10);
});

test('a section with data that is stale or blocked gets a one-line note and its one button', async ({ page }) => {
  await page.goto('/strategies/mixes?scenario=loose');
  const note = page.getByTestId('empty-state');
  await expect(note).toHaveAttribute('data-key', 'strategies.mixes');
  await expect(note).toHaveAttribute('data-state', 'stale');
  await expect(note).toContainText('Market history is from October');
  await expect(note).toContainText('Fills by itself Dec 2 at 3:30 AM.');
  await expect(note.getByTestId('empty-act')).toHaveText(/Fetch it now/);
  await expect(page.getByTestId('mixes')).toBeVisible();
  await page.goto('/portfolio/stocks?scenario=loose');
  const blocked = page.getByTestId('empty-state');
  await expect(blocked).toHaveAttribute('data-state', 'blocked');
  await expect(blocked.getByTestId('empty-act')).toHaveAttribute('href', '/settings/box');
  await expect(page.getByTestId('plan-card').first()).toBeVisible();
});

test('an empty section runs its job in place and fills in', async ({ page }) => {
  let asked = null;
  let polls = 0;
  let readiness = 0;
  await page.route('**/api/jobs/*/run', (route) => {
    asked = route.request().url().split('/').slice(-2)[0];
    route.fulfill({ status: 202, json: { ok: true, job: asked, request_id: 'req-review' } });
  });
  await page.route(/\/api\/jobs(\?.*)?$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    polls += 1;
    if (asked && polls > 3) body.jobs = body.jobs.map((j) => (j.name === asked ? { ...j, last_run: { request_id: 'req-review', result: 'ok', started: '2026-11-11T14:10:00Z', finished: '2026-11-11T14:10:09Z' } } : j));
    route.fulfill({ json: body });
  });
  await page.route(/\/api\/readiness(\?.*)?$/, async (route) => {
    readiness += 1;
    route.fulfill({ json: asked && polls > 3 ? fixture('readiness') : fixture('readiness.gaps') });
  });
  await page.goto('/results/week?scenario=gaps');
  await expect(page.getByTestId('start-strip')).toHaveCount(0);
  const empty = page.getByTestId('empty-state');
  await expect(empty).toHaveAttribute('data-key', 'results.week');
  await expect(empty).toContainText('No results yet: the review hasn’t run.');
  await expect(empty).toContainText('Fills by itself today at 5:35 PM.');
  const before = readiness;
  await empty.getByTestId('empty-act').click();
  await expect(empty.getByTestId('empty-working')).toBeVisible();
  await expect.poll(() => readiness, { timeout: 20000 }).toBeGreaterThan(before);
  expect(asked).toBe('engine-review');
});

test('a job that fails in place says so and keeps the button', async ({ page }) => {
  let asked = null;
  await page.route('**/api/jobs/*/run', (route) => {
    asked = route.request().url().split('/').slice(-2)[0];
    route.fulfill({ status: 202, json: { ok: true, job: asked, request_id: 'req-bad' } });
  });
  await page.route(/\/api\/jobs(\?.*)?$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    if (asked) body.jobs = body.jobs.map((j) => (j.name === asked ? { ...j, last_run: { request_id: 'req-bad', result: 'failed', detail: 'no prices for the period', started: '2026-11-11T14:10:00Z', finished: '2026-11-11T14:10:02Z' } } : j));
    route.fulfill({ json: body });
  });
  await page.goto('/portfolio/risk?scenario=gaps');
  const empty = page.getByTestId('empty-state');
  await expect(empty).toHaveAttribute('data-key', 'portfolio.risk');
  await empty.getByTestId('empty-act').click();
  await expect(empty.getByTestId('empty-msg')).toContainText('That didn’t finish: no prices for the period', { timeout: 15000 });
  await expect(empty.getByTestId('empty-act')).toBeVisible();
  expect(asked).toBe('engine-backfill');
});

for (const [path, key] of EMPTY_PAGES) {
  test(`${path} says why it is empty and offers one way to fill it`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto(`${path}?scenario=never`);
    const empty = page.locator(`[data-testid="empty-state"][data-key="${key}"]`);
    await expect(empty).toBeVisible();
    await expect(empty.locator('.es-text p')).not.toBeEmpty();
    await expect(empty.locator('.es-act').locator('a, button')).toHaveCount(1);
    expect(await empty.innerText()).not.toMatch(JOB_NAMES);
    const o = await overflow(page);
    expect(o.scroll).toBeLessThanOrEqual(o.view);
    expect(errors).toEqual([]);
  });
}

test('the top bar counts setup steps left and opens the checklist', async ({ page }) => {
  await page.goto('/');
  const chip = page.getByTestId('setup-chip');
  await expect(chip).toHaveAttribute('data-left', '2');
  await expect(chip).toHaveAccessibleName('Setup: 2 of 10 steps left. Open the first-run checklist.');
  await expect(page.getByTestId('start-panel')).toHaveCount(0);
  await chip.click();
  await expect(page).toHaveURL(/\/settings\/first-run$/);
  await expect(page.getByRole('heading', { level: 1, name: 'First run' })).toBeVisible();
});

test('First run leads with Start the desk and keeps the checklist under it', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/first-run?scenario=never');
  const panel = page.getByTestId('start-panel');
  await expect(panel).toHaveAttribute('data-mode', 'never');
  await expect(panel.getByTestId('start-desk')).toBeVisible();
  await expect(page.getByTestId('start-strip')).toHaveCount(0);
  await expect(page.getByTestId('first-run')).toHaveAttribute('data-done', '0');
  const box = await panel.boundingBox();
  const list = await page.getByTestId('first-run').boundingBox();
  expect(box.y).toBeLessThan(list.y);
  await page.goto('/settings/first-run');
  await expect(panel).toHaveAttribute('data-mode', 'ok');
  await expect(panel.getByTestId('start-desk')).toHaveText(/Run it all again/);
  await expect(panel.getByTestId('start-steps').locator('.sd-step')).toHaveCount(10);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a desk without the start and readiness answers looks as it did', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route(/\/api\/(start|readiness)(\?.*)?$/, (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/results/day?scenario=fresh');
  await expect(page.getByTestId('start-strip')).toHaveCount(0);
  const empty = page.getByTestId('empty-state');
  await expect(empty).toHaveAttribute('data-state', 'unknown');
  await expect(empty.getByTestId('empty-act')).toHaveText(/Write it now/);
  await page.goto('/');
  await expect(page.getByTestId('start-panel')).toHaveCount(0);
  await expect(page.locator('.kpis').first()).toBeVisible();
  expect(errors).toEqual([]);
});

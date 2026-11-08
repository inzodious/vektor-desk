import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('the first-run checklist ticks off what is done and points at the next step', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings');
  await page.getByTestId('first-run-link').click();
  await expect(page).toHaveURL(/\/settings\/first-run$/);
  const fr = page.getByTestId('first-run');
  await expect(fr).toHaveAttribute('data-done', '7');
  await expect(page.getByText('T-minus 2 steps')).toBeVisible();
  await expect(page.getByText('Next: Bring in your tax lots')).toBeVisible();
  await expect(fr.locator('[data-step="lots"]')).toHaveAttribute('data-state', 'todo');
  await expect(fr.locator('[data-step="risk"]')).toContainText('Coming soon');
  await expect(fr.locator('[data-step="crew"]').getByRole('link', { name: /Open Desks/ })).toHaveAttribute('href', '/settings');
  await expect(fr.locator('code')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a step runs its job from the page', async ({ page }) => {
  let asked = null;
  let polls = 0;
  await page.route('**/api/jobs/*/run', (route) => {
    asked = route.request().url().split('/').slice(-2)[0];
    route.fulfill({ status: 202, json: { ok: true, job: asked, request_id: 'req-research' } });
  });
  await page.route(/\/api\/jobs(\?.*)?$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    polls += 1;
    if (asked && polls > 2) body.jobs = body.jobs.map((j) => (j.name === asked ? { ...j, last_run: { ...j.last_run, request_id: 'req-research', result: 'ok', finished: '2026-11-09T16:43:00Z' } } : j));
    route.fulfill({ json: body });
  });
  await page.goto('/start');
  const step = page.getByTestId('first-run').locator('[data-step="research"]');
  await step.getByRole('button', { name: 'Run again' }).click();
  await expect(step).toContainText('Research done.', { timeout: 15000 });
  expect(asked).toBe('engine-research');
});

test('a fresh desk starts at step one', async ({ page }) => {
  await page.goto('/start?scenario=fresh');
  const fr = page.getByTestId('first-run');
  await expect(fr.locator('[data-step="profile"]')).toHaveAttribute('data-state', 'todo');
  await expect(fr.locator('[data-step="race"]')).toHaveAttribute('data-state', 'todo');
});

test('a fresh desk writes its profile with one button', async ({ page }) => {
  let posted = false;
  await page.route('**/api/decisions/profile/init', (route) => {
    posted = route.request().method() === 'POST';
    route.fulfill({ json: { changed: true, path: '/data/desk.yaml', message: 'Wrote /data/desk.yaml from your data.', status: {} } });
  });
  await page.goto('/start?scenario=fresh');
  const step = page.getByTestId('first-run').locator('[data-step="profile"]');
  await step.getByRole('button', { name: 'Write it now' }).click();
  await expect(step).toContainText('Wrote /data/desk.yaml from your data.');
  expect(posted).toBe(true);
});

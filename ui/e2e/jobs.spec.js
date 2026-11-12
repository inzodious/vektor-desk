import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

const JOBS = JSON.parse(readFileSync(new URL('../src/fixtures/jobs.json', import.meta.url), 'utf8'));

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

function fakeScheduler(page, { fail = [] } = {}) {
  const state = structuredClone(JOBS);
  const asked = [];
  const ticks = {};
  const job = (name) => state.jobs.find((j) => j.name === name);
  page.route('**/api/jobs/*/run', (route) => {
    const name = route.request().url().split('/').slice(-2)[0];
    asked.push(name);
    const j = job(name);
    Object.assign(j, { queued: true, can_run: false });
    ticks[name] = 0;
    route.fulfill({ status: 202, json: { ok: true, job: name, request_id: `req-${name}`, requested_at: '2026-11-09T16:42:00Z', message: 'Starts within a few seconds.' } });
  });
  page.route('**/api/jobs?*', (route) => route.fallback());
  page.route(/\/api\/jobs(\?.*)?$/, (route) => {
    for (const name of Object.keys(ticks)) {
      const j = job(name);
      ticks[name] += 1;
      if (ticks[name] === 1) Object.assign(j, { queued: false, running: true, running_since: '2026-11-09T16:42:05Z' });
      if (ticks[name] === 2) {
        const failed = fail.includes(name);
        Object.assign(j, {
          running: false,
          running_since: null,
          can_run: true,
          last_run: { trigger: 'request', request_id: `req-${name}`, started: '2026-11-09T16:42:05Z', finished: '2026-11-09T16:43:00Z', result: failed ? 'failed' : 'ok', exit_code: failed ? 1 : 0, detail: failed ? 'Firestore said no.' : null },
        });
        delete ticks[name];
      }
    }
    route.fulfill({ json: state });
  });
  return asked;
}

// ---------- settings ----------
test('jobs list plain names, how each last went and when it runs', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/box');
  const card = page.getByTestId('jobs');
  await expect(card).toHaveAttribute('data-alive', 'true');
  await expect(card.locator('.job-list').first().locator('.job-row')).toHaveCount(9);
  await expect(card.locator('[data-job="engine-quotes"]')).toContainText('Prices');
  await expect(card.locator('[data-job="engine-quotes"]')).toContainText('Every 5 min, 4 AM to 8 PM on weekdays');
  await expect(card.locator('[data-job="engine-daily"]')).toContainText('8:20 AM and 5:20 PM');
  await expect(card.locator('[data-job="engine-lookthrough"]')).toContainText('Fund breakdowns');
  await expect(card.locator('[data-job="engine-research"]')).toHaveAttribute('data-state', 'failed');
  await expect(card.locator('[data-job="engine-research"]')).toContainText('Didn’t finish');
  await expect(card.locator('[data-job="mirror"] button')).toBeDisabled();
  await expect(card.locator('[data-job="mirror"] button')).toContainText('Again at');
  await card.getByText(/Agents and housekeeping/).click();
  await expect(card.locator('[data-job="agents-run-tax"]')).toContainText('Tax desk');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a finished job shows what the run did, and never raw output', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/box');
  const card = page.getByTestId('jobs');
  const backfill = card.locator('[data-job="engine-backfill"]');
  await expect(backfill.getByTestId('job-did')).toHaveText('Asked Tiingo for 2 names. FXAIX and FTEC answered with nothing new for 2026-11-06.');
  await expect(card.getByTestId('job-did')).toHaveCount(1);
  await card.getByText(/Agents and housekeeping/).click();
  const paper = card.locator('[data-job="engine-paper"]');
  await expect(paper).toContainText('Ran ');
  await expect(paper.getByTestId('job-did')).toHaveCount(0);
  await expect(card).not.toContainText('{');
  await expect(card).not.toContainText('filled');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a waiting job gives the reason the desk names, and none when it names none', async ({ page }) => {
  const state = structuredClone(JOBS);
  const set = (name, more) => Object.assign(state.jobs.find((j) => j.name === name), { waiting: true, waiting_since: null, can_run: false }, more);
  set('engine-research', { waiting_for: 'night' });
  set('engine-lookthrough', { waiting_for: 'memory' });
  set('engine-french', { waiting_for: null });
  await page.route(/\/api\/jobs(\?.*)?$/, (route) => route.fulfill({ json: state }));
  await page.goto('/settings/box');
  const card = page.getByTestId('jobs');
  await expect(card.locator('[data-job="engine-research"]')).toContainText('Waiting for its turn: the overnight run goes one step at a time');
  await expect(card.locator('[data-job="engine-lookthrough"]')).toContainText('Waiting for its turn: low-memory mode runs heavy jobs one at a time');
  await expect(card.locator('[data-job="engine-french"] small').first()).toHaveText('Waiting for its turn');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

test('run now shows starting, running, then done', async ({ page }) => {
  const asked = fakeScheduler(page);
  await page.goto('/settings/box');
  const row = page.getByTestId('jobs').locator('[data-job="engine-daily"]');
  await row.getByRole('button', { name: 'Run Daily numbers now' }).click();
  await expect(row).toHaveAttribute('data-state', 'running');
  await expect(row.locator('.chip')).toBeVisible();
  await expect(row).toContainText('Daily numbers done.', { timeout: 15000 });
  await expect(row).toHaveAttribute('data-state', 'ok');
  expect(asked).toEqual(['engine-daily']);
});

test('a failed run says so kindly', async ({ page }) => {
  fakeScheduler(page, { fail: ['engine-backfill'] });
  await page.goto('/settings/box');
  const row = page.getByTestId('jobs').locator('[data-job="engine-backfill"]');
  await row.getByRole('button', { name: /Run Backfill now/ }).click();
  await expect(row).toContainText('Backfill didn’t finish: Firestore said no.', { timeout: 15000 });
  await expect(row).toHaveAttribute('data-state', 'failed');
});

test('a refusal shows the reason on the row', async ({ page }) => {
  await page.route('**/api/jobs/*/run', (route) => route.fulfill({ status: 503, json: { ok: false, error: 'scheduler_down', message: 'The cron service isn’t running.' } }));
  await page.goto('/settings/box');
  const row = page.getByTestId('jobs').locator('[data-job="engine-lots"]');
  await row.getByRole('button', { name: /Run Lots now/ }).click();
  await expect(row.locator('.job-note')).toContainText('taking a break');
});

test('with the scheduler off, run now is off and says why', async ({ page }) => {
  await page.goto('/settings/box?scenario=down');
  const card = page.getByTestId('jobs');
  await expect(card.getByTestId('scheduler-off')).toBeVisible();
  await expect(card.getByText('Scheduler off')).toBeVisible();
  await expect(card.locator('.job-list').first().getByRole('button', { disabled: false })).toHaveCount(0);
});

// ---------- the box refreshes by itself ----------
test('the app asks for no job on its own: the box does that', async ({ page }) => {
  const asked = fakeScheduler(page);
  for (const path of ['/?scenario=fail', '/research?scenario=warn', '/portfolio?scenario=healing']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.waitForLoadState('networkidle');
  }
  await expect(page.getByRole('button', { name: 'Refresh data' })).toHaveCount(0);
  expect(asked).toEqual([]);
});

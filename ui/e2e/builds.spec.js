import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

const load = (name) => JSON.parse(readFileSync(new URL(`../src/fixtures/${name}.json`, import.meta.url), 'utf8'));
const PRINT = `3d63e0705ff21e2b${'0123456789abcdef'.repeat(3)}`;
const START = 'DESK_BUILD=$(git rev-parse HEAD) docker compose -f deploy/worker/compose.yaml --profile builder up -d --build';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

function fakeBox(page, name, change = (s) => s) {
  const state = change(structuredClone(load(name)));
  const online = load('box.horizon').build;
  const asked = [];
  let ticks = null;
  const row = () => state.actions.find((a) => a.name === 'approve-builder');
  page.route('**/api/box/*/run', (route) => {
    asked.push(route.request().url().split('/').slice(-2)[0]);
    Object.assign(row(), { queued: true, queued_at: '2026-11-09T16:42:00Z', can_run: false });
    ticks = 0;
    route.fulfill({ status: 202, json: { ok: true, action: 'approve-builder', request_id: 'req-approve', requested_at: '2026-11-09T16:42:00Z', message: 'Starts within 5 minutes.' } });
  });
  page.route(/\/api\/box(\?.*)?$/, (route) => {
    if (ticks !== null) {
      ticks += 1;
      if (ticks === 2) Object.assign(row(), { queued: false, queued_at: null, running: true, last_run: { action: 'approve-builder', request_id: 'req-approve', started: '2026-11-09T16:42:10Z', finished: null, result: null, exit_code: null, output: null } });
      if (ticks === 3) {
        Object.assign(row(), { running: false, cooldown_until: '2026-11-09T16:43:10Z', last_run: { action: 'approve-builder', request_id: 'req-approve', started: '2026-11-09T16:42:10Z', finished: '2026-11-09T16:42:12Z', result: 'ok', exit_code: 0, output: 'Approved Horizon (3d63e0705ff2). The box now takes images it signs, for the commit auto-deploy is waiting on\n1 approved' } });
        state.build = online;
        ticks = null;
      }
    }
    route.fulfill({ json: state });
  });
  return asked;
}

// ---------- who builds ----------
test('the box says it builds its own images and how a worker can take over', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  const errors = watchErrors(page);
  await page.goto('/settings/box?scenario=current');
  const b = page.getByTestId('box-build');
  await expect(b).toHaveAttribute('data-state', 'none');
  await expect(b.getByTestId('build-head')).toHaveText('The box builds its own images, one stage at a time.');
  await expect(b).toContainText('The last image (716e203) came from this box.');
  await expect(b.locator('[data-box="approve-builder"]')).toHaveCount(0);
  await expect(page.getByTestId('box').locator('.job-list [data-box="approve-builder"]')).toHaveCount(0);
  await b.getByText('Let a worker build them').click();
  await expect(b.getByTestId('build-start').locator('pre')).toContainText(START);
  await b.getByTestId('build-start-copy').click();
  await expect(b.getByTestId('build-start-copy')).toHaveText('Copied');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`git pull --ff-only\n${START}`);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('the box panel says a new version waits for main to go quiet', async ({ page }) => {
  await page.goto('/settings/box');
  await expect(page.getByTestId('box-settle')).toHaveText('A new version goes in by itself once main has been quiet for 10 minutes; Deploy now skips the wait.');
  await expect(page.getByTestId('box').locator('.job-list [data-box="deploy-now"]')).toContainText('Deploy now');
});

test('a machine that asks to build gets its line for main, ready to copy', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/settings/box?scenario=asking');
  const b = page.getByTestId('box-build');
  await expect(b).toHaveAttribute('data-state', 'asking');
  await expect(b.getByTestId('build-head')).toHaveText("Horizon asks to build the desk's images (key 3d63 e070 5ff2 1e2b).");
  await expect(b.getByTestId('build-ask')).toContainText('Horizon’s line for main:');
  await expect(b.getByTestId('build-ask').locator('code')).toHaveText(`${PRINT} Horizon`);
  await b.getByTestId('build-ask-copy').click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(`${PRINT} Horizon`);
  await expect(b.locator('[data-box="approve-builder"]')).toHaveCount(0);
  await expect(b.getByTestId('build-start')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

test('Approve builder shows once main lists the builder, and runs like any box chore', async ({ page }) => {
  const asked = fakeBox(page, 'box.approve');
  await page.goto('/settings/box');
  const b = page.getByTestId('box-build');
  await expect(b).toHaveAttribute('data-state', 'approve');
  await expect(b.getByTestId('build-head')).toHaveText('Horizon is listed in main and has sent its key.');
  await expect(b.getByTestId('build-ask')).toHaveCount(0);
  const row = b.locator('[data-box="approve-builder"]');
  await row.getByRole('button', { name: 'Approve builder now' }).click();
  await expect(row).toContainText('Queued, runs within 5 min');
  await expect(row).toContainText('Approve builder done.', { timeout: 15000 });
  await expect(b).toHaveAttribute('data-state', 'online');
  await expect(b.getByTestId('build-head')).toHaveText("Horizon builds the desk's images, so the box doesn't have to.");
  await row.getByText('Last output').click();
  await expect(row.locator('pre')).toContainText('Approved Horizon (3d63e0705ff2)');
  expect(asked).toEqual(['approve-builder']);
});

test('an approved builder needs no button, awake or asleep', async ({ page }) => {
  await page.goto('/settings/box?scenario=horizon');
  const b = page.getByTestId('box-build');
  await expect(b).toHaveAttribute('data-state', 'online');
  await expect(b).toContainText('The last image (716e203) came from a builder.');
  await expect(b.locator('[data-box="approve-builder"]')).toHaveCount(0);
  await page.goto('/settings/box?scenario=asleep');
  await expect(b).toHaveAttribute('data-state', 'asleep');
  await expect(b.getByTestId('build-head')).toHaveText('Horizon is approved to build but is asleep or off (last heard 3 hours ago).');
  await expect(b).toContainText('The box builds here meanwhile.');
  await expect(b.locator('[data-box="approve-builder"]')).toHaveCount(0);
});

test('a builder that main no longer lists brings the button back', async ({ page }) => {
  fakeBox(page, 'box.horizon', (s) => ({ ...s, build: { ...s.build, listed: [] } }));
  await page.goto('/settings/box');
  const b = page.getByTestId('box-build');
  await expect(b.getByTestId('build-stale')).toHaveText('Horizon is no longer listed in main. Approve builder stops the box taking its images.');
  await expect(b.getByRole('button', { name: 'Approve builder now' })).toBeEnabled();
});

test('a machine can ask before the box has its new script', async ({ page }) => {
  fakeBox(page, 'box.asking', (s) => ({ ...s, build: { ...s.build, host_seen: false, settle_seconds: null } }));
  await page.goto('/settings/box');
  await expect(page.getByTestId('build-script')).toHaveText('The box needs its new script before it can list or approve a builder. Update box script comes first.');
  await expect(page.getByTestId('box-settle')).toHaveCount(0);
});

test('a desk without builds shows the box panel as before', async ({ page }) => {
  fakeBox(page, 'box', (s) => {
    const { build: _build, ...rest } = s;
    return { ...rest, actions: rest.actions.filter((a) => a.name !== 'approve-builder') };
  });
  await page.goto('/settings/box');
  await expect(page.getByTestId('box').locator('.job-list .box-row').first()).toBeVisible();
  await expect(page.getByTestId('box-build')).toHaveCount(0);
  await expect(page.getByTestId('box-settle')).toHaveCount(0);
});

test('a box that has not checked in says nothing about builds', async ({ page }) => {
  await page.goto('/settings/box?scenario=down');
  await expect(page.getByTestId('box')).toHaveAttribute('data-alive', 'false');
  await expect(page.getByTestId('box-build')).toHaveCount(0);
});

// ---------- the job that feeds the worker ----------
test('the every-minute lab job sits folded away with its schedule in plain words', async ({ page }) => {
  await page.goto('/settings/box');
  const card = page.getByTestId('jobs');
  await expect(card.locator('.job-list').first().locator('[data-job="engine-lab-offer"]')).toHaveCount(0);
  await card.getByText(/Agents and housekeeping/).click();
  const row = card.locator('[data-job="engine-lab-offer"]');
  await expect(row).toContainText('Lab work to the worker');
  await expect(row).toContainText('Every minute, 1 AM to 6 AM');
});

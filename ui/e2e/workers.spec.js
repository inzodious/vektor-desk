import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

const read = (name) => JSON.parse(readFileSync(new URL(`../src/fixtures/${name}.json`, import.meta.url), 'utf8'));
const NONE = read('workers');
const JOINED = read('workers.joined');
const ONLINE = read('workers.horizon');
const KEY = 'dwk_example_not_a_real_key';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

function fakeWorkers(page, start = NONE) {
  let block = structuredClone(start);
  const asked = [];
  page.route('**/api/worker/check', (route) => {
    asked.push('check');
    block = { ...block, summary: { ...block.summary, waiting: block.summary.waiting + 1 }, jobs: [{ id: 'feedfacecafe', kind: 'worker.check', title: 'Check a database copy on the worker', state: 'queued', queued_at: '2026-11-09T16:42:00Z', leased_at: null, finished_at: null, attempts: 0, seconds: null, peak_mb: null, where: 'queue', why: 'Next in line for Horizon.' }, ...block.jobs] };
    route.fulfill({ status: 202, json: { ok: true, job: 'feedfacecafe', ...block } });
  });
  page.route(/\/api\/workers\/[0-9a-f]+$/, (route) => {
    asked.push(`${route.request().method()} ${route.request().url().split('/').pop()}`);
    block = structuredClone(NONE);
    route.fulfill({ json: { ok: true, ...block } });
  });
  page.route(/\/api\/workers(\?.*)?$/, (route) => {
    if (route.request().method() !== 'POST') return route.fulfill({ json: block });
    const name = route.request().postDataJSON()?.name;
    asked.push(`POST ${name}`);
    if (name === 'Fifth') return route.fulfill({ status: 409, json: { ok: false, error: 'too_many', message: 'Four workers is the most. Remove one first.' } });
    block = structuredClone(JOINED);
    return route.fulfill({ status: 201, json: { ok: true, message: 'Copy the key now. It isn’t shown again.', key: KEY, id: 'a1b2c3d4e5f6', name, added_at: '2026-11-09T16:42:00Z', desk_url: 'https://desk-lan.example.test', ...block } });
  });
  return asked;
}

// ---------- the panel ----------
test('with no worker the panel says so and offers to add one', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/box');
  const card = page.getByTestId('workers');
  await expect(card).toHaveAttribute('data-state', 'none');
  await expect(card.getByTestId('workers-chip')).toHaveText('No worker yet');
  await expect(card.getByTestId('workers-lead')).toContainText('No worker has joined. Everything runs on this box.');
  await expect(card.getByTestId('worker-add')).toBeEnabled();
  await expect(card.getByTestId('worker-test')).toHaveCount(0);
  await expect(card.getByTestId('worker-jobs')).toHaveCount(0);
  await expect(page.getByTestId('worker-chip')).toHaveCount(0);
  await expect(page.getByTestId('worker-dot')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('an online worker shows what it is doing and where each job is', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/box?scenario=horizon');
  const card = page.getByTestId('workers');
  await expect(card).toHaveAttribute('data-state', 'online');
  await expect(card.getByTestId('workers-chip')).toHaveText('Online');
  await expect(card.getByTestId('workers-waiting')).toHaveText('1 waiting');
  await expect(card.getByTestId('workers-lead')).toHaveText(/Horizon is online, working on: Lab simulations\./);
  await expect(card.locator('[data-worker]')).toHaveCount(1);
  await expect(card.locator('[data-worker]')).toContainText('Added 8:10 AM · on horizon · build a02ded6');
  const jobs = card.getByTestId('worker-jobs');
  await expect(jobs.locator('[data-wjob="9f8e7d6c5b4a"]')).toContainText('Running on Horizon, started 3 minutes ago.');
  await expect(jobs.locator('[data-wjob="9f8e7d6c5b4a"] .chip')).toHaveText('On the worker');
  await expect(jobs.locator('[data-wjob="8e7d6c5b4a39"] .chip')).toHaveText('Waiting');
  await expect(jobs.locator('[data-wjob="7d6c5b4a3928"] .chip')).toHaveText('Being checked');
  await jobs.getByText(/Earlier \(2\)/).click();
  await expect(jobs.locator('[data-wjob="2c3d4e5f6071"]')).toContainText('the worker ran out of memory and stopped it');
  await expect(card).not.toContainText(/lab\.sims|worker\.check/);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a sleeping worker says when it was last heard and what waits for it', async ({ page }) => {
  await page.goto('/settings/box?scenario=asleep#workers');
  const card = page.getByTestId('workers');
  await expect(card).toBeInViewport();
  await expect(card).toHaveAttribute('data-state', 'asleep');
  await expect(card.getByTestId('workers-lead')).toHaveText(/Horizon is asleep or off: last heard 3 hours ago\. 2 jobs waiting\./);
  await expect(card.locator('[data-wjob="9f8e7d6c5b4a"] .chip')).toHaveText('Back in line');
  await expect(card.locator('[data-wjob="8e7d6c5b4a39"]')).toContainText('Waiting for Horizon, which is asleep or off (last heard 3 hours ago).');
});

test('an older desk without workers shows no panel and no chip', async ({ page }) => {
  await page.route(/\/api\/workers(\?.*)?$/, (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/settings/box');
  await expect(page.getByTestId('jobs')).toBeVisible();
  await expect(page.getByTestId('workers')).toHaveCount(0);
  await expect(page.getByTestId('worker-dot')).toHaveCount(0);
});

// ---------- add, test, remove ----------
test('adding a worker shows its key once with the commands to start it', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  const asked = fakeWorkers(page);
  await page.goto('/settings/box');
  const card = page.getByTestId('workers');
  await card.getByTestId('worker-add').click();
  await expect(card.getByTestId('worker-name')).toHaveValue('Horizon');
  await expect(card.getByTestId('worker-name')).toBeFocused();
  await card.getByRole('button', { name: 'Make its key' }).click();
  const key = card.getByTestId('worker-key');
  await expect(key).toContainText('Horizon has a key. Copy it now; it isn’t shown again.');
  await expect(key.getByTestId('worker-key-value')).toHaveText(KEY);
  await expect(key.getByTestId('worker-cmd')).toContainText(`DESK_URL=https://desk-lan.example.test DESK_WORKER_KEY=${KEY} docker compose -f deploy/worker/compose.yaml up -d --build`);
  await key.getByTestId('worker-cmd-copy').click();
  await expect(key.getByTestId('worker-cmd-copy')).toHaveText('Copied');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(`DESK_WORKER_KEY=${KEY}`);
  await expect(card).toHaveAttribute('data-state', 'never');
  await expect(card.locator('[data-worker="a1b2c3d4e5f6"] .chip')).toHaveText('Not seen yet');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await key.getByTestId('worker-key-done').click();
  await expect(card.getByTestId('worker-key')).toHaveCount(0);
  await expect(card).not.toContainText(KEY);
  expect(asked).toEqual(['POST Horizon']);
});

test('a bad name is caught before the desk is asked, and a refusal is shown as given', async ({ page }) => {
  const asked = fakeWorkers(page, JOINED);
  await page.goto('/settings/box');
  const card = page.getByTestId('workers');
  await card.getByTestId('worker-add').click();
  await expect(card.getByTestId('worker-name')).toHaveValue('');
  await card.getByRole('button', { name: 'Make its key' }).click();
  await expect(card.getByTestId('worker-form-error')).toHaveText('Give it a name, like Horizon.');
  await card.getByTestId('worker-name').fill('horizon');
  await card.getByRole('button', { name: 'Make its key' }).click();
  await expect(card.getByTestId('worker-form-error')).toHaveText('A worker already has that name.');
  await card.getByTestId('worker-name').fill('Fifth');
  await card.getByRole('button', { name: 'Make its key' }).click();
  await expect(card.getByTestId('worker-form-error')).toHaveText('Four workers is the most. Remove one first.');
  await card.getByRole('button', { name: 'Cancel' }).click();
  await expect(card.getByTestId('worker-form')).toHaveCount(0);
  expect(asked).toEqual(['POST Fifth']);
});

test('Test the worker queues a small job that shows in the list', async ({ page }) => {
  const asked = fakeWorkers(page, ONLINE);
  await page.goto('/settings/box');
  const card = page.getByTestId('workers');
  await card.getByTestId('worker-test').click();
  await expect(card.getByTestId('workers-note')).toContainText('A small test job is in line below');
  await expect(card.locator('[data-wjob="feedfacecafe"]')).toContainText('Next in line for Horizon.');
  expect(asked).toEqual(['check']);
});

test('a test with nothing to send says why', async ({ page }) => {
  fakeWorkers(page, JOINED);
  await page.route('**/api/worker/check', (route) => route.fulfill({ status: 409, json: { ok: false, error: 'no_data', message: 'There is no database to send yet.' } }));
  await page.goto('/settings/box');
  await page.getByTestId('worker-test').click();
  await expect(page.getByTestId('workers-note')).toHaveText('There is no database to send yet.');
});

test('removing a worker asks once and then drops it', async ({ page }) => {
  const asked = fakeWorkers(page, JOINED);
  await page.goto('/settings/box');
  const card = page.getByTestId('workers');
  await card.getByTestId('worker-remove').click();
  await expect(card.locator('[data-worker]')).toContainText('Remove Horizon? Its key stops working at once.');
  await card.getByRole('button', { name: 'Keep' }).click();
  await expect(card.locator('[data-worker]')).not.toContainText('Its key stops working');
  await card.getByTestId('worker-remove').click();
  await card.getByTestId('worker-remove-yes').click();
  await expect(card.getByTestId('workers-note')).toHaveText('Horizon is removed. Its key no longer works.');
  await expect(card).toHaveAttribute('data-state', 'none');
  await expect(card.locator('[data-worker]')).toHaveCount(0);
  expect(asked).toEqual(['DELETE a1b2c3d4e5f6']);
});

// ---------- top bar and Bridge ----------
test('the gear carries a mark for the worker that opens the panel', async ({ page }) => {
  await page.goto('/?scenario=asleep');
  const dot = page.getByTestId('worker-dot');
  await expect(dot).toHaveAttribute('data-state', 'asleep');
  await expect(dot).toHaveText('2');
  await expect(dot).toHaveAttribute('aria-label', 'Horizon is asleep or off: last heard 3 hours ago. 2 jobs waiting.');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await dot.click();
  await expect(page).toHaveURL(/\/settings\/box#workers$/);
});

test('on a wide screen the worker has its own chip', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1000 });
  await page.goto('/?scenario=horizon');
  const chip = page.getByTestId('worker-chip');
  await expect(chip).toBeVisible();
  await expect(chip).toHaveText('Horizon online');
  await expect(page.getByTestId('worker-dot')).toBeHidden();
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

test('the Bridge says when work is waiting for a sleeping worker, and the line can be hidden', async ({ page }) => {
  await page.goto('/?scenario=asleep');
  const strip = page.getByTestId('worker-strip');
  await expect(strip).toContainText('Work is waiting for Horizon. Horizon is asleep or off: last heard 3 hours ago. 2 jobs waiting.');
  await strip.getByTestId('worker-strip-hide').click();
  await expect(strip).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId('today-run')).toBeVisible();
  await expect(page.getByTestId('worker-strip')).toHaveCount(0);
  await page.goto('/?scenario=horizon');
  await expect(page.getByTestId('today-run')).toBeVisible();
  await expect(page.getByTestId('worker-strip')).toHaveCount(0);
});

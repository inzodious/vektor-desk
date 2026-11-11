import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

const read = (name) => JSON.parse(readFileSync(new URL(`../src/fixtures/${name}.json`, import.meta.url), 'utf8'));
const CALM = read('memory');
const LOW = read('memory.low');

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

function fakeMemory(page, start = CALM) {
  let block = structuredClone(start);
  const asked = [];
  page.route('**/api/memory/low', (route) => {
    const mode = route.request().postDataJSON()?.mode;
    asked.push(`${route.request().method()} ${mode}`);
    if (mode === 'on') block = { ...block, low_memory: { ...block.low_memory, on: true, mode: 'on', why: 'You switched it on.', paused: ['lab', 'eval'] } };
    else if (mode === 'off') block = { ...block, low_memory: { ...block.low_memory, on: false, mode: 'off', why: null, paused: [] } };
    else block = structuredClone(start);
    route.fulfill({ json: { ok: true, ...block } });
  });
  page.route(/\/api\/memory(\?.*)?$/, (route) => route.fulfill({ json: block }));
  return asked;
}

// ---------- the card ----------
test('the memory card says how much is free and that the mode is off', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/box');
  const card = page.getByTestId('memory');
  await expect(card).toHaveAttribute('data-state', 'ok');
  await expect(card).toHaveAttribute('data-low', 'false');
  await expect(card.getByTestId('memory-head')).toHaveText('6.0 GB free of 15.0 GB');
  await expect(card.getByTestId('memory-chip')).toHaveText('Enough room');
  await expect(card.getByTestId('memory-low-chip')).toHaveCount(0);
  await expect(card.getByTestId('memory-mode')).toHaveAttribute('data-mode', 'auto');
  await expect(card.getByTestId('memory-line')).toHaveText('Off right now. It switches itself on under 1.5 GB free.');
  await expect(card.getByTestId('memory-waiting')).toHaveCount(0);
  await expect(card.getByTestId('memory-killed')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a box short on memory shows why the mode is on, what waits and what was stopped', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/box?scenario=low');
  const card = page.getByTestId('memory');
  await expect(card).toHaveAttribute('data-state', 'tight');
  await expect(card).toHaveAttribute('data-low', 'true');
  await expect(card.getByTestId('memory-head')).toHaveText('512 MB free of 15.0 GB');
  await expect(card.getByTestId('memory-chip')).toHaveText('Tight');
  await expect(card.getByTestId('memory-low-chip')).toBeVisible();
  await expect(card.getByTestId('memory-line')).toHaveText('On right now. The box has 512 MB free, under the 1.5 GB floor.');
  await expect(card.getByTestId('memory-paused')).toHaveCount(0);
  await expect(card.getByTestId('memory-waiting')).toContainText('Results review since 5:35 PM');
  await expect(card.getByTestId('memory-killed').locator('li')).toHaveCount(3);
  await expect(card.getByTestId('memory-killed')).toContainText('The box ran out of memory and stopped smbd, a program outside the desk.');
  await expect(card.getByTestId('memory-host')).toHaveCount(0);
  await expect(card).not.toContainText(/engine-review|agents-run/);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('memory that cannot be read says so and still lists a stopped job', async ({ page }) => {
  await page.goto('/settings/box?scenario=blind');
  const card = page.getByTestId('memory');
  await expect(card).toHaveAttribute('data-state', 'unknown');
  await expect(card.getByTestId('memory-head')).toHaveText('The box’s memory can’t be read from here');
  await expect(card.getByTestId('memory-killed').locator('li')).toHaveCount(1);
  await expect(card.getByTestId('memory-host')).toContainText('Update box script');
});

test('an older desk without the memory endpoint shows no card', async ({ page }) => {
  await page.route(/\/api\/memory(\?.*)?$/, (route) => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/settings/box');
  await expect(page.getByTestId('jobs')).toBeVisible();
  await expect(page.getByTestId('memory')).toHaveCount(0);
});

test('the memory link from another page lands on the card', async ({ page }) => {
  await page.goto('/settings/box?scenario=low#memory');
  await expect(page.getByTestId('memory')).toBeInViewport();
});

// ---------- the switch ----------
test('switching low-memory mode on saves at once and shows anything the desk pauses', async ({ page }) => {
  const asked = fakeMemory(page);
  await page.goto('/settings/box');
  const card = page.getByTestId('memory');
  await card.locator('[data-choice="on"]').click();
  await expect(card.getByTestId('memory-saved')).toHaveText('Saved. The scheduler follows within 30 seconds.');
  await expect(card.getByTestId('memory-mode')).toHaveAttribute('data-mode', 'on');
  await expect(card).toHaveAttribute('data-low', 'true');
  await expect(card.getByTestId('memory-line')).toHaveText('On right now. You switched it on.');
  await expect(card.getByTestId('memory-paused')).toHaveText('Paused until it is off: the strategy lab and the eval session.');
  await card.locator('[data-choice="off"]').click();
  await expect(card.getByTestId('memory-mode')).toHaveAttribute('data-mode', 'off');
  await expect(card.getByTestId('memory-line')).toHaveText('Off. Everything runs side by side.');
  await card.locator('[data-choice="auto"]').click();
  await expect(card.getByTestId('memory-mode')).toHaveAttribute('data-mode', 'auto');
  expect(asked).toEqual(['PUT on', 'PUT off', 'PUT auto']);
});

test('the switch works from the keyboard', async ({ page }) => {
  const asked = fakeMemory(page, LOW);
  await page.goto('/settings/box');
  const card = page.getByTestId('memory');
  await card.locator('[data-choice="auto"] input').focus();
  await page.keyboard.press('ArrowRight');
  await expect(card.getByTestId('memory-mode')).toHaveAttribute('data-mode', 'on');
  expect(asked).toEqual(['PUT on']);
});

test('a refused switch keeps the old choice and says why', async ({ page }) => {
  await page.route('**/api/memory/low', (route) => route.fulfill({ status: 422, json: { ok: false, error: 'bad_mode', message: 'Mode is auto, on or off.' } }));
  await page.goto('/settings/box');
  const card = page.getByTestId('memory');
  await card.locator('[data-choice="off"]').click();
  await expect(card.getByTestId('memory-saved')).toHaveText('Mode is auto, on or off.');
  await expect(card.getByTestId('memory-mode')).toHaveAttribute('data-mode', 'auto');
});

// ---------- jobs taking turns ----------
test('a job waiting for its turn says so in the jobs list', async ({ page }) => {
  await page.goto('/settings/box?scenario=low');
  const jobs = page.getByTestId('jobs');
  await expect(jobs.getByTestId('jobs-low')).toContainText('Low-memory mode is on, so heavy jobs run one at a time');
  await expect(jobs.getByTestId('jobs-turns')).toHaveText('1 waiting for a turn');
  const row = jobs.locator('.job-list').first().locator('[data-job="engine-review"]');
  await expect(row).toHaveAttribute('data-state', 'waiting');
  await expect(row).toContainText('Waiting for its turn since 5:35 PM');
  await expect(row.locator('.chip')).toHaveText('Waiting');
  await expect(row.getByRole('button')).toHaveCount(0);
  await jobs.getByText(/Agents and housekeeping/).click();
  await expect(jobs.locator('[data-job="agents-run-debrief"]')).toContainText('It needed more memory than the scheduler is allowed (640 MB) and was stopped.');
});

test('today’s run shows the stage that is waiting for its turn', async ({ page }) => {
  await page.goto('/?scenario=low');
  const card = page.getByTestId('today-run');
  await expect(card.locator('[data-stage="review"]')).toHaveAttribute('data-state', 'turn');
  await expect(card.locator('[data-stage="review"]')).toContainText('Waiting for its turn');
  await expect(card.locator('[data-stage="desks"]')).toContainText('Plan keeper desk is running');
});

// ---------- the strip ----------
test('the Bridge carries one line about memory that opens the card and can be hidden', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/?scenario=low');
  const strip = page.getByTestId('memory-strip');
  await expect(strip).toHaveAttribute('data-tone', 'watch');
  await expect(strip).toContainText('Low-memory mode is on, so heavy jobs run one at a time. 3 things were stopped for memory in the last two days.');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await strip.getByTestId('memory-strip-hide').click();
  await expect(strip).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId('today-run')).toBeVisible();
  await expect(page.getByTestId('memory-strip')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('the strip comes back when something new is stopped', async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem('desk.memory.hidden', '1:2'));
  await page.goto('/?scenario=low');
  await page.getByTestId('memory-strip-open').click();
  await expect(page).toHaveURL(/\/settings\/box#memory$/);
});

test('the strip stays off other pages and off a calm box', async ({ page }) => {
  await page.goto('/portfolio?scenario=low');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Holdings');
  await expect(page.getByTestId('memory-strip')).toHaveCount(0);
  await page.goto('/');
  await expect(page.getByTestId('today-run')).toBeVisible();
  await expect(page.getByTestId('memory-strip')).toHaveCount(0);
});

test('a step held back by low-memory mode reads as waiting its turn on First run', async ({ page }) => {
  await page.goto('/settings/first-run?scenario=lowstart');
  const panel = page.getByTestId('start-panel');
  await expect(panel).toHaveAttribute('data-mode', 'running');
  const step = panel.locator('.sd-step[data-state="running"]');
  await expect(step).toContainText('Waiting for its turn: low-memory mode runs heavy jobs one at a time.');
  await expect(step.locator('.chip')).toHaveText('Waiting its turn');
  await expect(page.getByTestId('memory-strip')).toBeVisible();
});

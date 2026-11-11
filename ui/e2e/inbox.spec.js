import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

const JOBS = JSON.parse(readFileSync(new URL('../src/fixtures/jobs.json', import.meta.url), 'utf8'));
const CSV = { name: 'lots-2026-11-09 (1).csv', mimeType: 'text/csv', buffer: Buffer.from('Symbol,Quantity,Cost\nACME,10,100\n') };

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- settings ----------
test('the inbox lists what is waiting', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/data');
  const card = page.getByTestId('inbox');
  await expect(card.getByText('2 files waiting')).toBeVisible();
  await expect(card.getByTestId('inbox-files').locator('li').first()).toContainText('lots-2026-11-09.csv');
  await expect(card.getByTestId('inbox-files').locator('li').first()).toContainText('18 KB · added 9:05 AM');
  await expect(card.getByTestId('inbox-drop')).toContainText('JSON or CSV, up to 25 MB');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('uploading a lot export saves it and offers to read it now', async ({ page }) => {
  let put = null;
  let asked = null;
  let polls = 0;
  await page.route('**/api/inbox/fidelity/*', async (route) => {
    put = { method: route.request().method(), url: decodeURIComponent(route.request().url()), body: route.request().postData() };
    route.fulfill({ status: 201, json: { ok: true, broker: 'fidelity', name: 'lots-2026-11-09 (1).csv', size: 34, sha256: 'x', duplicate: false, import_job: 'engine-lots' } });
  });
  await page.route('**/api/jobs/*/run', (route) => {
    asked = route.request().url().split('/').slice(-2)[0];
    route.fulfill({ status: 202, json: { ok: true, job: asked, request_id: 'req-up' } });
  });
  await page.route(/\/api\/jobs(\?.*)?$/, (route) => {
    polls += 1;
    const body = structuredClone(JOBS);
    if (asked && polls > 1) body.jobs = body.jobs.map((j) => (j.name === asked ? { ...j, last_run: { ...j.last_run, request_id: 'req-up', result: 'ok', finished: '2026-11-09T16:43:00Z' } } : j));
    route.fulfill({ json: body });
  });
  await page.goto('/settings/data?scenario=empty');
  const card = page.getByTestId('inbox');
  await expect(card).toContainText('Nothing in the inbox yet.');
  await card.getByTestId('inbox-file').setInputFiles(CSV);
  await expect(card.getByTestId('inbox-msg')).toHaveText('Saved as lots-2026-11-09 (1).csv (34 B).');
  expect(put.method).toBe('PUT');
  expect(put.url).toMatch(/\/api\/inbox\/fidelity\/lots-2026-11-09 \(1\)\.csv$/);
  expect(put.body).toContain('Symbol,Quantity,Cost');
  await card.getByTestId('inbox-read').click();
  await expect(card).toContainText('Lots done. Your tax lots are in.', { timeout: 15000 });
  expect(asked).toBe('engine-lots');
});

test('a duplicate upload says so', async ({ page }) => {
  await page.route('**/api/inbox/fidelity/*', (route) => route.fulfill({ status: 200, json: { ok: true, broker: 'fidelity', name: 'lots-2026-11-09.csv', size: 34, sha256: 'x', duplicate: true, import_job: 'engine-lots' } }));
  await page.goto('/settings/data');
  await page.getByTestId('inbox-file').setInputFiles(CSV);
  await expect(page.getByTestId('inbox-msg')).toHaveText('Already in the inbox as lots-2026-11-09.csv. Nothing new to save.');
});

test('a refused upload explains what to do', async ({ page }) => {
  await page.route('**/api/inbox/fidelity/*', (route) => route.fulfill({ status: 400, json: { ok: false, error: 'bad_csv', message: 'That .csv file has no comma-separated header line.' } }));
  await page.goto('/settings/data');
  await page.getByTestId('inbox-file').setInputFiles(CSV);
  await expect(page.getByTestId('inbox-msg')).toHaveAttribute('data-phase', 'refused');
  await expect(page.getByTestId('inbox-msg')).toContainText('no header line');
});

test('the wrong kind of file never leaves the browser', async ({ page }) => {
  let sent = false;
  await page.route('**/api/inbox/fidelity/*', (route) => {
    sent = true;
    route.abort();
  });
  await page.goto('/settings/data');
  await page.getByTestId('inbox-file').setInputFiles({ name: 'statement.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4') });
  await expect(page.getByTestId('inbox-msg')).toContainText('Export the lots as CSV');
  expect(sent).toBe(false);
});

test('first run sends the tax-lot step to the inbox', async ({ page }) => {
  await page.goto('/start');
  await page.getByTestId('first-run').locator('[data-step="lots"]').getByRole('link', { name: 'Upload it' }).click();
  await expect(page).toHaveURL(/\/settings\/data#inbox$/);
  await expect(page.getByTestId('inbox')).toBeInViewport();
});

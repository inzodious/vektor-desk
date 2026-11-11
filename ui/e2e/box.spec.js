import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

const BOX = JSON.parse(readFileSync(new URL('../src/fixtures/box.json', import.meta.url), 'utf8'));

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

function fakeBox(page, { fail = [] } = {}) {
  const state = structuredClone(BOX);
  const asked = [];
  const ticks = {};
  const act = (name) => state.actions.find((a) => a.name === name);
  page.route('**/api/box/*/run', (route) => {
    const name = route.request().url().split('/').slice(-2)[0];
    asked.push(name);
    Object.assign(act(name), { queued: true, queued_at: '2026-11-09T16:42:00Z', can_run: false });
    ticks[name] = 0;
    route.fulfill({ status: 202, json: { ok: true, action: name, request_id: `req-${name}`, requested_at: '2026-11-09T16:42:00Z', message: 'Starts within 5 minutes.' } });
  });
  page.route(/\/api\/box$/, (route) => {
    for (const name of Object.keys(ticks)) {
      const a = act(name);
      ticks[name] += 1;
      if (ticks[name] === 2) Object.assign(a, { queued: false, queued_at: null, running: true, last_run: { action: name, request_id: `req-${name}`, started: '2026-11-09T16:42:10Z', finished: null, result: null, exit_code: null, output: null } });
      if (ticks[name] === 3) {
        const failed = fail.includes(name);
        Object.assign(a, { running: false, can_run: false, cooldown_until: '2026-11-09T16:47:00Z', last_run: { action: name, request_id: `req-${name}`, started: '2026-11-09T16:42:10Z', finished: '2026-11-09T16:42:40Z', result: failed ? 'failed' : 'ok', exit_code: failed ? 1 : 0, output: failed ? 'docker said no (synthetic)' : 'All good (synthetic)' } });
        delete ticks[name];
      }
    }
    route.fulfill({ json: state });
  });
  return asked;
}

// ---------- settings ----------
test('box lists each chore with how it last went', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/box');
  const card = page.getByTestId('box');
  await expect(card).toHaveAttribute('data-alive', 'true');
  await expect(card.locator('.job-list .box-row')).toHaveCount(7);
  await expect(card.locator('[data-box="redeploy"]')).toHaveAttribute('data-state', 'never');
  await expect(card.locator('[data-box="backup"]')).toHaveAttribute('data-state', 'ok');
  await expect(card.locator('[data-box="restore-test"]')).toHaveAttribute('data-state', 'failed');
  await expect(card.locator('[data-box="restore-test"]')).toContainText('Didn’t finish 7:09 AM (exit 1)');
  await expect(card.locator('[data-box="logs"]')).toContainText('Queued, runs within 5 min');
  await expect(card.locator('[data-box="status"] button')).toBeDisabled();
  await expect(card.locator('[data-box="status"] button')).toContainText('Again at 11:43 AM');
  await card.locator('[data-box="restore-test"]').getByText('Last output').click();
  await expect(card.locator('[data-box="restore-test"] pre')).toContainText('integrity check');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a box chore goes queued, running, then done', async ({ page }) => {
  const asked = fakeBox(page);
  await page.goto('/settings/box');
  const row = page.getByTestId('box').locator('[data-box="redeploy"]');
  await row.getByRole('button', { name: 'Redeploy now' }).click();
  await expect(row).toHaveAttribute('data-state', 'queued');
  await expect(row).toContainText('Queued, runs within 5 min');
  await expect(row).toContainText('Redeploy done.', { timeout: 15000 });
  await expect(row).toHaveAttribute('data-state', 'ok');
  await expect(row.getByRole('button', { name: 'Redeploy now' })).toContainText('Again at');
  expect(asked).toEqual(['redeploy']);
});

test('a failed box chore points at its output', async ({ page }) => {
  fakeBox(page, { fail: ['check'] });
  await page.goto('/settings/box');
  const row = page.getByTestId('box').locator('[data-box="check"]');
  await row.getByRole('button', { name: 'Check now' }).click();
  await expect(row).toContainText('Check didn’t finish. The output below says why.', { timeout: 15000 });
  await row.getByText('Last output').click();
  await expect(row.locator('pre')).toContainText('docker said no');
});

test('a box refusal shows the reason on the row', async ({ page }) => {
  await page.route('**/api/box/*/run', (route) => route.fulfill({ status: 429, headers: { 'Retry-After': '120' }, json: { ok: false, error: 'cooldown', message: 'Backup ran recently.', cooldown_until: '2026-11-09T17:10:00Z', retry_after: 120 } }));
  await page.goto('/settings/box');
  const row = page.getByTestId('box').locator('[data-box="backup"]');
  await row.getByRole('button', { name: 'Back up now now' }).click();
  await expect(row.locator('.job-note')).toHaveText('Ran a moment ago. Try again at 12:10 PM.');
});

test('the script row offers Update box script only when behind', async ({ page }) => {
  await page.goto('/settings/box');
  const s = page.getByTestId('box-script');
  await expect(s).toHaveAttribute('data-state', 'behind');
  await expect(s).toContainText('2 commits behind main');
  await expect(s).toContainText('a1b2c3d → f9e8d7c');
  await expect(s.locator('[data-box="update-script"]')).toContainText('the box checkout is still catching up to main');
  await expect(s.getByRole('button', { name: 'Update box script now' })).toBeEnabled();
  await page.goto('/settings/box?scenario=current');
  await expect(page.getByTestId('box-script-chip')).toHaveText('Script current');
  await expect(page.getByTestId('box-script')).toHaveCount(0);
  await page.goto('/settings/box?scenario=off');
  await expect(page.getByTestId('box-script')).toHaveAttribute('data-state', 'off');
  await expect(page.getByTestId('box-script').getByTestId('box-hand')).toContainText('install -m 700');
  await expect(page.locator('[data-box="update-script"]')).toHaveCount(0);
});

test('a quiet box shows the one-time step and holds the buttons', async ({ page }) => {
  await page.goto('/settings/box?scenario=down');
  const card = page.getByTestId('box');
  await expect(card).toHaveAttribute('data-alive', 'false');
  await expect(card.getByText('Box not checking in')).toBeVisible();
  await expect(card.getByTestId('box-hand')).toContainText('One hand step left');
  await expect(card.getByTestId('box-hand').locator('code')).toContainText('deploy.sh');
  await expect(card.locator('.job-list').getByRole('button', { disabled: false })).toHaveCount(0);
});

// ---------- compose ----------
test('a safe compose change offers Apply compose', async ({ page }) => {
  let asked = null;
  await page.route('**/api/box/*/run', (route) => {
    asked = route.request().url().split('/').slice(-2)[0];
    route.fulfill({ status: 202, json: { ok: true, action: asked, request_id: 'req-c', requested_at: '2026-11-09T16:42:00Z', message: 'Starts within 5 minutes.' } });
  });
  await page.goto('/settings/box');
  const c = page.getByTestId('box-compose');
  await expect(c).toHaveAttribute('data-state', 'apply');
  await expect(c).toContainText('What changed: cron: environment; api: healthcheck');
  await c.getByRole('button', { name: 'Apply compose now' }).click();
  await expect(c.locator('[data-box="apply-compose"]')).toContainText('Queued, runs within 5 min');
  expect(asked).toBe('apply-compose');
});

test('a compose change that widens access asks for eyes and copies the file', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.route('**/api/box/compose.yaml', (route) => route.fulfill({ status: 200, contentType: 'text/yaml', body: 'services:\n  cron:\n    image: synthetic\n' }));
  await page.goto('/settings/box?scenario=off');
  const c = page.getByTestId('box-compose');
  await expect(c).toHaveAttribute('data-state', 'eyes');
  await expect(c.getByTestId('compose-needs').locator('li')).toHaveCount(2);
  await expect(c.locator('[data-box="apply-compose"]')).toHaveCount(0);
  await c.getByTestId('compose-copy').click();
  await expect(c.getByTestId('compose-copy')).toHaveText('Copied');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('image: synthetic');
});

test('no compose banner when the box matches main', async ({ page }) => {
  await page.goto('/settings/box?scenario=current');
  await expect(page.getByTestId('box')).toBeVisible();
  await expect(page.getByTestId('box-compose')).toHaveCount(0);
});

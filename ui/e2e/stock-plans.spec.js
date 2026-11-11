import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

async function catchWrites(page, answer = {}) {
  const sent = [];
  await page.route('**/api/decisions/plans/**', async (r) => {
    const method = r.request().method();
    if (method === 'GET') return r.fallback();
    const path = new URL(r.request().url()).pathname;
    const body = r.request().postDataJSON();
    sent.push({ method, path, body });
    const reply = typeof answer === 'function' ? answer({ method, path, body }) : answer;
    return r.fulfill({ status: reply.status || 200, json: reply.json || { changed: true, skipped: null, plan: { version: 9, status: body?.approve || path.endsWith('/approve') ? 'approved' : 'draft' } } });
  });
  return sent;
}

test('each holding with a plan gets a card: role, weight, zones, steps and the thesis', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/portfolio');
  await page.getByRole('navigation', { name: 'Portfolio views' }).getByRole('link', { name: 'Stock plans' }).click();
  await expect(page).toHaveURL(/\/portfolio\/stocks$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Stock plans');
  await expect(page.getByTestId('plans-count')).toHaveText('3 plans');
  await expect(page.locator('.ph-big')).toContainText('1 approved · 2 drafts wait on you · 2 without a plan');
  await expect(page.getByTestId('plan-card')).toHaveCount(3);
  const acme = page.locator('[data-plan="ACME"]');
  await expect(acme.getByTestId('plan-role')).toHaveText('Conviction');
  await expect(acme.getByTestId('plan-version')).toHaveText('Draft v2 from the Plan desk');
  await expect(acme.getByTestId('plan-draft')).toContainText('Tightened the trim rule ahead of earnings');
  await expect(acme.getByTestId('plan-changes')).toHaveText('Changed: Trim rule, Next review, 1 new step');
  await expect(acme.getByTestId('plan-draft')).toContainText('v1 stays in force until you approve this one.');
  await expect(acme.getByTestId('plan-weight')).toHaveAttribute('data-band', 'inside');
  await expect(acme.getByTestId('plan-weight')).toContainText('0.5% of the portfolio · band 0% to 5%');
  await expect(acme.getByTestId('plan-ruler')).toHaveAttribute('data-where', 'between');
  await expect(acme.getByTestId('plan-ruler').locator('[data-key="add"]')).toContainText('$1.92 to $2.57');
  await expect(acme.getByTestId('plan-ruler').locator('[data-key="trim"]')).toContainText('$3.87 to $4.52');
  await expect(acme.getByTestId('plan-steps')).toHaveAttribute('data-count', '5');
  await expect(acme.locator('.sp-step').first()).toHaveClass(/next/);
  await expect(acme.locator('[data-step="harvest-2026"]')).toContainText('Dec 7 to Dec 15 · 10 shares · from Individual');
  await expect(acme.getByTestId('plan-thesis').locator('.sp-thesis')).toBeHidden();
  await acme.getByTestId('plan-thesis').locator('summary').click();
  await expect(acme.locator('[data-rule="add"]')).toContainText('Add between $1.92 and $2.57, up to $50 a month, from new deposits only.');
  await expect(acme.getByTestId('plan-warning')).toContainText('no conviction hold yet');
  await expect(page.locator('[data-plan="VXUS"]').getByTestId('plan-ruler')).toHaveAttribute('data-where', 'add');
  await expect(page.locator('[data-plan="FXAIX"]').getByTestId('plan-version')).toHaveText('Approved v1');
  await expect(page.getByTestId('plans-bare')).toHaveAttribute('data-count', '2');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a step added to an approved plan goes straight on, sent with the plan whole', async ({ page }) => {
  const sent = await catchWrites(page);
  await page.goto('/portfolio/stocks');
  const card = page.locator('[data-plan="FXAIX"]');
  await card.getByTestId('plan-add-step').click();
  const form = card.getByTestId('step-form');
  await expect(form).toContainText('It goes straight onto the approved plan.');
  await form.getByRole('button', { name: /^Step/ }).click();
  await form.getByRole('option', { name: 'Harvest a loss' }).click();
  await expect(form).toHaveAttribute('data-kind', 'harvest');
  await expect(form.getByTestId('sf-noBuy')).toHaveValue('31');
  await form.getByTestId('sf-save').click();
  await expect(form.getByTestId('plan-err')).toHaveText('Say how many shares, or type all.');
  expect(sent).toHaveLength(0);
  await form.getByTestId('sf-shares').fill('105');
  await form.getByTestId('sf-due').fill('2026-12-07');
  await form.getByTestId('sf-until').fill('2026-12-15');
  await form.getByRole('button', { name: /^Account/ }).click();
  await form.getByRole('option', { name: 'Individual' }).click();
  await form.getByTestId('sf-save').click();
  await expect(card.getByTestId('plan-msg')).toHaveText('FXAIX plan v9 is saved and in force.');
  await expect(card.getByTestId('step-form')).toHaveCount(0);
  expect(sent).toHaveLength(1);
  expect(sent[0]).toMatchObject({ method: 'PUT', path: '/api/decisions/plans/FXAIX' });
  expect(sent[0].body.approve).toBe(true);
  expect(sent[0].body.plan.role).toBe('core');
  expect(sent[0].body.plan.steps).toEqual([
    { id: 'add', kind: 'add', text: 'Buy $300 of FXAIX', when: 'Each deposit', amount_usd: 300, note: 'Per the deposit route.' },
    { kind: 'harvest', shares: 105, due: '2026-12-07', until: '2026-12-15', account: 'Individual', lots: 'highest_cost', no_buy_days: 31, note: 'Tax-loss harvest. Pick Specific Shares at the broker.' },
  ]);
});

test('a step added to a draft joins the draft and waits for Approve', async ({ page }) => {
  const sent = await catchWrites(page);
  await page.goto('/portfolio/stocks');
  const card = page.locator('[data-plan="ACME"]');
  await card.getByTestId('plan-add-step').click();
  const form = card.getByTestId('step-form');
  await expect(form).toContainText('It joins the draft.');
  await form.getByRole('button', { name: /^Step/ }).click();
  await form.getByRole('option', { name: 'Repay margin' }).click();
  await form.getByTestId('sf-due').fill('2026-11-18');
  await form.getByTestId('sf-save').click();
  await expect(card.getByTestId('plan-msg')).toHaveText('Saved as draft v9. Approve it to put it in force.');
  expect(sent[0].body.approve).toBeUndefined();
  expect(sent[0].body.plan.steps).toHaveLength(6);
  expect(sent[0].body.plan.steps[5]).toEqual({ kind: 'repay', due: '2026-11-18', note: 'The deposit pays off the margin debit.' });
});

test('approve, discard, done and remove each make one call', async ({ page }) => {
  const sent = await catchWrites(page);
  await page.goto('/portfolio/stocks');
  const acme = page.locator('[data-plan="ACME"]');
  await acme.getByTestId('plan-approve').click();
  await expect(acme.getByTestId('plan-msg')).toHaveText('ACME plan v9 is approved and in force.');
  await acme.getByTestId('plan-discard').click();
  await expect(acme.getByTestId('plan-discard')).toHaveText('Yes, discard the draft');
  expect(sent).toHaveLength(1);
  await acme.getByTestId('plan-discard').click();
  await expect(acme.getByTestId('plan-msg')).toHaveText('Draft discarded.');
  await expect(acme.locator('[data-step="trim"]').getByTestId('step-done')).toHaveCount(0);
  await acme.locator('[data-step="margin-repay"]').getByTestId('step-done').click();
  await expect(acme.getByTestId('plan-msg')).toHaveText('Marked done.');
  const fx = page.locator('[data-plan="FXAIX"]');
  await fx.locator('[data-step="add"]').getByTestId('step-remove').click();
  expect(sent).toHaveLength(3);
  await fx.locator('[data-step="add"]').getByTestId('step-remove').click();
  await expect(fx.getByTestId('plan-msg')).toHaveText('Step removed. FXAIX plan v9 is saved and in force.');
  expect(sent.map((s) => `${s.method} ${s.path}`)).toEqual([
    'POST /api/decisions/plans/ACME/approve',
    'POST /api/decisions/plans/ACME/discard',
    'POST /api/decisions/plans/ACME/steps/margin-repay/done',
    'PUT /api/decisions/plans/FXAIX',
  ]);
  expect(sent[3].body).toMatchObject({ approve: true, plan: { steps: [] } });
});

test('a holding without a plan starts from the engine’s zones', async ({ page }) => {
  const sent = await catchWrites(page);
  await page.goto('/portfolio/stocks');
  const row = page.locator('[data-bare="FTEC"]');
  await row.getByTestId('bare-write').click();
  await expect(row.getByTestId('plan-ruler').locator('[data-key="add"]')).toContainText('Suggested add');
  const form = row.getByTestId('plan-form');
  await expect(form.getByTestId('pf-thesis')).toBeFocused();
  await expect(form.getByTestId('pf-addLow')).toHaveValue('211.85');
  await form.getByTestId('pf-approve').click();
  await expect(form.getByTestId('plan-err')).toHaveText('Say in a line or two why you hold it.');
  await form.getByTestId('pf-thesis').fill('Tech tilt, held through the cycle.');
  await form.getByTestId('pf-min').fill('15');
  await form.getByTestId('pf-max').fill('25');
  await form.getByTestId('pf-approve').click();
  await expect(page.getByTestId('plans-bare').getByTestId('plan-msg')).toHaveText('FTEC plan v9 is saved and in force.');
  expect(sent[0]).toMatchObject({ method: 'PUT', path: '/api/decisions/plans/FTEC' });
  expect(sent[0].body).toMatchObject({ approve: true, plan: { role: 'core', thesis: 'Tech tilt, held through the cycle.', weight_band: { min_pct: 15, max_pct: 25 }, add_rule: { zone_low: 211.85, zone_high: 232.04, deposits_only: true }, trim_rule: { zone_low: 272.4, zone_high: 292.59 }, steps: [] } });
});

test('editing a plan saves a draft and shows the desk’s reasons when it refuses', async ({ page }) => {
  let refuse = true;
  const sent = await catchWrites(page, () => (refuse ? { status: 422, json: { detail: 'weight_band: max_pct can’t pass the single-stock cap of 10' } } : {}));
  await page.goto('/portfolio/stocks');
  const card = page.locator('[data-plan="ACME"]');
  await card.getByTestId('plan-edit').click();
  const form = card.getByTestId('plan-form');
  await expect(form.getByTestId('pf-max')).toHaveValue('5');
  await form.getByTestId('pf-max').fill('40');
  await form.getByTestId('pf-draft').click();
  await expect(form.getByTestId('plan-err')).toHaveText('weight_band: max_pct can’t pass the single-stock cap of 10');
  refuse = false;
  await form.getByTestId('pf-max').fill('8');
  await form.getByTestId('pf-draft').click();
  await expect(card.getByTestId('plan-msg')).toHaveText('Saved as draft v9. Approve it to put it in force.');
  expect(sent[1].body.approve).toBeUndefined();
  expect(sent[1].body.plan.weight_band).toEqual({ min_pct: 0, max_pct: 8 });
  expect(sent[1].body.plan.steps).toHaveLength(5);
  expect(sent[1].body.plan.catalysts).toHaveLength(2);
});

test('before the Plan desk’s first run the page says so and still lets him write one', async ({ page }) => {
  await page.goto('/portfolio/stocks?scenario=fresh');
  await expect(page.getByTestId('plans-count')).toHaveText('No plans yet');
  await expect(page.getByTestId('plans-first')).toContainText('Nothing is in force until you approve it.');
  await expect(page.getByTestId('plan-card')).toHaveCount(0);
  await expect(page.getByTestId('plans-bare')).toHaveAttribute('data-count', '5');
});

test('an older desk without stock plans explains itself', async ({ page }) => {
  await page.route('**/api/decisions/plans**', (r) => r.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/portfolio/stocks');
  await expect(page.locator('.ph-big')).toContainText('Not yet');
  await expect(page.getByTestId('plans-soon')).toContainText('switch on with the next desk update');
});

test('Ask the Plan desk opens the Console set to that holding', async ({ page }) => {
  await page.goto('/portfolio/stocks');
  await page.locator('[data-plan="ACME"]').getByTestId('plan-ask').click();
  const dlg = page.getByRole('dialog', { name: 'Console' });
  await expect(dlg.getByRole('button', { name: /^Desk/ })).toContainText('Plan desk');
  await expect(dlg.getByLabel('Symbol, optional')).toHaveValue('ACME');
  await expect(dlg.getByLabel('Ask a desk')).toHaveValue('Refresh the ACME plan');
});

test('the symbol sheet carries the same block and links to the plan', async ({ page }) => {
  await page.goto('/portfolio/stocks');
  await page.locator('[data-plan="FXAIX"] .sp-name [data-sym]').click();
  const sheet = page.getByTestId('sheet-plan');
  await expect(sheet).toHaveAttribute('data-status', 'approved');
  await expect(sheet.getByTestId('plan-role')).toHaveText('Core');
  await expect(sheet.getByTestId('plan-weight')).toContainText('band 50% to 65%');
  await expect(sheet.getByTestId('plan-next')).toContainText('Buy $300 of FXAIX');
  await page.keyboard.press('Escape');
  await page.locator('[data-bare="BND"] [data-sym]').click();
  await expect(page.getByTestId('sheet-plan')).toHaveAttribute('data-status', 'none');
  await expect(page.getByTestId('sheet-plan')).toContainText('No plan for BND yet.');
  await page.getByTestId('sheet-plan').getByRole('link', { name: 'Write a plan' }).click();
  await expect(page).toHaveURL(/\/portfolio\/stocks\?symbol=BND$/);
});

test('steps due on the Bridge lists the coming plan steps and any no-buy window', async ({ page }) => {
  await page.goto('/');
  const card = page.getByTestId('steps-due');
  await expect(card).toHaveAttribute('data-steps', '3');
  await expect(card.locator('[data-due="step"]').first()).toContainText('Review the ACME plan');
  await expect(card.getByTestId('no-buy')).toContainText('No ACME buys while its loss sale is planned.');
  await card.locator('[data-due="step"]').first().getByRole('link', { name: 'Open' }).click();
  await expect(page).toHaveURL(/\/portfolio\/stocks\?symbol=ACME$/);
  await expect(page.locator('[data-plan="ACME"]')).toBeInViewport();
  await page.goto('/');
  await card.getByTestId('due-plans').click();
  await expect(page).toHaveURL(/\/portfolio\/stocks$/);
  await page.goto('/?scenario=fresh');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Bridge');
  await expect(page.getByTestId('steps-due')).toHaveAttribute('data-steps', '0');
  await expect(page.getByTestId('steps-due').locator('[data-due="step"]')).toHaveCount(0);
});

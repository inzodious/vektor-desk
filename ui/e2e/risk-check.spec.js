import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

const RISK = JSON.parse(readFileSync(new URL('../src/fixtures/decisions.risk.json', import.meta.url), 'utf8'));

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

const ANSWERS = [
  ['max_drawdown', /^30%/],
  ['drop_reaction', 'Hold and wait'],
  ['one_year_range', 'Up 15% to down 15%'],
  ['goal', 'A balance of growth and safety'],
  ['experience', 'Index funds and a 401(k)'],
  ['horizon', '12 to 20 years'],
  ['income_stability', 'Steady salary'],
  ['emergency_months', '3 to 5 months'],
];

// ---------- result ----------
test('the risk check shows your band and what holds it there', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/settings/risk');
  const r = page.getByTestId('risk-result');
  await expect(r).toHaveAttribute('data-band', '4');
  await expect(r).toContainText('Band 4');
  await expect(page.getByTestId('risk-limit')).toHaveText('Your nerve says band 5; your timeline and cushion hold it at 4.');
  await expect(r.locator('.risk-facts')).toContainText('75–90%');
  await expect(r.locator('.risk-facts')).toContainText('−33%');
  await expect(page.getByTestId('risk-history').locator('tbody tr')).toHaveCount(2);
  await r.getByRole('button', { name: 'See all five bands' }).click();
  const bands = page.getByTestId('risk-bands');
  await expect(bands.locator('tbody tr')).toHaveCount(5);
  await expect(bands.locator('tr[data-band="4"]')).toContainText('You');
  await page.keyboard.press('Escape');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

// ---------- quiz ----------
test('a fresh desk takes the eight questions and saves them', async ({ page }) => {
  let sent = null;
  await page.route(/\/api\/decisions\/risk(\?.*)?$/, async (route) => {
    if (route.request().method() === 'PUT') {
      sent = route.request().postDataJSON();
      route.fulfill({ json: { changed: true, result: { ...RISK.current, band: 3, label: 'Moderate' }, current: RISK.current } });
      return;
    }
    route.fallback();
  });
  await page.goto('/settings/risk?scenario=fresh');
  const quiz = page.getByTestId('risk-quiz');
  await expect(page.getByTestId('risk-result')).toHaveCount(0);
  await expect(page.getByTestId('risk-count')).toHaveText('0 of 8 answered');
  await expect(page.getByTestId('risk-save')).toBeDisabled();
  for (const [id, label] of ANSWERS) await quiz.locator(`[data-q="${id}"]`).getByText(label).click();
  await expect(page.getByTestId('risk-count')).toHaveText('8 of 8 answered');
  await page.getByTestId('risk-save').click();
  await expect.poll(() => sent).not.toBeNull();
  expect(sent.answers).toEqual({ max_drawdown: 30, drop_reaction: 'hold', one_year_range: 'r3', goal: 'balanced', experience: 'funds', horizon: '12to20', income_stability: 'steady', emergency_months: '3to5' });
});

test('retaking starts from your last answers and can be put back', async ({ page }) => {
  await page.goto('/settings/risk');
  await page.getByTestId('risk-retake').click();
  await expect(page.getByTestId('risk-count')).toHaveText('8 of 8 answered');
  await expect(page.locator('[data-q="goal"] .rq-opt.on')).toHaveText('As much growth as possible');
  await page.getByRole('button', { name: 'Keep my band' }).click();
  await expect(page.getByTestId('risk-result')).toBeVisible();
});

test('a refused save says what is missing', async ({ page }) => {
  await page.route(/\/api\/decisions\/risk(\?.*)?$/, (route) => (route.request().method() === 'PUT' ? route.fulfill({ status: 422, json: { detail: 'goal is not answered' } }) : route.fallback()));
  await page.goto('/settings/risk');
  await page.getByTestId('risk-retake').click();
  await page.getByTestId('risk-save').click();
  await expect(page.getByTestId('risk-msg')).toHaveText('A few questions still need an answer.');
});

test('settings and first run both lead to the risk check', async ({ page }) => {
  await page.goto('/settings');
  await page.getByTestId('risk-link').click();
  await expect(page).toHaveURL(/\/settings\/risk$/);
  await page.goto('/start?scenario=fresh');
  const step = page.getByTestId('first-run').locator('[data-step="risk"]');
  await expect(step).toHaveAttribute('data-state', 'todo');
  await step.getByRole('link', { name: 'Take it' }).click();
  await expect(page.getByTestId('risk-quiz')).toBeVisible();
});

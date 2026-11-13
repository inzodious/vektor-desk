import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

const PAGES = [
  ['/results/day', 'rs-vs-about'],
  ['/portfolio', 'rules-about'],
  ['/portfolio/stocks', 'plans-about'],
  ['/portfolio/risk', 'risk-shock-about'],
  ['/strategies', 'lb-about'],
  ['/strategies/mixes', 'mix-about'],
  ['/strategies/habits', 'pat-nots'],
  ['/decisions', 'notes-about'],
  ['/decisions/journal', 'streak-about'],
  ['/decisions/flight', 'flight-about'],
  ['/research/compare', 'compare-about'],
  ['/settings/crew', 'crew-about'],
  ['/settings/data', 'keys-about'],
  ['/settings/box', 'box-about'],
  ['/settings/risk', 'cv-about'],
];

// ---------- explainers ----------
for (const [path, id] of PAGES) {
  test(`${path} keeps its explainers folded until tapped`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto(path);
    const fold = page.getByTestId(id).first();
    await expect(fold).toBeVisible();
    await expect(page.locator('.about-body:visible')).toHaveCount(0);
    await fold.locator('> summary').click();
    await expect(fold.locator('.about-body')).toBeVisible();
    const o = await overflow(page);
    expect(o.scroll).toBeLessThanOrEqual(o.view);
    expect(errors).toEqual([]);
  });
}

// ---------- results ----------
test('the debrief shows its headline, and the rest opens on a tap', async ({ page }) => {
  await page.goto('/results/day');
  const card = page.getByTestId('rs-debrief');
  await expect(card.locator('.rs-headline')).toBeVisible();
  await expect(card.locator('.rs-words')).toBeHidden();
  await card.getByTestId('rs-more').locator('> summary').click();
  await expect(card.locator('.rs-words')).toBeVisible();
  await expect(card.locator('.rs-words')).toContainText('What happened');
});

// ---------- habits ----------
test('habit tiles keep their caveats in one fold per card', async ({ page }) => {
  await page.goto('/strategies/habits');
  const market = page.getByTestId('market');
  await expect(market.locator('.pat')).toHaveCount(4);
  await expect(page.locator('.pat-not:visible')).toHaveCount(0);
  await market.getByTestId('pat-nots').locator('> summary').click();
  await expect(market.locator('.pat-not')).toHaveCount(4);
  await expect(market.locator('.pat-not').first()).toBeVisible();
});

// ---------- folded cards ----------
test('the lab rules, source grades and box chores open on a tap', async ({ page }) => {
  await page.goto('/strategies');
  const honest = page.getByTestId('honest');
  await expect(honest.locator('.rule').first()).toBeHidden();
  await honest.locator('> summary').click();
  await expect(honest.locator('.rule')).toHaveCount(3);
  await expect(honest.locator('.rule').first()).toBeVisible();
  await page.goto('/research/sources');
  const grades = page.getByTestId('grades');
  await expect(grades.locator('.rule').first()).toBeHidden();
  await grades.locator('> summary').click();
  await expect(grades.locator('.rule').first()).toBeVisible();
  await page.goto('/settings/box');
  const about = page.getByTestId('box-about');
  await expect(about.locator('[data-what="redeploy"]')).toBeHidden();
  await about.locator('> summary').click();
  await expect(about.locator('[data-what="redeploy"]')).toContainText('Recreates the containers');
  await page.goto('/decisions');
  const cleared = page.getByTestId('cleared');
  await expect(cleared.getByTestId('cleared-note')).toBeHidden();
  await cleared.locator('> summary').click();
  await expect(cleared.getByTestId('cleared-note')).toBeVisible();
});

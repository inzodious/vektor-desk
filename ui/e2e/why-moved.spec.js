import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('a big mover shows its verdict on the Bridge and opens why it moved', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  const chips = page.getByTestId('movers');
  await expect(chips.locator('[data-mover]')).toHaveCount(3);
  await expect(chips.locator('[data-mover="ACME"]')).toContainText('Looks overdone');
  await expect(chips.locator('[data-mover="NOVA"]')).toContainText('After the close');
  await expect(chips.locator('[data-mover="FTEC"]')).toHaveAttribute('data-sym', 'FTEC');
  await chips.locator('[data-mover="ACME"]').click();
  await expect(page.getByRole('dialog')).toHaveCount(1);
  const drawer = page.getByRole('dialog', { name: 'Why it moved' });
  await expect(drawer.getByTestId('move-head')).toHaveText('1 of 2 big moves explained');
  await expect(drawer.locator('[data-move-row="ACME"]')).toHaveAttribute('open', '');
  await expect(drawer.getByTestId('move-detail')).toContainText('share offering');
  await expect(drawer.getByTestId('move-detail')).toContainText('Case it’s overdone');
  await expect(drawer.locator('[data-move-row="NOVA"] .mv-wait')).toBeHidden();
  await expect(drawer.getByTestId('moved-with-market')).not.toHaveAttribute('open', '');
  await drawer.getByTestId('explain-now').click();
  await expect(drawer.getByRole('alert')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

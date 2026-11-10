import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, overflow, watchErrors } from './helpers.js';

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

test('research opens the newest dossier with its verdict, range and sources', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/research');
  await expect(page.locator('.ph-big')).toContainText('3');
  await expect(page.locator('.ph-big')).toContainText('1 deep dive queued for tonight');
  const d = page.getByTestId('dossier');
  await expect(d).toHaveAttribute('data-symbol', 'FTEC');
  await expect(d.getByTestId('verdict')).toHaveText('Hold in band');
  await expect(d).toContainText('Now 32x: inside the range, upper half.');
  await expect(d.getByTestId('triggers').locator('.rule')).toHaveCount(3);
  await expect(d.getByTestId('dossier-sources').locator('.src')).toHaveCount(4);
  await expect(d.getByTestId('dossier-sources').locator('.src[data-kind="note"]')).toHaveCount(1);
  await expect(d.getByTestId('key-numbers')).toContainText('Plan target');
  await expect(d.getByTestId('events')).toContainText('NPORT-P');
  expect(errors).toEqual([]);
});

test('picking a dossier swaps the detail and keeps it in the URL', async ({ page }) => {
  await page.goto('/research');
  await page.getByTestId('dossier-list').getByRole('button', { name: /ACME/ }).click();
  await expect(page).toHaveURL(/s=ACME/);
  const d = page.getByTestId('dossier');
  await expect(d).toHaveAttribute('data-symbol', 'ACME');
  await expect(d.getByTestId('verdict')).toHaveText('Stay out');
  await expect(d).toContainText('inside the range, lower half');
  await expect(d.getByTestId('key-numbers')).toContainText('Next earnings');
  await expect(d.getByTestId('events')).toContainText('Earnings report');
  await expect(d.getByTestId('events').locator('.chip.info')).toHaveText('Coming up');
});

test('the show combo filters held and not held dossiers', async ({ page }) => {
  await page.goto('/research');
  const list = page.getByTestId('dossier-list');
  await list.getByRole('button', { name: /^Show/ }).click();
  await page.getByRole('option', { name: 'Not held' }).click();
  await expect(list.locator('.dossier-row')).toHaveCount(1);
  await expect(list.locator('.dossier-row')).toContainText('NOVA');
});

test('no dossiers asks for a deep dive instead of showing blanks', async ({ page }) => {
  await page.route('**/api/agents/dossiers', (r) => r.fulfill({ json: [] }));
  await page.goto('/research');
  await expect(page.locator('.ph-big')).toContainText('0');
  await expect(page.getByText('No dossier open')).toBeVisible();
  await page.getByRole('main').getByRole('button', { name: 'Request a deep dive' }).last().click();
  await expect(page.getByRole('dialog', { name: 'Console' })).toBeVisible();
});

test('refresh now opens the console set to run now for that symbol', async ({ page }) => {
  let sent = null;
  await page.route('**/api/agents/console', async (r) => {
    if (r.request().method() !== 'POST') return r.fallback();
    sent = r.request().postDataJSON();
    return r.fulfill({ status: 201, json: { id: 9, status: 'queued', desk: 'research', question: sent.question, symbol: sent.symbol, run_now: 1 } });
  });
  await page.goto('/research');
  await page.getByRole('button', { name: 'Refresh now' }).click();
  const dlg = page.getByRole('dialog', { name: 'Console' });
  await expect(dlg.getByLabel('Ask a desk')).toHaveValue('Refresh the FTEC dossier');
  await expect(dlg.getByLabel('Symbol, optional')).toHaveValue('FTEC');
  await expect(dlg.getByLabel('Ask a desk')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(dlg.locator('.act-note')).toContainText('Sent to the Research desk to run now.');
  expect(sent).toEqual({ desk: 'research', question: 'Refresh the FTEC dossier', symbol: 'FTEC', run_now: true });
});

test('the robot opens the console with history, chips and a tonight default', async ({ page }) => {
  const errors = watchErrors(page);
  let sent = null;
  await page.route('**/api/agents/console', async (r) => {
    if (r.request().method() !== 'POST') return r.fallback();
    sent = r.request().postDataJSON();
    return r.fulfill({ status: 201, json: { id: 9, status: 'queued', desk: sent.desk } });
  });
  await page.goto('/');
  await page.getByTestId('console-open').click();
  const dlg = page.getByRole('dialog', { name: 'Console' });
  const term = dlg.getByTestId('console-term');
  await expect(term.locator('.t-item')).toHaveCount(2);
  await expect(term).toContainText('> Why is the tax desk quiet about ACME?');
  await expect(term).toContainText('Queued for the Research desk · tonight 1:00 AM');
  await dlg.getByRole('button', { name: 'Where does the next deposit go?' }).click();
  await expect(dlg.getByLabel('Ask a desk')).toHaveValue('Where does the next deposit go?');
  await dlg.getByRole('button', { name: 'Tonight' }).click();
  await expect(dlg.locator('.act-note')).toContainText('Queued for the Plan keeper tonight at 1:00 AM.');
  expect(sent).toEqual({ desk: 'plan_keeper', question: 'Where does the next deposit go?', symbol: null, run_now: false });
  await page.keyboard.press('Escape');
  await expect(dlg).toBeHidden();
  expect(errors).toEqual([]);
});

test('the console refuses an empty question and shows server errors', async ({ page }) => {
  await page.route('**/api/agents/console', async (r) => {
    if (r.request().method() !== 'POST') return r.fallback();
    return r.fulfill({ status: 422, json: { detail: "skeptic can't take Console questions" } });
  });
  await page.goto('/?open=console');
  const dlg = page.getByRole('dialog', { name: 'Console' });
  await dlg.getByRole('button', { name: 'Run now' }).click();
  await expect(dlg.getByRole('alert')).toHaveText('Type a question first.');
  await dlg.getByLabel('Ask a desk').fill('Anything?');
  await dlg.getByRole('button', { name: 'Run now' }).click();
  await expect(dlg.getByRole('alert')).toHaveText("skeptic can't take Console questions");
});

test('the Plan desk takes one holding at a time', async ({ page }) => {
  let sent = null;
  await page.route('**/api/agents/console', async (r) => {
    if (r.request().method() !== 'POST') return r.fallback();
    sent = r.request().postDataJSON();
    return r.fulfill({ status: 201, json: { id: 10, status: 'queued', desk: sent.desk } });
  });
  await page.goto('/?open=console');
  const dlg = page.getByRole('dialog', { name: 'Console' });
  await dlg.getByRole('button', { name: /^Desk/ }).click();
  await dlg.getByRole('option', { name: 'Plan desk' }).click();
  await dlg.getByLabel('Ask a desk').fill('Trim above 12% of the portfolio');
  await dlg.getByRole('button', { name: 'Tonight' }).click();
  await expect(dlg.getByRole('alert')).toHaveText('The Plan desk works one holding at a time. Add its symbol.');
  expect(sent).toBeNull();
  await dlg.getByLabel('Symbol, optional').fill('acme');
  await dlg.getByRole('button', { name: 'Tonight' }).click();
  await expect(dlg.locator('.act-note')).toContainText('Queued for the Plan desk tonight');
  expect(sent).toEqual({ desk: 'plans', question: 'Trim above 12% of the portfolio', symbol: 'ACME', run_now: false });
});

test('slash opens symbol search and Enter opens the sheet', async ({ page, isMobile }) => {
  test.skip(isMobile, 'keyboard shortcut is a desktop affordance');
  await page.goto('/');
  await page.locator('body').press('/');
  const dlg = page.getByRole('dialog', { name: 'Find a symbol' });
  await expect(dlg.getByLabel('Symbol or name')).toBeFocused();
  await page.keyboard.type('nov');
  await expect(dlg.getByRole('option').first()).toContainText('NOVA');
  await page.keyboard.press('Enter');
  const sheet = page.getByRole('dialog', { name: 'NOVA symbol sheet' });
  await expect(sheet).toContainText('Not held');
  await expect(sheet.getByTestId('sheet-dossier')).toContainText('Watching');
  await sheet.getByRole('link', { name: 'Open the dossier' }).click();
  await expect(page).toHaveURL(/\/research\?s=NOVA/);
  await expect(page.getByTestId('dossier')).toHaveAttribute('data-symbol', 'NOVA');
});

test('the search button works on a phone too', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('search-open').click();
  const dlg = page.getByRole('dialog', { name: 'Find a symbol' });
  await dlg.getByRole('option', { name: /FTEC/ }).click();
  await expect(page.getByRole('dialog', { name: 'FTEC symbol sheet' }).getByTestId('sheet-dossier')).toContainText('Hold in band');
});

test('sources list every citation and filter by kind', async ({ page }) => {
  await page.goto('/research/sources');
  const s = page.getByTestId('sources');
  await expect(s.locator('.src')).toHaveCount(8);
  await s.getByRole('button', { name: /^Kind/ }).click();
  await page.getByRole('option', { name: 'Primary' }).click();
  await expect(s.locator('.src')).toHaveCount(5);
  await expect(page.getByTestId('source-mix')).toContainText('Note');
});

test('watchlist adds and removes through the engine', async ({ page }) => {
  const calls = [];
  await page.route('**/api/engine/watchlist**', async (r) => {
    const m = r.request().method();
    if (m === 'GET') return r.fallback();
    calls.push([m, new URL(r.request().url()).pathname, r.request().postDataJSON?.() ?? null]);
    return r.fulfill({ json: { added: 'RKLB', symbols: [] } });
  });
  await page.goto('/research/watchlist');
  const w = page.getByTestId('watchlist');
  await expect(w.locator('tr[data-watch="NOVA"]')).toContainText('Watching');
  await expect(w.locator('tr[data-watch="NOVA"]')).toContainText('In 12 days');
  await w.getByLabel('Symbol to watch').fill('rklb');
  await w.getByRole('button', { name: 'Watch it' }).click();
  await expect(w.locator('.act-note')).toContainText('Added RKLB.');
  await w.getByRole('button', { name: 'Stop watching NOVA' }).click();
  await expect(w.locator('.act-note')).toContainText('Stopped watching NOVA.');
  expect(calls.map((c) => c.slice(0, 2))).toEqual([
    ['POST', '/api/engine/watchlist'],
    ['DELETE', '/api/engine/watchlist/NOVA'],
  ]);
  expect(calls[0][2]).toEqual({ symbol: 'RKLB' });
});

test('watchlist says so when the engine does not serve it yet', async ({ page }) => {
  await page.route('**/api/engine/watchlist', (r) => r.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/research/watchlist');
  await expect(page.locator('.ph-big')).toContainText('Soon');
  await expect(page.getByLabel('Symbol to watch')).toHaveCount(0);
});

test('calendar lists what is coming up and the yield lines', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/research/calendar');
  const ahead = page.getByTestId('cal-ahead');
  await expect(ahead.locator('.row')).toHaveCount(2);
  await expect(ahead.locator('.row').first()).toContainText('ACME');
  await expect(ahead).toContainText('EPS estimate −$0.14');
  await expect(page.getByTestId('cal-recent')).toContainText('Synthetic Director A sold 12,000 shares');
  await expect(page.getByTestId('rates').locator('svg path.mark')).toHaveCount(3);
  await expect(page.getByTestId('market')).toContainText('Inverted');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('the symbol sheet shows the latest filing read and the lane chip only when the lane holds it', async ({ page }) => {
  await page.goto('/');
  await page.locator('.board-row[data-sym="ACME"]').click();
  const acme = page.getByRole('dialog', { name: 'ACME symbol sheet' });
  await expect(acme.getByTestId('filing-chip')).toHaveText('Leans good · 72% sure');
  await expect(acme.getByTestId('sheet-filing')).toContainText('Current report · Contract');
  await expect(acme.getByTestId('filing-lane')).toHaveText('On the filings lane’s paper book');
  await page.keyboard.press('Escape');
  await page.goto('/research/watchlist');
  await page.locator('tr[data-watch="NOVA"] [data-sym]').click();
  const nova = page.getByRole('dialog', { name: 'NOVA symbol sheet' });
  await expect(nova.getByTestId('filing-chip')).toHaveText('Leans bad · 61% sure');
  await expect(nova.getByTestId('filing-lane')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.goto('/');
  await page.locator('.board-row[data-sym="FTEC"]').click();
  await expect(page.getByRole('dialog', { name: 'FTEC symbol sheet' }).getByTestId('sheet-dossier')).toBeVisible();
  await expect(page.getByTestId('sheet-filing')).toHaveCount(0);
});


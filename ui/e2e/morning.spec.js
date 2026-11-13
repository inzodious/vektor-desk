import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, ROUTES, overflow, record, watchErrors } from './helpers.js';

const NIGHT = JSON.parse(readFileSync(new URL('../src/fixtures/overnight.json', import.meta.url), 'utf8'));

const NOT_FOUND = { status: 404, contentType: 'application/json', body: '{"detail":"Not Found"}' };

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(MONDAY_MIDDAY);
});

// ---------- the Bridge ----------
test('This morning has three doors, each with a count, a line and when it ran', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  const morning = page.getByTestId('morning');
  await expect(morning.locator('.door')).toHaveCount(3);
  await expect(page.getByTestId('morning-night')).toHaveText('4 of 5 steps done. Not done: Write the debrief.');

  const strategies = morning.locator('[data-door="strategies"]');
  await expect(strategies).toHaveAttribute('data-state', 'ready');
  await expect(strategies).toContainText('Strategies tested');
  await expect(page.getByTestId('door-strategies-count')).toHaveText('24 of 26 tested');
  await expect(strategies).toContainText('5 held up out of sample. 10 inside the noise, 8 fell short, 1 inconclusive, 2 still to run.');
  await expect(strategies).toContainText('Today, 3:12 AM ET');

  const holdings = morning.locator('[data-door="holdings"]');
  await expect(holdings).toContainText('Your holdings analysed');
  await expect(page.getByTestId('door-holdings-count')).toHaveText('4 of 5 analysed');
  await expect(holdings).toContainText('4 of 5 holdings analysed, 2 of them today. 1 failed last night.');
  await expect(holdings).toContainText('Today, 3:44 AM ET');

  const ideas = morning.locator('[data-door="opportunities"]');
  await expect(ideas).toContainText('Buying opportunities');
  await expect(page.getByTestId('door-opportunities-count')).toHaveText('4 ideas');
  await expect(ideas).toContainText('1 worth buying now. 2 could become a buy, 1 not for now. Top: QUAL, 12% under its high.');

  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('What ran overnight is a closed fold that lists each step with the line it left', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/');
  const fold = page.getByTestId('night-steps');
  await expect(fold.locator('summary')).toContainText('What ran overnight');
  await expect(fold.locator('summary')).toContainText('5 steps');
  await expect(fold.locator('li').first()).toBeHidden();
  await fold.locator('summary').click();
  await expect(fold.locator('li')).toHaveCount(5);
  await expect(fold.locator('[data-step="mirror"]')).toContainText('Accounts');
  await expect(fold.locator('[data-step="mirror"]')).toContainText('Done');
  await expect(fold.locator('[data-step="mirror"] .night-line')).toHaveCount(0);
  await expect(fold.locator('[data-step="engine-daily"]')).toContainText('Daily numbers');
  await expect(fold.locator('[data-step="engine-daily"] .night-line')).toHaveText('It already ran on the version that is live.');
  await expect(fold.locator('[data-step="strategies"] .night-line')).toHaveText('24 strategies tested, 5 held up out of sample');
  await expect(fold.locator('[data-step="agents-run-debrief"]')).toHaveAttribute('data-state', 'failed');
  await expect(fold.locator('[data-step="agents-run-debrief"]')).toContainText('Didn’t finish');
  await expect(fold.locator('[data-step="agents-run-debrief"] .night-line')).toHaveText('The model call timed out.');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);

  const raw = { ...NIGHT, steps: NIGHT.steps.map((s, i) => (i ? s : { ...s, detail: '{"accounts": 4, "rows": 212}' })) };
  await page.route('**/api/overnight*', (route) => route.fulfill({ json: raw }));
  await page.goto('/');
  await page.getByTestId('night-steps').locator('summary').click();
  await expect(page.getByTestId('night-steps').locator('li')).toHaveCount(5);
  await expect(page.getByTestId('night-steps')).not.toContainText('{');
  await page.unroute('**/api/overnight*');

  await page.goto('/?scenario=fresh');
  await expect(page.getByTestId('morning')).toBeVisible();
  await expect(page.getByTestId('night-steps')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('each door opens the page it promises', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('morning').locator('[data-door="strategies"]').click();
  await expect(page).toHaveURL(/\/strategies$/);
  await expect(page.getByTestId('library')).toBeVisible();

  await page.goto('/');
  await page.getByTestId('morning').locator('[data-door="holdings"]').click();
  await expect(page).toHaveURL(/\/research$/);
  await expect(page.getByTestId('holding-list')).toBeVisible();

  await page.goto('/');
  await page.getByTestId('morning').locator('[data-door="opportunities"]').click();
  await expect(page).toHaveURL(/\/research\/opportunities$/);
  await expect(page.getByTestId('ideas').locator('.idea')).toHaveCount(4);
});

test('before the first night every door says why it is empty', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/?scenario=fresh');
  const morning = page.getByTestId('morning');
  await expect(page.getByTestId('morning-night')).toHaveText('Tonight’s run starts at 23:30.');
  await expect(morning.locator('[data-door="strategies"]')).toHaveAttribute('data-state', 'waiting');
  await expect(page.getByTestId('door-strategies-count')).toHaveText('0 of 26 tested');
  await expect(morning.locator('[data-door="strategies"]')).toContainText('In tonight’s queue. The lab starts at 1 AM.');
  await expect(page.getByTestId('door-holdings-count')).toHaveText('0 of 5 analysed');
  await expect(morning.locator('[data-door="holdings"]')).toContainText('No holding has been analysed yet. The first pass runs tonight from 11:05 PM.');
  await expect(page.getByTestId('door-opportunities-count')).toHaveText('0 ideas');
  await expect(morning.locator('[data-door="opportunities"]')).toContainText('No list yet: the engine has not run. It fills in after the next engine run.');
  expect(errors).toEqual([]);
});

test('a desk that does not serve them yet says so, and one that fails says that', async ({ page }) => {
  await page.route('**/api/lab/library*', (route) => route.fulfill(NOT_FOUND));
  await page.route('**/api/agents/holdings*', (route) => route.fulfill(NOT_FOUND));
  await page.route('**/api/opportunities*', (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"boom"}' }));
  await page.goto('/');
  const morning = page.getByTestId('morning');
  await expect(morning.locator('[data-door="strategies"]')).toHaveAttribute('data-state', 'off');
  await expect(page.getByTestId('morning-night')).toHaveText('4 of 5 steps done. Not done: Write the debrief.');
  await page.route('**/api/overnight*', (route) => route.fulfill(NOT_FOUND));
  await page.goto('/');
  await expect(page.getByTestId('morning-night')).toHaveText('What ran overnight, and where to read it');
  await expect(morning.locator('[data-door="strategies"]')).toContainText('The strategy library arrives with the next desk update.');
  await expect(morning.locator('[data-door="holdings"]')).toContainText('One analysis per holding arrives with the next desk update.');
  await expect(morning.locator('[data-door="opportunities"]')).toHaveAttribute('data-state', 'down');
  await expect(morning.locator('[data-door="opportunities"]')).toContainText('The desk did not answer. It tries again by itself.');
});

// ---------- strategies ----------
test('Strategies leads with the overnight table, grouped by kind, with honest words', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/strategies');
  await expect(page.getByTestId('strat-count')).toHaveText('24');
  await expect(page.locator('.ph-big')).toContainText('of 26 tested overnight · 5 held up · 7 on paper or eligible');
  await expect(page.getByTestId('lb-lede')).toContainText('7 racers on paper');
  await expect(page.getByTestId('stages').locator('[data-stage="paper"] b')).toHaveText('6');
  await expect(page.getByTestId('stages').locator('[data-stage="eligible"] b')).toHaveText('1');
  const lib = page.getByTestId('library');
  const how = lib.getByTestId('lib-how');
  await expect(how.locator('> summary')).toHaveText('How to read this');
  await expect(lib.getByTestId('lib-note')).toBeHidden();
  await expect(lib.getByTestId('lib-benchmarks')).toBeHidden();
  await how.locator('> summary').click();
  await expect(lib.getByTestId('lib-note')).toContainText('Held up means ahead of its benchmark by more than luck allows');
  await expect(lib.getByTestId('lib-note')).toContainText('The last two years of data are held back');
  await expect(lib.getByTestId('lib-legend')).toHaveCount(0);
  const legend = lib.getByTestId('lib-benchmarks');
  await expect(legend).toContainText('17 of 26 are measured against the S&P 500 (SPY). The S&P 500 index fund SPY, bought and held with dividends reinvested.');
  await expect(legend.locator('details')).toHaveJSProperty('open', false);
  await legend.locator('summary').click();
  await expect(legend.locator('li')).toHaveCount(5);
  await expect(legend.locator('li').first()).toContainText('The funds in your plan at their target weights.');
  await expect(legend.locator('li', { hasText: 'US stock market (French)' })).toContainText('Every US stock weighted by size');
  await expect(lib.locator('.lib-group')).toHaveCount(3);
  await expect(lib.locator('.lib-group h3')).toHaveText(['Old and tested', 'Practical', 'Novel and creative']);
  const classic = lib.locator('.lib-group[data-kind="classic"]');
  await expect(classic.locator('.lib-row')).toHaveCount(5);
  const top = classic.locator('.lib-row').first();
  await expect(top.locator('summary')).toHaveText('12-1 momentum+3.1 pts a yearHeld up');
  await expect(top.locator('.lib-more-text')).toBeHidden();
  await expect(lib.locator('.lib-more-text:visible')).toHaveCount(0);
  await top.locator('summary').click();
  await expect(top.locator('.lib-desc')).toBeVisible();
  await expect(classic.locator('.lib-row').first().getByTestId('lib-bench')).toHaveText('Measured against the S&P 500 (SPY)');
  await expect(classic.locator('.lib-row').first().getByTestId('lib-bench')).toHaveAttribute('title', 'The S&P 500 index fund SPY, bought and held with dividends reinvested.');
  await expect(classic.locator('.lib-row', { hasText: 'Profitability and quality tilt' }).getByTestId('lib-bench')).toHaveText('Measured against the US stock market');
  await expect(lib.locator('.lib-row:visible').getByTestId('lib-bench')).toHaveCount(await lib.locator('.lib-row:visible').count());
  await expect(classic.locator('.lib-row').first()).toContainText('+3.1 pts a year');
  await expect(classic.locator('.lib-row').first()).toContainText('Ahead by 3.1 points a year out of sample, more than luck explains across 212 tries.');
  await expect(top.getByTestId('lib-open')).toHaveAttribute('href', '/strategies/momentum-12-1');
  await expect(lib.getByTestId('lib-retest')).toHaveCount(1);
  await expect(classic.locator('.lib-row', { hasText: 'Dual momentum' }).getByTestId('lib-retest')).toHaveText('This result is from an older version of the rule. It is queued to run again.');
  await expect(classic.locator('.lib-row', { hasText: 'Dual momentum' }).locator('summary .chip')).toHaveCount(1);
  await classic.getByRole('button', { name: /Show all/ }).click();
  await expect(classic.locator('.lib-row[data-verdict="fell_short"]').first()).toContainText('Fell short');
  await expect(lib.locator('.lib-row[data-verdict="waiting"]')).toContainText('Waiting');
  await expect(lib.locator('.lib-row[data-verdict="waiting"]').getByTestId('lib-open')).toHaveCount(0);
  const box = await lib.boundingBox();
  const board = await page.getByTestId('strategies').boundingBox();
  expect(box.y).toBeLessThan(board.y);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('before the first night the table lists every strategy with its reason, and an older desk shows the race alone', async ({ page }) => {
  await page.goto('/strategies?scenario=fresh');
  const lib = page.getByTestId('library');
  await expect(lib).toContainText('On tonight’s list');
  await expect(lib).toContainText('26 waiting for their first run');
  await expect(lib.locator('.lib-row').first()).toContainText('In tonight’s queue. The lab starts at 1 AM.');
  await expect(lib.locator('.lib-row').first()).toContainText('Waiting');
  await expect(page.getByTestId('strat-count')).toHaveText('26');
  await expect(page.locator('.ph-big')).toContainText('on tonight’s list, waiting for their first run');

  await page.route('**/api/lab/strategies', (r) => r.fulfill({ json: { strategies: [], rules: [], features: [], grammar: {} } }));
  await page.goto('/strategies');
  await expect(page.getByTestId('library')).toBeVisible();
  await expect(page.getByTestId('strategies')).toHaveCount(0);
  await expect(page.locator('main')).not.toContainText('Nothing in the lab yet');
  await expect(page.locator('.ph-big')).toContainText('7 on paper or eligible');
  await page.unroute('**/api/lab/strategies');

  await page.route('**/api/lab/library*', (route) => route.fulfill(NOT_FOUND));
  await page.goto('/strategies');
  await expect(page.getByTestId('strategies')).toBeVisible();
  await expect(page.getByTestId('library')).toHaveCount(0);
});

// ---------- research ----------
test('Research is organised by holding, each with a status', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/research');
  await expect(page.getByTestId('research-count')).toHaveText('4 of 5');
  await expect(page.getByTestId('holding-line')).toContainText('4 of 5 holdings analysed, 2 of them today. 1 failed last night.');
  const list = page.getByTestId('holding-list');
  await expect(list.locator('.hold-row')).toHaveCount(5);
  await expect(list.locator('[data-holding="FXAIX"]')).toContainText('Analysed today');
  await expect(list.locator('[data-holding="FXAIX"]')).toContainText('Add on plan');
  await expect(list.locator('[data-holding="FTEC"]')).toContainText('Analysed Thu Nov 5. It is in tonight’s pass.');
  await expect(list.locator('[data-holding="BND"]')).toContainText('Last try failed at 3:12 AM: the model call timed out.');
  await expect(list.locator('[data-holding="BND"]')).toContainText('Last try failed');
  await expect(list).toContainText('Next pass: Today, 11:05 PM ET.');

  const d = page.getByTestId('dossier');
  await expect(d).toHaveAttribute('data-symbol', 'FXAIX');
  await expect(d.getByTestId('dossier-lead')).toContainText('Add on schedule. It is the core of the book and still under its band.');
  await expect(d.getByTestId('dossier-lead')).toContainText('What it is. A fund that owns the 500 largest US companies');
  await expect(d.getByTestId('valuation-note')).toHaveText('Fair to slightly rich. Earnings growth is carrying the price, not hope.');
  await expect(d.getByTestId('range-label')).toHaveText('Valuation range · Price against next year’s earnings');
  await expect(d.locator('.range .lab').first()).toHaveText('17x');
  await expect(d.locator('.range')).not.toContainText('$');
  await expect(d).toContainText('Now 22x: inside the range, upper half.');
  await expect(d.getByTestId('dossier-risks').locator('li')).toHaveCount(2);
  await expect(d.getByTestId('dossier-fit')).toContainText('It is 59% of the book against a 60% target');
  await expect(d).toContainText('numbers as of Mon Nov 9');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a fund with no valuation range shows its reason as text and no strip', async ({ page }) => {
  const note = 'A broad fund has no single fair price, so there is no range here. It is judged by its cost and how closely it tracks its index.';
  await page.route('**/api/agents/dossiers', async (route) => {
    const res = await route.fetch();
    const rows = await res.json();
    await route.fulfill({ json: rows.map((r) => (r.symbol === 'FTEC' ? { ...r, dossier: { ...r.dossier, valuation_range: { low: null, high: null, now: null, unit: null, basis: null }, valuation_note: note } } : r)) });
  });
  await page.goto('/research?s=FTEC');
  const d = page.getByTestId('dossier');
  await expect(d.getByTestId('valuation-note')).toHaveText(note);
  await expect(d.getByTestId('range-label')).toHaveText('Valuation');
  await expect(d.locator('.range')).toHaveCount(0);
  await expect(d).not.toContainText('No valuation range written yet');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

test('an older dossier with a long method note prints it as plain text and its multiples without a dollar sign', async ({ page }) => {
  const basis = 'Forward P/E on the listed shares (price ÷ next-year consensus EPS). Low 22x = the recent trough reading; high 33x = the five-year average. Now 24.57x at the close of $100.00.';
  await page.route('**/api/agents/dossiers', async (route) => {
    const res = await route.fetch();
    const rows = await res.json();
    await route.fulfill({ json: rows.map((r) => (r.symbol === 'FTEC' ? { ...r, dossier: { ...r.dossier, valuation_range: { low: 22, high: 33, now: 24.57, basis } } } : r)) });
  });
  await page.goto('/research?s=FTEC');
  const d = page.getByTestId('dossier');
  await expect(d.getByTestId('range-label')).toHaveText('Valuation range · Forward P/E on the listed shares');
  await expect(d.getByTestId('range-basis')).toHaveText(basis);
  await expect(d.getByTestId('range-basis')).toHaveCSS('text-transform', 'none');
  await expect(d.locator('.range .lab').first()).toHaveText('22x');
  await expect(d.locator('.range .lab').last()).toHaveText('33x');
  await expect(d).toContainText('Now 24.6x: inside the range, lower half.');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

test('a holding with no analysis says why and offers to run one', async ({ page }) => {
  await page.goto('/research');
  await page.getByTestId('holding-list').locator('[data-holding="BND"]').click();
  await expect(page).toHaveURL(/s=BND/);
  const none = page.getByTestId('not-analysed');
  await expect(none).toContainText('No analysis of BND yet');
  await expect(none).toContainText('Last try failed at 3:12 AM: the model call timed out. No earlier analysis. Next pass: Today, 11:05 PM ET.');
  await none.getByRole('button', { name: 'Analyse BND now' }).click();
  await expect(page.getByRole('dialog', { name: 'Console' })).toBeVisible();
});

test('buying opportunities lists each idea with why now, a zone, a size and what would make it wrong', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/research/opportunities');
  await expect(page.getByTestId('opp-count')).toHaveText('3');
  await expect(page.locator('.ph-big')).toContainText('ideas to look at · 1 not for now');
  const top = page.getByTestId('opp-top');
  await expect(top).toContainText('1 worth buying now. 2 could become a buy, 1 not for now. Top: QUAL, 12% under its high.');
  await expect(top.locator('.opp-note:visible')).toHaveCount(0);
  await top.getByTestId('opp-how').locator('> summary').click();
  await expect(top.locator('.opp-note:visible')).toHaveCount(7);
  await expect(top).toContainText('1 of these has no written case yet.');
  await expect(top).toContainText('No risk check on file yet, so sizes use the Moderate band');
  await expect(top).toContainText('It is a sort, not a forecast.');
  const first = page.getByTestId('ideas').locator('[data-idea="QUAL"]');
  await expect(first).toContainText('Worth buying now');
  await expect(first.getByTestId('idea-usd')).toHaveText('$100');
  await expect(first.locator('> .idea-why')).toHaveText('A broad sell-off pulled quality names down with everything else; earnings estimates for the fund’s top holdings have not moved.');
  await expect(first.locator('.idea-plan')).toBeHidden();
  await expect(page.getByTestId('ideas').locator('.idea-plan:visible')).toHaveCount(0);
  await first.getByTestId('idea-more').locator('> summary').click();
  await expect(first.locator('.idea-plan')).toBeVisible();
  await expect(first).toContainText('Cheap for a reason that looks temporary.');
  await expect(first).toContainText('$171.20 to $180.40. Now $180.40, inside the zone.');
  await expect(first).toContainText('$100 (about 0.55 shares). A starter slice, cut to the cash that is free today.');
  await expect(first).toContainText('Off below $162.00');
  await expect(first).toContainText('Not held');
  const acme = page.getByTestId('ideas').locator('[data-idea="ACME"]');
  await expect(acme).toContainText('A buy in any account would void the planned loss sale.');
  await expect(acme).toContainText('You hold 0.5%');
  await expect(acme).not.toContainText('$0');
  await expect(page.getByTestId('ideas')).not.toContainText('score');
  await expect(page.getByTestId('opp-passed')).toContainText('BND');
  await page.getByTestId('ideas').locator('.idea-fold > summary').click();
  await acme.getByTestId('idea-more').locator('> summary').click();
  await acme.getByRole('link', { name: 'Open its research' }).click();
  await expect(page).toHaveURL(/\/research\?s=ACME$/);
  await expect(page.getByTestId('dossier')).toHaveAttribute('data-symbol', 'ACME');
  expect(errors).toEqual([]);
});

test('the page leads with what could be bought and folds the rest under Not now', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/research/opportunities');
  const ideas = page.getByTestId('ideas');
  await expect(ideas.locator('[data-group]')).toHaveCount(3);
  await expect(ideas.locator('[data-group="buy"] h2')).toHaveText('Worth buying 1');
  await expect(ideas.locator('[data-group="could"] h2')).toHaveText('Could become a buy 2');
  await expect(ideas.locator('[data-group="buy"] .idea')).toHaveAttribute('data-idea', 'QUAL');
  await expect(ideas.locator('[data-group="could"] .idea')).toHaveCount(2);
  const fold = ideas.locator('[data-group="not_now"]');
  await expect(fold.locator('> summary')).toContainText('Not now');
  await expect(fold.locator('> summary .chip')).toHaveText('1');
  await expect(fold.locator('.idea')).toBeHidden();
  await fold.locator('> summary').click();
  await expect(fold.locator('[data-idea="ACME"]')).toBeVisible();
  await fold.locator('> summary').click();
  await expect(fold.locator('.idea')).toBeHidden();
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a could row says what the desk is waiting for, and the page quotes the lab on its own rule', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/research/opportunities');
  const ideas = page.getByTestId('ideas');
  await expect(ideas.locator('[data-idea="VXUS"]').getByTestId('idea-becomes')).toBeHidden();
  await ideas.locator('[data-idea="VXUS"]').getByTestId('idea-more').locator('> summary').click();
  await expect(ideas.locator('[data-idea="VXUS"]').getByTestId('idea-becomes')).toBeVisible();
  await expect(ideas.locator('[data-idea="VXUS"]').getByTestId('idea-becomes')).toHaveText('What would change it No written case yet. It is next in line tonight; the desk writes up to 6 a night.');
  await expect(ideas.locator('[data-idea="NOVA"]').getByTestId('idea-becomes')).toContainText('It moves up only if a later Scout idea gets past Skeptic; no price changes that.');
  await expect(ideas.locator('[data-idea="QUAL"]').getByTestId('idea-becomes')).toHaveCount(0);
  await ideas.locator('[data-group="not_now"] > summary').click();
  await expect(ideas.locator('[data-idea="ACME"]').getByTestId('idea-becomes')).toHaveCount(0);
  const lab = page.getByTestId('opp-top').getByTestId('opp-evidence');
  await expect(lab).toHaveCount(2);
  await expect(lab.first()).toBeHidden();
  await page.getByTestId('opp-how').locator('> summary').click();
  await expect(lab.first()).toHaveText('Lab test, Buy a stock dip and hold: Ahead by 1.2 points a year out of sample, but inside the luck band for 212 tries.');
  await expect(lab.nth(1)).toHaveText('Lab test, Average down on the way: Behind by 0.8 points a year out of sample.');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await page.goto('/research/opportunities?scenario=evening');
  await expect(page.getByTestId('ideas').locator('[data-idea="NOVA"]').getByTestId('idea-becomes')).toHaveCount(0);
  await page.goto('/research/opportunities?scenario=fresh');
  await expect(page.getByTestId('opp-top')).toBeVisible();
  await expect(page.getByTestId('opp-evidence')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('when nothing is a buy or close to one the Not now list stays folded until opened, and an older desk keeps one flat list', async ({ page }) => {
  const fact = '31.3% under its 52-week high at the latest price (31.9% when the case was written)';
  let mode = 'not_now';
  await page.route('**/api/opportunities*', async (route) => {
    const res = await route.fetch();
    const json = await res.json();
    const rows = json.rows.map((r) => {
      const rest = { ...r };
      delete rest.group;
      delete rest.group_label;
      return mode === 'flat' ? rest : { ...rest, group: 'not_now', group_label: 'Not now', facts: [fact, ...r.facts.slice(1)] };
    });
    await route.fulfill({ json: { ...json, headline: 'Nothing rated a buy yet. 4 not for now.', rows } });
  });
  await page.goto('/research/opportunities');
  const ideas = page.getByTestId('ideas');
  await expect(page.getByTestId('opp-count')).toHaveText('0');
  await expect(page.locator('.ph-big')).toContainText('ideas to look at · 4 not for now');
  await expect(ideas.locator('[data-group="not_now"] .idea')).toHaveCount(4);
  await expect(page.getByTestId('opp-top')).toContainText('Nothing rated a buy yet. 4 not for now.');
  await expect(ideas.locator('[data-idea="QUAL"]')).toBeHidden();
  await ideas.locator('.idea-fold > summary').click();
  await expect(ideas.locator('[data-idea="QUAL"]')).toBeVisible();
  await expect(ideas.locator('[data-idea="QUAL"] .idea-facts li').first()).toHaveText(fact);
  const gaps = await page.locator('.idea').evaluateAll((cards) =>
    cards.map((card) => {
      const pad = parseFloat(getComputedStyle(card).paddingRight);
      const li = card.querySelector('.idea-facts li').getBoundingClientRect();
      return Math.round(card.getBoundingClientRect().right - li.right - pad);
    }),
  );
  gaps.forEach((gap) => expect(gap).toBeGreaterThanOrEqual(-1));
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);

  mode = 'flat';
  await page.goto('/research/opportunities');
  await expect(page.getByTestId('opp-count')).toHaveText('4');
  await expect(page.getByTestId('ideas').locator('[data-group]')).toHaveCount(0);
  await expect(page.getByTestId('ideas').locator('.idea')).toHaveCount(4);
});

test('each idea says which price it is worked out from, and why a buy is not in the queue', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/research/opportunities');
  await expect(page.getByTestId('opp-top')).toContainText('Prices run to Mon Nov 9. NOVA is still at an earlier close');
  const ideas = page.getByTestId('ideas');
  await expect(ideas.locator('[data-idea="QUAL"]').getByTestId('idea-asof')).toHaveText('Priced at Mon Nov 9, 11:40 AM ET. The written case is from Fri Nov 6; the price is 1.8% lower since.');
  await expect(ideas.locator('[data-idea="NOVA"]').getByTestId('idea-asof')).toContainText('The desk has no newer price for it than Fri Nov 6');
  await expect(ideas.locator('[data-idea="NOVA"]')).not.toContainText('Numbers from');
  await expect(ideas.locator('[data-idea="NOVA"]').getByTestId('idea-queue')).toHaveText('See it in Decisions');
  await expect(ideas.getByTestId('idea-queue')).toHaveCount(1);
  await expect(ideas.getByTestId('idea-not-queued')).toHaveCount(0);

  await page.goto('/research/opportunities?scenario=evening');
  await expect(page.getByTestId('opp-top')).toContainText('2 worth buying once the margin debit is paid');
  const debit = page.getByTestId('ideas');
  await expect(debit.locator('[data-idea="QUAL"]').getByTestId('idea-not-queued')).toHaveText('Pay the margin debit first: $1,500 is open, so no buy goes to the queue.');
  await expect(debit.locator('[data-idea="NOVA"]').getByTestId('idea-not-queued')).toBeHidden();
  await debit.locator('[data-idea="NOVA"]').getByTestId('idea-more').locator('> summary').click();
  await expect(debit.locator('[data-idea="NOVA"]').getByTestId('idea-not-queued')).toBeVisible();
  await expect(debit.getByTestId('idea-queue')).toHaveCount(0);
  await expect(debit.locator('[data-idea="ACME"]').getByTestId('idea-not-queued')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a long stance label stays inside its card', async ({ page }) => {
  const labels = ['You already hold this; the analysis says hold, not add', 'Watch: the case says buy, but your research note says hold'];
  await page.route('**/api/opportunities*', async (route) => {
    const res = await route.fetch();
    const json = await res.json();
    await route.fulfill({ json: { ...json, rows: json.rows.map((r, k) => ({ ...r, stance: 'watch', stance_label: labels[k % 2] })) } });
  });
  await page.goto('/research/opportunities');
  await expect(page.getByTestId('ideas')).toContainText(labels[1]);
  const gaps = await page.locator('.idea').evaluateAll((cards) =>
    cards.map((card) => {
      const pad = parseFloat(getComputedStyle(card).paddingRight);
      const chip = card.querySelector('.card-head .chip').getBoundingClientRect();
      return Math.round(card.getBoundingClientRect().right - chip.right - pad);
    }),
  );
  gaps.forEach((gap) => expect(gap).toBeGreaterThanOrEqual(-1));
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
});

test('an empty opportunities list gives its reason', async ({ page }) => {
  await page.goto('/research/opportunities?scenario=fresh');
  await expect(page.getByTestId('opp-count')).toHaveText('0');
  await expect(page.getByTestId('opp-top')).toContainText('No list yet: the engine has not run. It fills in after the next engine run.');
  await expect(page.getByTestId('ideas')).toHaveCount(0);

  await page.route('**/api/opportunities*', (route) => route.fulfill(NOT_FOUND));
  await page.goto('/research/opportunities');
  await expect(page.getByText('The ranked list of buying opportunities arrives with the next desk update.')).toBeVisible();
});

// ---------- decisions ----------
test('each queue item shows its as-of', async ({ page }) => {
  await page.goto('/decisions');
  const first = page.locator('[data-prop]').first();
  await expect(first.getByTestId('prop-asof')).toHaveText('As of Mon Nov 9');
  await expect(first.getByTestId('prop-asof')).toHaveAttribute('title', /Written Nov 9/);
});

test('heads-up notes sit under the queue as reading matter, with nothing to press', async ({ page }) => {
  await page.goto('/decisions');
  const notes = page.getByTestId('notes');
  await expect(notes.locator('.note-row')).toHaveCount(2);
  await expect(notes).toContainText('Margin is back to zero');
  await expect(notes).toContainText('Plan keeper · as of Mon Nov 9');
  await expect(notes.getByRole('button')).toHaveCount(0);
  await page.goto('/decisions?scenario=fresh');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Decisions');
  await expect(page.getByTestId('notes')).toHaveCount(0);
});

test('what the desk cleared from the queue sits in a closed fold with each reason, and only when there is something', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/decisions');
  const fold = page.getByTestId('cleared');
  await expect(fold.locator('summary')).toContainText('Cleared overnight');
  await expect(fold.locator('summary .chip')).toHaveText('4');
  await expect(fold.locator('[data-cleared]').first()).toBeHidden();
  await fold.locator('summary').click();
  await expect(fold.locator('[data-cleared]')).toHaveCount(4);
  const first = fold.locator('[data-cleared="d_20261109051000_cc01"]');
  await expect(first.getByTestId('cleared-next')).toHaveCount(0);
  await expect(first).toContainText('Sell ACME to harvest the loss');
  await expect(first).toContainText('Your ACME plan already times this sale for Nov 13, so a second proposal would double it.');
  await expect(first).toContainText('Tax desk · cleared Today, 8:10 AM ET');
  await expect(fold.getByRole('button')).toHaveCount(0);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await page.goto('/decisions?scenario=fresh');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Decisions');
  await expect(page.getByTestId('cleared')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a replaced proposal says what became of it, and the open one is a tap away', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/decisions');
  const fold = page.getByTestId('cleared');
  await fold.locator('summary').click();
  const live = fold.locator('[data-cleared="d_20261109051000_cc03"]');
  await expect(live).toContainText('A newer proposal on the same subject replaced this one on Nov 9.');
  await expect(live.getByTestId('cleared-next')).toHaveAttribute('data-open', 'yes');
  await expect(live.getByTestId('cleared-next')).toContainText('It became “Buy $400 ACME”. Waiting in your queue.');
  const ended = fold.locator('[data-cleared="d_20261109051000_cc04"]');
  await expect(ended.getByTestId('cleared-next')).toHaveAttribute('data-open', 'no');
  await expect(ended.getByTestId('cleared-next')).toHaveText('It became “Buy $300 ACME”. ACME is at $23.50, above the $18.00 to $22.00 zone this was written for.');
  await expect(ended.getByRole('link')).toHaveCount(0);
  await page.locator('.prop', { hasText: 'Trim $150 FTEC' }).first().click();
  await expect(page.getByTestId('detail').getByRole('heading', { level: 2 })).toHaveText('Trim $150 FTEC');
  await live.getByRole('link', { name: 'Open it' }).click();
  await expect(page).toHaveURL(/d=d_20261109140500_9747d0/);
  await expect(page.getByTestId('detail').getByRole('heading', { level: 2 })).toHaveText('Buy $400 ACME');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('snoozed proposals stay in sight in a closed fold that the chip opens', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/decisions?scenario=snoozed');
  await expect(page.locator('.ph-big b')).toHaveText('2');
  await expect(page.locator('.prop')).toHaveCount(2);
  const fold = page.getByTestId('snoozed');
  await expect(fold.locator('summary')).toContainText('Snoozed');
  await expect(fold.locator('summary .chip')).toHaveText('2');
  await expect(fold.locator('[data-snoozed]').first()).toBeHidden();
  await page.getByTestId('snoozed-chip').click();
  await expect(fold.locator('[data-snoozed]')).toHaveCount(2);
  const first = fold.locator('[data-snoozed]').first();
  await expect(first).toContainText('Trim $150 FTEC');
  await expect(first).toContainText('Waiting for Friday’s deposit.');
  await expect(first).toContainText('Plan keeper · back Tue Nov 10, 9:30 AM ET');
  await expect(fold.locator('[data-snoozed]').nth(1)).toContainText('Carries the snooze from the proposal it replaced.');
  await first.click();
  await expect(page).toHaveURL(/d=d_20261109130500_ea1ca9/);
  await expect(page.getByTestId('detail').getByRole('heading', { level: 2 })).toHaveText('Trim $150 FTEC');
  await expect(first).toHaveAttribute('aria-pressed', 'true');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  await page.goto('/decisions');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Decisions');
  await expect(page.getByTestId('snoozed')).toHaveCount(0);
  await expect(page.getByTestId('snoozed-chip')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('Decisions leads with one dated list of next steps, each with why, where it comes from and what would change it', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/decisions');
  const card = page.getByTestId('next-steps');
  await expect(card.locator('.card-head .chip')).toHaveText('3 dated');
  const dated = card.getByTestId('ns-dated').locator('[data-step]');
  await expect(dated).toHaveCount(3);
  const first = dated.first();
  await expect(first.locator('.stamp-day')).toHaveText('Nov 13');
  await expect(first.locator('summary')).toContainText('Sell 40 ACME to harvest the loss');
  await expect(first.locator('summary')).toHaveText('Nov 13Sell 40 ACME to harvest the lossto Nov 20Lab backs it');
  await expect(card.locator('.ns-lead')).toHaveCount(0);
  await expect(first.locator('.ns-more')).toBeHidden();
  await first.locator('summary').click();
  await expect(first.locator('.ns-more')).toContainText('A sale below your cost books the loss against this year’s taxes.');
  await expect(first.locator('.ns-more')).toContainText('Your ACME plan, version 2, approved Nov 6.');
  await expect(first.locator('.ns-more')).toContainText('No longer worth doing if ACME is back above your cost.');
  await expect(first.locator('.ns-more')).toContainText('From Individual. Lots: Specific Shares, highest-cost lots.');
  await expect(first.getByTestId('ns-test')).toContainText('Tax-loss harvesting. Helped: ahead in 70% of 120 start months. The lab’s test backs this.');
  await expect(first.getByRole('link', { name: 'See the test' })).toHaveAttribute('href', '/strategies/lib-harvest');
  await expect(first.getByRole('link', { name: 'Open it in the queue' })).toHaveCount(0);
  await expect(first.getByRole('button')).toHaveCount(0);
  const standing = card.getByTestId('ns-standing');
  await expect(standing.locator('> summary')).toContainText('Standing');
  await expect(standing.locator('> summary .chip')).toHaveText('5');
  await expect(standing.locator('[data-step]').first()).toBeHidden();
  await standing.locator('> summary').click();
  await expect(standing.locator('[data-step]')).toHaveCount(5);
  const unbacked = standing.locator('[data-step^="agreed:"]');
  await expect(unbacked.getByTestId('ns-backed')).toHaveText('Lab disagrees');
  await expect(unbacked.getByTestId('ns-backed')).toHaveClass(/watch/);
  await expect(standing.locator('[data-step="plan:ACME:add"] summary')).toContainText('On a pullback below $2.60');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  const mine = dated.nth(1);
  await mine.locator('summary').click();
  await mine.getByRole('link', { name: 'Open it in the queue' }).click();
  await expect(page).toHaveURL(/d=d_20261109130500_168372/);
  await expect(page.getByTestId('detail').getByRole('heading', { level: 2 })).toHaveText('Route deposit to $180 VXUS');
  await page.goto('/decisions?scenario=fresh');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Decisions');
  await expect(page.getByTestId('next-steps')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('his own pass reason sits in the list in his words, with how its date was read and a way to take it off', async ({ page }) => {
  const errors = watchErrors(page);
  const { readFileSync } = await import('node:fs');
  const list = JSON.parse(readFileSync(new URL('../src/fixtures/decisions.next-steps.json', import.meta.url), 'utf8'));
  let removed = null;
  await page.route('**/api/decisions/next-steps?*', (route) => route.fulfill({ json: removed ? { ...list, count: 2, items: list.items.filter((s) => !s.id.endsWith(removed)) } : list }));
  await page.route('**/api/decisions/next-steps/*', async (route) => {
    expect(route.request().method()).toBe('DELETE');
    expect(route.request().postData()).toBeNull();
    removed = route.request().url().split('/').pop();
    await route.fulfill({ json: { removed } });
  });
  await page.goto('/decisions');
  const card = page.getByTestId('next-steps');
  const mine = card.locator('[data-step="you:s_20261109150000_32032d_4835"]');
  await expect(mine.locator('.stamp-day')).toHaveText('Dec 7');
  await expect(mine.locator('summary')).toContainText('I’ll trim FTEC after Dec 6, once the year’s gains are clear.');
  await expect(mine.locator('summary')).toContainText('Your words · to Dec 31');
  await expect(mine.getByTestId('ns-backed')).toHaveCount(0);
  await mine.locator('summary').click();
  await expect(mine.getByTestId('ns-read')).toContainText('Read as Dec 7 to Dec 31, from “after Dec 6”.');
  await expect(mine.locator('.ns-more')).toContainText('Your words on Nov 9, when you passed on “Trim $90 FTEC”.');
  await expect(mine.getByTestId('ns-test')).toHaveCount(0);
  await mine.getByTestId('ns-undo').click();
  await expect(card.getByTestId('ns-msg')).toHaveText('Taken off your next steps.');
  await expect(mine).toHaveCount(0);
  await expect(card.locator('.card-head .chip')).toHaveText('2 dated');
  expect(removed).toBe('s_20261109150000_32032d_4835');
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
  expect(errors).toEqual([]);
});

test('a pass whose reason became a step says so, and Undo takes it back', async ({ page }) => {
  const { readFileSync } = await import('node:fs');
  const list = JSON.parse(readFileSync(new URL('../src/fixtures/decisions.next-steps.json', import.meta.url), 'utf8'));
  const step = list.items.find((s) => s.source === 'you');
  let undone = 0;
  await page.route('**/api/decisions/*/pass', (route) => route.fulfill({ json: { ...record({ status: 'passed', title: 'Buy $400 ACME' }), step } }));
  await page.route('**/api/decisions/next-steps/*', async (route) => {
    undone += 1;
    await route.fulfill({ json: { removed: 's_20261109150000_32032d_4835' } });
  });
  await page.goto('/decisions');
  await page.getByRole('textbox', { name: 'One-line reason' }).fill('I’ll trim FTEC after Dec 6, once the year’s gains are clear.');
  await page.getByRole('button', { name: 'Pass and log it' }).click();
  await expect(page.locator('.act-note').first()).toContainText('Passed and logged');
  const added = page.getByTestId('step-added');
  await expect(added).toContainText('Added to your next steps: “I’ll trim FTEC after Dec 6, once the year’s gains are clear.”, read as Dec 7 to Dec 31, from “after Dec 6”.');
  await added.getByRole('button', { name: 'Undo' }).click();
  await expect(page.getByTestId('step-added')).toHaveCount(0);
  await expect(page.locator('.act-note').first()).toContainText('Taken off your next steps.');
  expect(undone).toBe(1);
});

test('a pass that became no step says nothing more, and a step that already left is said plainly', async ({ page }) => {
  await page.route('**/api/decisions/*/pass', (route) => route.fulfill({ json: record({ status: 'passed', title: 'Buy $400 ACME' }) }));
  await page.route('**/api/decisions/next-steps/*', (route) => route.fulfill({ status: 409, json: { detail: 'That step already left the list.' } }));
  await page.goto('/decisions');
  await page.getByRole('textbox', { name: 'One-line reason' }).fill('Not on margin');
  await page.getByRole('button', { name: 'Pass and log it' }).click();
  await expect(page.locator('.act-note').first()).toContainText('Passed and logged');
  await expect(page.getByTestId('step-added')).toHaveCount(0);
  const card = page.getByTestId('next-steps');
  await card.getByTestId('ns-standing').locator('> summary').click();
  const mine = card.locator('[data-step="you:s_20261109150000_632595_d3af"]');
  await expect(mine.locator('summary')).toContainText('Your words');
  await mine.locator('summary').click();
  await mine.getByTestId('ns-undo').click();
  await expect(card.getByTestId('ns-msg')).toHaveText('It had already left your next steps.');
});

// ---------- every page ----------
test('every page says what it is in one line and where to go next', async ({ page }) => {
  for (const r of ROUTES) {
    await page.goto(r.path);
    await expect(page.getByRole('heading', { level: 1 }), r.path).toHaveText(r.h1);
    const guide = page.getByTestId('guide');
    if (r.h1 === 'Lost in orbit') continue;
    await expect(guide, r.path).toBeVisible();
    expect((await guide.innerText()).length, r.path).toBeGreaterThan(30);
    await expect(page.getByTestId('guide-next'), r.path).toHaveText(/^Next: /);
  }
});

test('the next links chain from the Bridge through the desk and back', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('guide')).toContainText('The whole desk at a glance');
  await page.getByTestId('guide-next').click();
  await expect(page).toHaveURL(/\/decisions$/);
  await page.goto('/research');
  await page.getByTestId('guide-next').click();
  await expect(page).toHaveURL(/\/research\/opportunities$/);
  await expect(page.getByTestId('guide')).toContainText('A ranked list of what is worth buying or watching');
  await page.getByTestId('guide-next').click();
  await expect(page).toHaveURL(/\/decisions$/);
});

test('an older desk note gets the Held up legend above it, once', async ({ page }) => {
  const LIB = JSON.parse(readFileSync(new URL('../src/fixtures/lab.library.json', import.meta.url), 'utf8'));
  await page.route('**/api/lab/library*', (route) => route.fulfill({ json: { ...LIB, note: 'Every result is out of sample.' } }));
  await page.goto('/strategies');
  const lib = page.getByTestId('library');
  await expect(lib.getByTestId('lib-legend')).toHaveText('Held up means it beat its benchmark on years it was never tuned on, by more than luck allows across everything tried. The last two years are held back.');
  await expect(lib.getByTestId('lib-note')).toHaveText('Every result is out of sample.');
  await expect(lib.getByText(/Held up means/)).toHaveCount(1);
  await page.unroute('**/api/lab/library*');
  const { benchmarks, ...older } = LIB;
  expect(benchmarks.length).toBeGreaterThan(1);
  await page.route('**/api/lab/library*', (route) => route.fulfill({ json: older }));
  await page.goto('/strategies');
  await expect(page.getByTestId('library').locator('.lib-row').first()).toBeVisible();
  await expect(page.getByTestId('lib-benchmarks')).toHaveCount(0);
});

test('a library of 60 stays short: three rows a kind with counts, the rest behind Show all', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/strategies?scenario=big');
  const lib = page.getByTestId('library');
  await expect(lib.locator('.card-head .chip')).toContainText('59 of 61 tested');
  await expect(lib.locator('.lib-group')).toHaveCount(3);
  for (const kind of ['classic', 'practical', 'novel']) await expect(lib.locator(`.lib-group[data-kind="${kind}"] .lib-row`)).toHaveCount(3);
  await expect(lib.locator('.lib-group[data-kind="classic"] .lib-head')).toContainText('24 tested · 4 held up');
  await expect(lib.locator('.lib-row').getByTestId('lib-bench')).toHaveCount(9);
  await expect(lib.locator('.lib-group[data-kind="novel"] .lib-row').first().getByTestId('lib-bench')).toHaveText('Measured against small caps (IWM)');
  const short = await lib.boundingBox();
  const view = page.viewportSize();
  expect(short.height / view.height).toBeLessThanOrEqual(view.width < 600 ? 2.4 : 1.6);
  await lib.locator('.lib-group[data-kind="classic"]').getByRole('button', { name: 'Show all 24' }).click();
  await expect(lib.locator('.lib-group[data-kind="classic"] .lib-row')).toHaveCount(24);
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);

  await page.goto('/?scenario=big');
  const door = page.getByTestId('morning').locator('[data-door="strategies"]');
  await expect(door).toContainText('59 of 61');
  await expect(door).toContainText('10 held up out of sample');
  const b = await overflow(page);
  expect(b.scroll).toBeLessThanOrEqual(b.view);
  expect(errors).toEqual([]);
});

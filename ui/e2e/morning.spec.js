import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { MONDAY_MIDDAY, ROUTES, overflow, watchErrors } from './helpers.js';

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
  await expect(lib).toContainText('Every result is out of sample.');
  await expect(lib.locator('.lib-group')).toHaveCount(3);
  await expect(lib.locator('.lib-group h3')).toHaveText(['Old and tested', 'Practical', 'Novel and creative']);
  const classic = lib.locator('.lib-group[data-kind="classic"]');
  await expect(classic.locator('.lib-row')).toHaveCount(5);
  await expect(classic.locator('.lib-row').first()).toContainText('12-1 momentum');
  await expect(classic.locator('.lib-row').first()).toContainText('Held up');
  await expect(classic.locator('.lib-row').first()).toContainText('+3.1 pts a year');
  await expect(classic.locator('.lib-row').first()).toContainText('Ahead by 3.1 points a year out of sample, more than luck explains across 212 tries.');
  await expect(classic.locator('.lib-row').first()).toHaveAttribute('href', '/strategies/momentum-12-1');
  await expect(lib.getByTestId('lib-retest')).toHaveCount(1);
  await expect(classic.locator('.lib-row', { hasText: 'Dual momentum' }).getByTestId('lib-retest')).toHaveText('Retest pending');
  await classic.getByRole('button', { name: /Show all/ }).click();
  await expect(classic.locator('.lib-row[data-verdict="fell_short"]').first()).toContainText('Fell short');
  await expect(lib.locator('.lib-row[data-verdict="waiting"]')).toContainText('Waiting');
  await expect(lib.locator('.lib-row[data-verdict="waiting"]')).not.toHaveAttribute('href');
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
  await expect(top).toContainText('1 of these has no written case yet.');
  await expect(top).toContainText('No risk check on file yet, so sizes use the Moderate band');
  await expect(top).toContainText('It is a sort, not a forecast.');
  const first = page.getByTestId('ideas').locator('[data-idea="QUAL"]');
  await expect(first).toContainText('Worth buying now');
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
  await page.getByTestId('ideas').locator('summary').click();
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
  await expect(fold.locator('summary')).toContainText('Not now');
  await expect(fold.locator('summary .chip')).toHaveText('1');
  await expect(fold.locator('.idea')).toBeHidden();
  await fold.locator('summary').click();
  await expect(fold.locator('[data-idea="ACME"]')).toBeVisible();
  await fold.locator('summary').click();
  await expect(fold.locator('.idea')).toBeHidden();
  const o = await overflow(page);
  expect(o.scroll).toBeLessThanOrEqual(o.view);
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
  await ideas.locator('summary').click();
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
  await expect(fold.locator('summary .chip')).toHaveText('2');
  await expect(fold.locator('[data-cleared]').first()).toBeHidden();
  await fold.locator('summary').click();
  await expect(fold.locator('[data-cleared]')).toHaveCount(2);
  const first = fold.locator('[data-cleared]').first();
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

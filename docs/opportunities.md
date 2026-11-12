# Buying opportunities

One ranked list of things worth buying or watching, in his holdings and outside them. Advice only: nothing here trades, writes a decision record or touches a broker.

## What owns what

| Piece | Where |
|---|---|
| Package | `desk/opportunities/` (list, sizes, night job, route, job) and `tests/opportunities/` |
| Route prefix | `/api/opportunities` |
| Tables | None. The list is built on each read from the engine's and the desks' tables |
| Files | `data/run/opportunities/night.json` (last night's record) and `cases.json` (cases written for rows the scanner did not flag) |
| Model calls | None of its own. The night job runs the existing Discount cases and Scout desks through `desk.agents`, so every call still goes through `claude -p` and the desks' switches, guard and weekly caps |

## Where a row comes from

| Source | Meaning | Written by |
|---|---|---|
| `scanner` | A discount scanner hit in the last 5 days | `python -m desk.engine discounts` |
| `case` | A written case: buy, wait or avoid. For a scanner hit it lives in the engine's `discount_cases`; for a row on sale with no hit it lives in `cases.json` and counts for 7 days | Discount cases desk |
| `research` | A held name's latest research note. It is the row's written analysis when there is no case or Scout idea | Research desk, the nightly holdings pass |
| `scout` | A Scout buy idea from the last 45 days: open in the queue, or turned back for cash, the margin debit, a hold-off note or a no-buy window | Scout, checked by the Skeptic |
| `standing` | On sale by the numbers with no fresh hit: at least 10% under the 52-week high and 1.5 of its usual monthly swings, or in the cheapest fifth of its own 5 years on earnings and 5% under the high | Built on read |
| `near` | Not on sale. Shown only to fill the list to 3 rows, with the zone where it would get interesting | Built on read |

Names come from the scanner's universe (held, watchlist, quality list) plus anything Scout proposed.

## What each row says

| Part | Rule |
|---|---|
| Why now | The written case or Scout's thesis when there is one. Otherwise the numbers: the hit, the drop, how many monthly swings that is, and the 200-day trend |
| Entry zone | The latest price down to one monthly swing lower (63-session volatility × √21, the same swing Stock plans use). For `near` rows, one to two swings under that price |
| Size | A starter slice: 1% of the portfolio for a single stock, 2.5% for a fund. Never more than the room under the caps, never more than free cash, never on margin |
| What would make it wrong | The case's risks, or the Skeptic's counter-case, or Scout's bear case. Plus a price: two monthly swings under the latest price. Plus earnings inside 14 days |
| Stance | `buy`: a written case or Scout says buy, or a holding's research note says add, and nothing blocks it. `watch`: the case says wait, the Skeptic flagged it, a cap, rule or no-buy window blocks it, the holding's research note says anything but add, or it is not on sale. `screen`: cheap by the numbers, no written case yet |

A written case that says avoid drops the name from the rows and lists it under `passed` with the reason.

## Holdings and their research note

| Note says | Row |
|---|---|
| `add` | A buy, on the list even when the name is not on sale |
| `hold` or `watch`, name on sale | A watch: "You already hold this; the analysis says hold, not add". Why now is the note's verdict line, what would make it wrong is its bear case |
| `hold` or `watch`, name not on sale | Not on the list |
| `trim` or `avoid` | A watch: "your research note says trim" |
| Anything but `add`, and a written case says buy | A watch: "the case says buy, but your research note says hold" |
| The desk could not tell what the holding is | The note is ignored |

## Which price, which day

| Part | Rule |
|---|---|
| Price | The newest the desk holds for that name: an official close, else a provisional close (`closes_provisional`), else the latest live quote (`quotes_live`, Finnhub rows only). The drop, the swings, the zone and the off-below price are all worked out at that price |
| `price_source` | `close`, `provisional` or `quote`; `price_as_of` is its day and `price_at` the quote's time |
| Day of the desk | `as_of` and `asof` come from `desk.engine.asof`, the same answer as `/api/asof`. The list never reads its own clock for the day |
| Analysis day | `analysis_as_of`: the scanner hit's day for a hit or a written case, the record's day for a Scout idea, the price day for rows worked out on read. `since_analysis_pct` is the move since then |
| `as_of_words` | One line for the row: "Priced at the Wed Nov 11 close, provisional until the official close lands. The written case is from Mon Nov 9; the price is 3.1% lower since." |
| Older prices | Live quotes are only pulled for held names, SPY and the yardsticks. Other closes come from the hourly price backfill, which has a stock's or ETF's close the same evening and a mutual fund's later. A row priced before the newest day gets `price_behind` and says so in `as_of_words`; `prices.older` lists them |

## Worth buying, not in the queue

Opportunities are not queue items, and since the funding check the desks propose no buy while a margin debit is open or ready cash is short. A buy-rated row still shows, with `not_queued` saying why in one line.

| Case | `stance` | `not_queued` |
|---|---|---|
| Margin debit open | `buy`, "Worth buying once cash is free" | "Pay the margin debit first: $X is open, so no buy goes to the queue." |
| No ready cash | `buy` | "Needs more ready cash than there is: $X is ready today." |
| Scout buy turned back for cash, cash is free again | `buy`, "Worth buying now" | "Scout's idea was turned back on Nov 11: … Nothing has proposed it again since." |
| Scout buy turned back by a hold-off note or a no-buy window | `watch` | The record's own reason |
| Open Scout idea | `buy` | `null`, and `queued` is true |

Turned-back Scout buys are read from the decision journal (`status=rejected`, `origin=scout`). Any other rejection, such as numbers that did not match the brief, stays off the list.

## Caps a size respects

| Cap | Source |
|---|---|
| Single-stock band | The lower of the `single_stock_band` rule (or the satellite cap) and the risk band's single-stock max |
| All single stocks together | The lower of `opportunity.satellite_cap_pct` and the risk band's speculative max. Conviction holds are not counted |
| Conviction hold | Its own band only, and never on margin |
| No risk check on file | The Moderate band (5% and 5%), and the payload says so in `profile.note` |
| Planned loss sale | No buys of that name inside the window from Stock plans |
| Everything else | The size is run through Preflight, the same checker the Decisions queue uses. A red Concentration, Plan rules or Wash sales lamp sets the size to 0 and shows the lamp's words |
| Cash | Ready cash and the margin debit are the desk's own figures (`cash.ready`, `margin.debit`, the ones the Bridge shows). An open debit comes first: nothing is sized from cash. Then ready cash, then the next expected deposit after it clears the debit. With neither, size 0 and the room the caps would allow. A size the buying account cannot settle is 0 too |

## Order and groups

Every row has a `group`, and the list is sorted by it so the page leads with what could be bought.

| `group` | `group_label` | Rows |
|---|---|---|
| `buy` | Worth buying | Stance `buy` |
| `could` | Could become a buy | On sale and nothing rules it out: the case says wait, the Skeptic disagreed, or no case is written yet |
| `not_now` | Not now | A holding whose research note does not say add; a row a cap, rule, hold-off note or no-buy window blocks; a name that is not on sale and only fills the list |

Inside a group rows are sorted by score. The score is a sort key from 0 to 100: depth of the discount in monthly swings (up to 40), cheapness against its own history (±15), above or below the 200-day average (±8), a fresh hit (+10), a buy case (+25 × confidence), a wait case (−5), a Scout idea (+20 × confidence, −15 if flagged), a research note that says add (+15), a blocked size (−25), earnings inside 5 days (−5). It is not a forecast and has not been through the lab's gate; the payload's `method` says so.

The headline counts the groups: "Nothing rated a buy yet. 2 could become one, 9 not for now. Top: VGT, 12.4% under its high." The drop in the headline is the top row's `numbers.drop_from_high_pct`, the same figure as its first fact. When a written case is older than the row's price, the fact says both: "31.3% under its 52-week high at the latest price (31.9% when the case was written)", because the case's own sentence quotes the scanner's number from its day.

## The night job

`python -m desk.opportunities night`, job `opportunities-night`, overnight key 210 (after the portfolio pass), with 02:40 and 04:40 ET as fallback times.

| Step | Does | Skips when |
|---|---|---|
| Scan | Runs the discount scan | The scan is already current to the latest close |
| Cases | Runs the Discount cases desk on pending scanner hits | Nothing is pending, or the desk is off, guarded or over its cap |
| List cases | Asks the same desk for a case on each `screen` row (on sale, no written case, note or idea), best rank first | Every such row has one; six cases were already written tonight, scanner cases included; the desk stopped in the step before; it is between 05:30 and 09:00 ET |
| Scout | Runs Scout once | It had a good run in the last 35 days, or any counted run in the last 7 |

List cases goes through `run_discount_desk(discounts=ListSource(...), trigger="schedule", limit=n)`: the desk's own prompt, schema, switch, guard, lock and weekly allowance, with the hit built from the row's `numbers` in the scanner's shape. The cap is six cases a night across both steps (18 hours back). A row with a case is no longer a `screen`, so a second run pays for nothing.

Safe to start twice. It records the night in `data/run/opportunities/night.json` and ends with one JSON line for the morning alert: `{"ready": "6 buying opportunities, 2 rated a buy; 3 cases written overnight", "detail": "<the night's summary>"}` or `{"skipped": "why"}`. The count in `ready` is `buy` plus `could`; rows that are not for now are not called opportunities. The line is saved in `night.json`, and `desk.opportunities.ready(cfg)` returns that saved line for 18 hours, so the overnight page never lists two versions of it. Cases written overnight are counted once (both kinds, 18 hours back): `ready`, `night.json` `cases_written` and the summary's one sentence all use that count; a step's own note says "This run wrote N of M". The steps' own lines are also in the payload under `freshness.night_summary` and `freshness.night_steps`, because the overnight page only shows `ready` for a step that ended ok.

The list never waits for the night job. Rows without a case show as `screen` and `freshness.note` says how many.

## Payload

`GET /api/opportunities`. Field meanings are in the table below; `tests/opportunities/test_build.py` pins the keys.

| Field | Meaning |
|---|---|
| `as_of`, `built_at` | The desk's day; when this answer was built |
| `asof` | `day`, `words`, `status`, `provisional`, `expected_day`, `behind`, straight from `desk.engine.asof` |
| `prices` | `day` (newest price on the list), `words`, `older[]` (`symbol`, `price_as_of`, `held`) |
| `freshness` | `scanner_as_of`, `last_case_at` (newest case of either kind), `last_scout_at`, `night_run_at`, `night_status` (`ok`, `partial`, `waiting`), `night_summary`, `night_steps[]` (`step`, `status`, `note`), `note` |
| `headline`, `counts`, `note` | One line for the door; totals by stance and by group (`could`, `not_now`), held and outside, `with_case` and `written` (rows with a case, a Scout idea or a research note); the reason when the list is empty |
| `profile`, `cash`, `method` | The band sizes use; free cash, margin debit and next deposit; how rows are ranked |
| `rows[]` | `rank`, `symbol`, `name`, `kind`, `held`, `weight_pct`, `sources`, `source_label`, `stance`, `stance_label`, `group`, `group_label`, `why_now`, `facts`, `entry`, `size`, `wrong_if`, `invalid_below`, `case`, `decision_id`, `queued`, `not_queued`, `research_verdict`, `research`, `numbers`, `next_earnings`, `as_of`, `price_as_of`, `price_source`, `price_at`, `price_behind`, `analysis_as_of`, `since_analysis_pct`, `as_of_words`, `score` |
| `passed[]` | `symbol`, `name`, `reason` |

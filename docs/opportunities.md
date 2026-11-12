# Buying opportunities

One ranked list of things worth buying or watching, in his holdings and outside them. Advice only: nothing here trades, writes a decision record or touches a broker.

## What owns what

| Piece | Where |
|---|---|
| Package | `desk/opportunities/` (list, sizes, night job, route, job) and `tests/opportunities/` |
| Route prefix | `/api/opportunities` |
| Tables | None. The list is built on each read from the engine's and the desks' tables |
| Model calls | None of its own. The night job runs the existing Discount cases and Scout desks through `desk.agents`, so every call still goes through `claude -p` and the desks' switches, guard and weekly caps |

## Where a row comes from

| Source | Meaning | Written by |
|---|---|---|
| `scanner` | A discount scanner hit in the last 5 days | `python -m desk.engine discounts` |
| `case` | That hit has a written case: buy, wait or avoid | Discount cases desk |
| `scout` | An open Scout buy idea from the last 45 days | Scout, checked by the Skeptic |
| `standing` | On sale by the numbers with no fresh hit: at least 10% under the 52-week high and 1.5 of its usual monthly swings, or in the cheapest fifth of its own 5 years on earnings and 5% under the high | Built on read |
| `near` | Not on sale. Shown only to fill the list to 3 rows, with the zone where it would get interesting | Built on read |

Names come from the scanner's universe (held, watchlist, quality list) plus anything Scout proposed.

## What each row says

| Part | Rule |
|---|---|
| Why now | The written case or Scout's thesis when there is one. Otherwise the numbers: the hit, the drop, how many monthly swings that is, and the 200-day trend |
| Entry zone | Today's close down to one monthly swing lower (63-session volatility × √21, the same swing Stock plans use). For `near` rows, one to two swings under the close |
| Size | A starter slice: 1% of the portfolio for a single stock, 2.5% for a fund. Never more than the room under the caps, never more than free cash, never on margin |
| What would make it wrong | The case's risks, or the Skeptic's counter-case, or Scout's bear case. Plus a price: two monthly swings under today. Plus earnings inside 14 days |
| Stance | `buy`: a written case or Scout says buy and nothing blocks it. `watch`: the case says wait, the Skeptic flagged it, a cap, rule or no-buy window blocks it, the research note says trim, or it is not on sale. `screen`: cheap by the numbers, no written case yet |

A written case that says avoid drops the name from the rows and lists it under `passed` with the reason.

## Caps a size respects

| Cap | Source |
|---|---|
| Single-stock band | The lower of the `single_stock_band` rule (or the satellite cap) and the risk band's single-stock max |
| All single stocks together | The lower of `opportunity.satellite_cap_pct` and the risk band's speculative max. Conviction holds are not counted |
| Conviction hold | Its own band only, and never on margin |
| No risk check on file | The Moderate band (5% and 5%), and the payload says so in `profile.note` |
| Planned loss sale | No buys of that name inside the window from Stock plans |
| Everything else | The size is run through Preflight, the same checker the Decisions queue uses. A red Concentration, Plan rules or Wash sales lamp sets the size to 0 and shows the lamp's words |
| Cash | Free cash in the buying account first. With none, the next expected deposit after it clears any margin debit. With neither, size 0 and the room the caps would allow |

## Order

Buys first, then by score. The score is a sort key from 0 to 100: depth of the discount in monthly swings (up to 40), cheapness against its own history (±15), above or below the 200-day average (±8), a fresh hit (+10), a buy case (+25 × confidence), a wait case (−5), a Scout idea (+20 × confidence, −15 if flagged), a blocked size (−25), earnings inside 5 days (−5). It is not a forecast and has not been through the lab's gate; the payload's `method` says so.

## The night job

`python -m desk.opportunities night`, job `opportunities-night`, overnight key 210 (after the portfolio pass), with 02:40 and 04:40 ET as fallback times.

| Step | Does | Skips when |
|---|---|---|
| Scan | Runs the discount scan | The scan is already current to the latest close |
| Cases | Runs the Discount cases desk on pending hits | Nothing is pending, or the desk is off, guarded or over its cap |
| Scout | Runs Scout once | It had a good run in the last 35 days, or any counted run in the last 7 |

Safe to start twice. It records the night in `data/run/opportunities/night.json` and ends with one JSON line for the morning alert: `{"ready": "6 buying opportunities, 2 rated a buy"}` or `{"skipped": "why"}`. `desk.opportunities.ready(cfg)` returns the same line at any time.

The list never waits for the night job. Rows without a case show as `screen` and `freshness.note` says how many.

## Payload

`GET /api/opportunities`. Field meanings are in the table below; `tests/opportunities/test_build.py` pins the keys.

| Field | Meaning |
|---|---|
| `as_of`, `built_at` | The close the list is built on; when this answer was built |
| `freshness` | `scanner_as_of`, `last_case_at`, `last_scout_at`, `night_run_at`, `night_status` (`ok`, `partial`, `waiting`), `note` |
| `headline`, `counts`, `note` | One line for the door; totals by stance, held and outside; the reason when the list is empty |
| `profile`, `cash`, `method` | The band sizes use; free cash, margin debit and next deposit; how rows are ranked |
| `rows[]` | `rank`, `symbol`, `name`, `kind`, `held`, `weight_pct`, `sources`, `source_label`, `stance`, `stance_label`, `why_now`, `facts`, `entry`, `size`, `wrong_if`, `invalid_below`, `case`, `decision_id`, `research_verdict`, `next_earnings`, `as_of`, `score` |
| `passed[]` | `symbol`, `name`, `reason` |

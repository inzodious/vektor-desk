# Vektor Desk: product concept

Written November 7, 2026. This page says what the desk is for, how it gets used, and what it contains. The base decisions (TrueNAS, Tailscale only, read-only mirror of Escape Vektor, Claude Code CLI on the subscription, agents advise only) come from fin-dashboard's `docs/invest-desk.md` and are not reopened here.

Sibling documents own the detail:

| Topic | Owner |
|---|---|
| Phases, order, roadmap | `docs/project-plan.md`, `ROADMAP.md` |
| Hosting, mirror, deploy | `docs/architecture.md` |
| Agent desks, prompts, schedules, guardrails | `docs/agents.md` |
| Metric definitions and methods | `docs/statistics.md` |
| Layouts, visuals, mockups | `docs/design.md`, `mockups/` |

## Purpose

Escape Vektor answers "where is my money?" Vektor Desk answers "what should I do with the next dollar, and was the last decision any good?"

It is a decision instrument for one investor. Every buy, sell, rebalance or deliberate pass is checked against the plan before it happens, recorded with its reasoning, and scored afterwards against the plain default of following the plan. Research, statistics, dashboards and agents all exist to feed that loop.

**Why this framing.** The plan's biggest risks are not a lack of information. They are concentration in a single stock, margin-funded buys, and tax timing (wash sales, loss harvesting windows). Those are decision-time mistakes. A desk that shows more charts but does nothing at the moment of decision would be a nicer dashboard and nothing more. The desk earns its place by adding friction and evidence exactly when a trade is being considered, and by keeping score honestly afterwards, including on its own agents.

## Principles

1. **Decisions are the core object.** Every other area either feeds a decision (Research, Lab, Plan) or reports on decisions (Bridge, Flight record).
2. **The plan is the default.** Anything that departs from the plan has to state why, and is measured against what the plan would have done.
3. **The engine computes, agents argue, Joshua decides.** Numbers come from deterministic code. Agents read those numbers and write proposals. Nothing on the box can place a trade.
4. **Real data or none.** Positions come from the mirror and prices from a live feed. No estimated figures where a connection supplies real ones, and no placeholder numbers while waiting.
5. **Fast daily, deep on demand.** The daily check takes under three minutes on a phone. Research and analysis can be as deep as needed on a desktop.
6. **Warn, log, never scold.** The desk cannot stop a trade at Fidelity, so it does not pretend to. It shows the cost in dollars, records an override with its reason, and keeps the tone from Escape Vektor's tone sheet.
7. **Built for one.** No onboarding, blank slates or multi-user settings. Personal preferences live in versioned settings (`desk.yaml`), not in code, and personal figures never go in the repo.

## Scope

**In:** Fidelity Individual, HSA and 401(k) (the 401(k) once Empower is connected), stocks and ETFs/mutual funds, cash and margin balances, the plan in Escape Vektor's `plans` table, tax lots from a Fidelity export.

**Out for 1.0:** placing trades, options, crypto, intraday trading tools, anything other users could see, and writing back to Escape Vektor. Options and crypto can be revisited if he starts holding them.

## Areas

Five areas plus Settings, in the Escape Vektor pill nav on desktop and the phone dock on mobile.

| Area | Question it answers | Main contents |
|---|---|---|
| **Bridge** | What changed, and does anything need me? | KPI row, today's brief, decision queue, live holdings strip, alerts |
| **Research** | What do I know about this? | Dossiers per symbol and theme, watchlist, source library, filings and earnings calendar |
| **Decisions** | What am I doing and why? | Queue of proposals, Preflight, order tickets, decision journal, Flight record |
| **Plan** | What is the rulebook? | Target mix, deposit schedule, rules, tax calendar, FI projection and scenarios |
| **Lab** | What does the evidence say? | Compare, patterns, risk and statistics, saved boards |
| **Settings** | How is the desk configured? | Desk profile, agent status and run log, data freshness, token renewal date |

### Live tracking, one click away

Live tracking is not a separate page. Every symbol anywhere in the desk (a holding, a ledger row, a dossier, a proposal) is a chip that opens the **Symbol sheet**: live price and day move, position across accounts, cost basis and lots, plan target versus actual, latest dossier, open decisions, and upcoming events. The sheet closes on outside click or Escape, like every Escape Vektor popup.

Prices update near real time during market hours from the free Finnhub or Tiingo feed; outside hours they show the last close. Position values use mirrored shares times the live price. Shares only change when the mirror sees a new position, so an order ticket marked "placed" shows as pending until the next mirror confirms it.

### Bridge

- **KPI row:** portfolio value and day change, return versus benchmark for the selected period, plan drift (largest gap in points), single-stock share against its band, margin debit with its monthly interest in dollars, cash ready to invest, FI progress. Definitions belong to `statistics.md`.
- **Brief:** a short daily note from the plan keeper, in plain sentences: what moved, what drifted, what is due, what the queue holds. No wall of text; three to five lines.
- **Queue:** proposals and triggers waiting on him, each with approve, dismiss or snooze.
- **Holdings strip:** every holding as a live tile, sorted by value, each opening the Symbol sheet.
- **Alerts:** a rule about to be breached, a thesis invalidation trigger hit, a wash-sale window opening or closing, a tax deadline, a stale mirror.

### Research

- **Dossiers.** One per symbol or theme (for example nuclear, grid, space). Each holds a thesis, a bear case, a valuation range, key numbers from the engine, what would change the call, and dated sources. The research desk writes and refreshes them; Joshua can edit and add notes. Every claim links to its source.
- **Deep research on request.** Ask from any symbol or theme. The request runs overnight by default to save subscription usage, or now if he chooses.
- **Watchlist** with optional price and event triggers that land in the Bridge queue.
- **Source library.** Filings (SEC EDGAR), insider trades, 13F holders, earnings dates, macro series (FRED), saved articles. Web content is treated as data, never as instructions to an agent.

### Decisions

This is the heart of the desk.

- **Queue.** Agent proposals and his own drafts in one list.
- **Queue rule (2026-11-11).** The queue holds only what is true today. Checked on every read and by the night job `python -m desk.decisions tidy`; nothing is deleted, each item that leaves goes to the journal as `expired` or `logged` with a plain `status_reason`.

  | Rule | What happens |
  |---|---|
  | Subject and "as of" | Every proposal has a `subject` (stable across runs, scoped to its desk; derived when missing: `buy:SYM`, `sell:SYM`, `hold_off:SYM`, `hold_off:general` with no symbol, `next-deposit` for a deposit route) and an `as_of` (the day of its facts; the creation time when missing) |
  | Replace | A newer desk proposal on the same subject from a later run expires the older one (`replaced_by` points to it), including an older one filed without a subject that it stands for. A snooze carries over, and the new one says so in `status_reason`. One run never replaces its own proposals; his drafts are never replaced. Only a proposal that passes the checks below replaces anything: one that is already out of date when it arrives expires at once with its own reason (the record returned to the desk has `status` `expired`) and the older one stays |
  | Window passed | `expires` is behind us |
  | Price outside its zone | Latest price is outside `price_min` to `price_max`. With no zone, a desk trade expires once the price is more than 10% from the price it was written at |
  | Cash gone | A ready-cash figure newer than the proposal is below `needs_cash_usd` (a cash-funded buy uses its amount) |
  | Unknown is not stale | No price, or a cash figure the engine marks `stale`, `mismatch` or `insufficient_history`, never expires anything. A rolled-forward or inferred figure (`pro_forma`, `trimmed`, `modelled`) counts, and the reason says "estimated" |
  | Pulls against his plan | The night job and the `sync` job (08:10 and 17:10 ET) also clear a desk proposal that fails `desk.agents.checks.queue_problem`: a sale his approved plan already times, a sale to pay margin his plan already repays, a second margin hold-off beside the Plan keeper's. No model call; the returned sentence is the reason. His own drafts are never cleared |
  | Cleared, and why | `GET /api/decisions/cleared?days=2` lists what the rule removed, newest first, each with `status_reason`, `check` (`window`, `price`, `cash`, `replaced`, `plan`), `cleared_at` and `successor` |
  | Nothing leaves silently | Every proposal is in exactly one place: `items` of `GET /api/decisions/queue`, its `snoozed_items` (hidden until `snoozed_until`), or the journal. In the journal it carries a `status_reason`, or the event of his own approve, dismiss or pass. A replaced row in the cleared list has `successor`: the proposal at the end of its chain, with its status, reason and `outcome` (one plain sentence for every ending, including his own approve, agree, dismiss or pass and when), so a chain that ended with nothing says why |
  | Heads-up notes | `memo` and `alert` from a desk need no decision: stored as `logged`, listed by `GET /api/decisions/notes` (latest per subject), never in the queue. `hold_off` stays a queue item |
- **Preflight.** Every candidate trade runs a checklist before an order ticket is made, shown as cockpit lights:
  - concentration after the trade versus the single-stock band,
  - plan drift after the trade,
  - funding source, with margin interest per month in dollars if margin is used,
  - wash-sale conflicts across Individual, HSA and 401(k),
  - tax lots to use and the realized gain or loss,
  - any plan rule it breaks (no new single stocks, no buying on margin, and so on).
  A red light does not block. Going ahead records an override with his one-line reason.
- **Order ticket.** Account, symbol, side, quantity or amount, order type, lots for Specific Shares. Copy-ready for Fidelity. He marks it placed; the mirror confirms the fill.
- **Decision record.** Created for every action and every deliberate pass. Holds: type, symbol, amount, account, funding, origin (Joshua or a named desk), thesis, bear case, invalidation trigger, horizon, confidence, Preflight result and any overrides, the desk settings in force, tax impact, status, and scores.
- **Flight record.** Each decision is scored at 30, 90 and 365 days against the default of putting the same money into the plan mix on the same day. Summaries by origin (Joshua, each desk), by type, and for overrides versus clean Preflights. If a desk cannot beat the default after six months, it is switched off.

### Plan

- Target mix and bands, read from Escape Vektor's plan, with drift per holding.
- Deposit schedule: where the next deposit should go to close drift, ready as a proposal on payday.
- Rules, editable and versioned. Every change to a rule is itself a decision record.
- Tax calendar: harvest candidates, wash-sale windows, year-end deadlines, and which lots to sell.
- **Stock plans.** One versioned plan per holding. The desk drafts, he edits and approves; only approved plans reach the calendar, alerts and the daily brief. Orders still go through Preflight tickets.

| Field | Holds |
|---|---|
| `role` | core, conviction, satellite or exit |
| `thesis`, `exit_conditions`, `tax_notes`, `catalysts`, `next_review` | The why, what would end it, and what is coming |
| `weight_band` | `{min_pct, max_pct}`; falls back to the conviction hold's band |
| `add_rule`, `trim_rule` | Price zones, a monthly cap, deposits only. Margin is never an option |
| `steps` | Dated or conditional: add, trim, hold, review, harvest, sell, repay, other. A harvest carries its lots and a 31-day no-buy window |

| Endpoint | Does |
|---|---|
| `GET /api/decisions/plans` | Latest version per symbol, with the approved one alongside when the latest is a draft |
| `GET /api/decisions/plans/{symbol}` | The plan and its version history; `/versions/{n}` reads one |
| `PUT /api/decisions/plans/{symbol}` `{plan, approve?}` | Saves his edit as a new draft, or approves it in the same call |
| `POST /api/decisions/plans/{symbol}/approve` `{version?}` | Approves the latest draft |
| `POST /api/decisions/plans/{symbol}/discard` | Drops the latest draft |
| `POST /api/decisions/plans/{symbol}/steps/{id}/done` `{on?, undo?}` | Marks a step done by hand; broker fills and a cleared margin debit mark steps done on their own |
| `GET /api/decisions/plan-steps?days=` | Approved steps live today or coming up, plus symbols under a no-buy window |

The plan desk writes through `desk.decisions.plans.save_draft`. It never changes an approved version, waits when his own draft is unapproved, and carries his steps into its drafts untouched.
- **Next steps (2026-11-13).** One ordered list of what to do next across his holdings and deposits: `GET /api/decisions/next-steps?days=90` returns `{as_of, days, count, items, standing, readings}`. `items` are dated and sorted by date; `standing` has no date. Nothing here is a new record: the list is read from what he already approved, agreed to or set.

  | Source | Row |
  |---|---|
  | Approved stock plan step | Its text, window and lots. A step due later than `days` is left out; an undated step goes to `standing` with its `when` |
  | Expected deposit | The next one says what it does: it pays the margin debit (a plan repay step, which then has no row of its own, or a margin note he agreed to), follows an approved deposit route, points at a route waiting in the queue, or says nothing is planned yet. A deposit that is late is never listed |
  | Desk note he agreed to | In `standing` for 30 days. A margin note ends when the debit reads zero |
  | Rule | `no_margin_buys` and `no_new_single_stocks`, in `standing` |
  | His own words | A reason he types when he passes on a proposal. See the table below |
  | No-buy window | One `standing` row per symbol while a harvest step holds buys back |

  | Field | Holds |
  |---|---|
  | `text`, `detail` | What he does, in one line; account and lots when they matter |
  | `why`, `basis` | One sentence of reason; where the row comes from ("Your ABCD plan, version 2, approved Nov 9.") |
  | `changes_if` | What would change or retire it |
  | `evidence`, `backed` | The strategy library row it leans on: `{row, title, sentence, verdict, tested_at, stance, reading, words}`. Only the row id is fixed in code; the rest is read from the lab each time. `backed` is the reading, or null with no evidence |
  | `source`, `ref` | `plan`, `deposit`, `agreed` or `rule`, with the ids behind it |
  | `read`, `undo` | Only on a row from his own words: the date read from them (`{date, until, phrase}`), shown beside his sentence so a wrong reading is visible, and the call that takes the row off the list |
  | `status`, `completes` | `open`, `partial`, `upcoming` or `waiting`; who can tell it is done: `broker` (a fill), `desk` (a figure) or `you` |

  | Lab result | `reading` | `words` |
  |---|---|---|
  | Held up, or a deposit rule ahead in most start months | `yes` | The lab's test backs this. |
  | Inside the noise | `no_edge` | The lab's test shows no clear edge either way. |
  | Fell short, or behind in most start months | `no` | The lab's test does not back this. |
  | Not run yet, could not be judged, or measured before a lab fix | `untested` | The lab has not judged this yet. |

  | His words when he passes | What happens |
  |---|---|
  | A date ("after Dec 6", "on Nov 18", "by Dec 15", "in January", "next week") | A step is written at once with `source` `you`: his sentence unchanged, the symbol and kind of the proposal he passed (a sale whose reason mentions harvesting or tax losses is a harvest), and the date read by plain parsing. No model call. "After Dec 6" opens Dec 7. With no end given the window is 30 days, or to year end for a harvest. The pass response carries the row as `step` |
  | No date, but intent ("I'll wait for earnings") | An undated row in `standing` with his sentence |
  | Anything else, a date already past, or a bare fraction such as 1/2 | Nothing. The reason stays in the journal |
  | Passes from the last 60 days | Read the same way on the next read of the list, once per record |
  | Afterwards | A fill at the broker completes it. A window that ends without one retires it. Both are written on the proposal he passed (`step_done`, `step_retired`). An approved plan step for the same symbol and side hides it. `DELETE /api/decisions/next-steps/{id}` takes it off for good |
  | For the desks | His dated steps are part of `open_steps`, so a desk proposal that pulls against one is cleared by the same plan check |

  A row with `stance` `against` cites a test of the opposite (borrowing to buy a dip, for the no-margin rule), so its reading is flipped. A step the lab does not back stays on the list and says so; it is his to change.
- FI projection: the path to the FI number at current contributions, with scenarios (contribution changes, return assumptions, a drawdown at a bad time). Lines and bars only, no area fills.

### Lab

- **Compare.** Pick two to five items (holdings, funds, accounts, the whole portfolio, the plan default, a benchmark, a set of decisions) and a period. Shows return, volatility, drawdown, correlation, expense ratio and, for funds, holdings overlap. Overlap matters here because a broad index fund and a tech fund share many top holdings.
- **Patterns.** Two kinds. Market patterns for holdings and watchlist (seasonality, drawdown and recovery, correlation shifts). And his own behavior: how buys made right after a sharp drop, off-schedule buys, or margin buys did against scheduled plan buys. The investor is a subject of analysis, not just the portfolio.
- **Risk and statistics.** Concentration, factor and sector exposure, scenario shocks, margin stress (what price move triggers a call). Methods are in `statistics.md`.
- **Saved boards.** Any Lab view can be pinned as a board with its filters and period, so recurring questions are one click.

### Settings

- **Desk profile:** risk band (from the risk questions), industry focus, satellite cap (share allowed outside the plan mix), growth versus income tilt, tax preferences (harvest threshold, avoid short-term gains), horizon. Stored in `desk.yaml`; every proposal records the profile version it used.
- **Editing without SSH.** Every profile change goes through the API, which rewrites only the touched section of `desk.yaml` and keeps the old file as `desk.yaml.bak`. The first profile is made by `POST /api/decisions/profile/init` (offered as `init` in `GET /profile/status` while there is none). Messages to him never name a file path or a command.

| Endpoint | Does |
|---|---|
| `PATCH /api/decisions/profile` `{changes}` | Deep-merges sections listed in `GET /profile` → `editable`; `risk_level` is refused |
| `GET /api/decisions/convictions` | `{items, suggested}`; each item has its band, weight and status (inside, above, below) |
| `PUT /api/decisions/convictions/{symbol}` | Adds or updates a conviction hold; missing band values come from the risk band |
| `DELETE /api/decisions/convictions/{symbol}` | Removes it |

- **FI goal.** `fi` in the profile (`number_usd`, or `yearly_spend_usd` × `multiple`; `target_age` + `birth_date`, or `target_date`) is the fallback when Escape Vektor has no FI goal. `desk.decisions.profile.fi_goal(data)` returns it in the engine's shape.
- **Desks on (2026-11-11).** Research, Scout, Strategy, Discounts and Filings are on by default, and a one-time pass switched them on in an existing `desk.yaml` (kept as `desk.yaml.bak`, recorded in `profile_passes`, shown in `GET /profile/status` → `notices`). A switch in Settings → Crew always wins.
- **Margin rate.** `margin.rate_pct` in the profile (default 12, a typical retail rate) so interest cost is never unknown; `profile.margin_rate(data)` returns `{rate_pct, source}` with source `default` or `profile`.
- **Conviction hold.** A held conviction position (rule `conviction_hold`) is exempt from the single-stock cap and has its own band instead. No adds above the ceiling, never on margin, and one friendly alert a week only while above it.
- Agent status: last run, next run, usage cost of each run in turns, on or off.
- Data freshness: last mirror, last price tick, last lot import.
- Claude token renewal date, with a reminder a month ahead.

## Loops

| Loop | When | Steps | Done when |
|---|---|---|---|
| **Daily check** | Morning, on the phone | Open Bridge, read the brief, clear the queue | Queue is empty or snoozed; under three minutes |
| **Payday** | Biweekly, after the deposit lands | Plan keeper proposes the split; Preflight; ticket; place at Fidelity; mark placed | Next mirror confirms; decision closes as "followed plan" |
| **Idea** | Whenever something catches his eye | Open or request a dossier; check Lab; draft a decision with thesis and invalidation; Preflight | A decision record exists, taken or passed |
| **Review** | Monthly, plus a quarterly deep one | Flight record by origin; overrides; desk scores; adjust rules or desk profile | Notes saved; any rule change logged as a decision |
| **Tax season** | Weekly, daily in December | Harvest candidates, lot picks, wash-sale windows | Year-end plan comes from the desk |

## What it borrows from Escape Vektor

| From Escape Vektor | In the desk |
|---|---|
| Jetset Lite look, Jetset Orbit tokens, light default and graphite dark | Same tokens and themes; the desk is denser, with more tables |
| Pill nav and phone dock | Five areas plus Settings |
| KPI cards, one main visual per page | Bridge KPI row; every Lab view opens with one chart |
| Cockpit gauges | Preflight lights, drift and band gauges |
| Stamped ledger | Trade and activity history, decision journal |
| Period picker and combo boxes | Every period and metric selector; no pill-button selectors |
| Symbol popup (`?s=SYM`) | Symbol sheet, opened from any chip |
| Ask terminal and robot | Console for talking to the desks and requesting research |
| Mission log and achievements | Flight record; a light discipline streak (days without an unlogged rule break), never a guilt counter |
| Tone sheet, shared Tip, popups close on outside click and Escape | Same rules |
| Sound (off by default) | Same cue set, optional |

What it drops: onboarding, blank-slate rules, friends, generic goals, Money and spending pages, and the "nobody inherits Joshua" principle. The desk is for Joshua by design.

## Alerts outside the app

Alerts that matter between visits (rule breach, invalidation trigger, wash-sale window, stale mirror, research ready) go to his phone. A free, self-hosted option on TrueNAS such as ntfy fits the no-paid-services rule; `architecture.md` makes the call.

## Success measures

1. Every trade at Fidelity matches a decision record (at least 95 percent coverage after three months).
2. No rule break goes through without a logged override.
3. The daily check takes under three minutes on a phone.
4. December's loss-sale plan comes from the desk.
5. After six months the Flight record says which desks beat "follow the plan", and the ones that do not are switched off.

## Priority tiers

The lead maps these to phases. Tier 1 delivers most of the value on its own.

| Tier | Contents |
|---|---|
| **1. Decide well** | Bridge KPIs and holdings strip, Symbol sheet with live prices, Plan (mix, drift, rules), Preflight, order tickets, decision records, lot import, plan keeper and tax desk |
| **2. Know more** | Research dossiers and source library, watchlist triggers, research and risk desks, Lab Compare and risk, phone alerts |
| **3. Learn** | Flight record scoring, Patterns (market and behavior), saved boards, scout desk, FI scenarios |

## Open questions

These have working defaults so nothing waits on them.

- **401(k) and HSA in Preflight:** default yes for wash-sale checks across all accounts, since a buy in any of them can disallow a loss.
- **Discipline streak:** default on, quiet, and reset only by an override without a reason.
- **Options and crypto:** default out until he holds them.

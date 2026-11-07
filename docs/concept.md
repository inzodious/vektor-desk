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
- FI projection: the path to the FI number at current contributions, with scenarios (contribution changes, return assumptions, a drawdown at a bad time). Lines and bars only, no area fills.

### Lab

- **Compare.** Pick two to five items (holdings, funds, accounts, the whole portfolio, the plan default, a benchmark, a set of decisions) and a period. Shows return, volatility, drawdown, correlation, expense ratio and, for funds, holdings overlap. Overlap matters here because a broad index fund and a tech fund share many top holdings.
- **Patterns.** Two kinds. Market patterns for holdings and watchlist (seasonality, drawdown and recovery, correlation shifts). And his own behavior: how buys made right after a sharp drop, off-schedule buys, or margin buys did against scheduled plan buys. The investor is a subject of analysis, not just the portfolio.
- **Risk and statistics.** Concentration, factor and sector exposure, scenario shocks, margin stress (what price move triggers a call). Methods are in `statistics.md`.
- **Saved boards.** Any Lab view can be pinned as a board with its filters and period, so recurring questions are one click.

### Settings

- **Desk profile:** risk level, industry focus, satellite cap (share allowed outside the plan mix), growth versus income tilt, tax preferences (harvest threshold, avoid short-term gains), horizon. Stored in `desk.yaml`; every proposal records the profile version it used.
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

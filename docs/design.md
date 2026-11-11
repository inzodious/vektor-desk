# Design: look, navigation and dashboards

How Vektor Desk looks and behaves: the visual system it borrows from Escape Vektor, the page map, every dashboard and its main visual, the drill model, live tracking, chart rules and the components the build needs. The clickable mockups in [`mockups/`](../mockups/index.html) are the reference for everything here.

Status: plan, November 7, 2026. Nothing built. Areas, loops and tiers come from [concept.md](concept.md); metric ids from [statistics.md](statistics.md); the proposal contract from [agents.md](agents.md).

## Principles

1. **One question per page, one main visual per question.** Every page opens on the chart or board that answers its question. Supporting cards sit below it.
2. **Every number opens something.** A KPI opens its breakdown, a mark opens the day or the fund behind it, a symbol opens the Symbol sheet. Nothing on screen is a dead end.
3. **Dense, not loud.** More tables and smaller cards than Escape Vektor, the same calm palette. Saturated colour goes on small marks and lights, never on big blocks.
4. **Real data or a plain line.** No placeholder numbers while waiting. Every value shows when it is from, and anything that is not plain fact says so with a small friendly tag.
5. **Fast daily, deep on demand.** The daily check (Bridge, brief, queue) works one-handed on a phone in under three minutes. Lab and Research are desktop-first but never break on a phone.
6. **Escape Vektor's rules hold.** Light by default with graphite dark, no area charts, no pill-button selectors, popups close on outside click and Escape, tone sheet copy, coral only for "act today".

## Look

### Tokens

The desk copies Escape Vektor's **Jetset Orbit** tokens from fin-dashboard `src/index.css` unchanged (paper, card, ink, coral, teal, mustard, mint, sky, lilac, board, flap, graphite dark). It does not import them across repos; the desk keeps its own copy in `ui/src/styles/tokens.css` so the two apps can drift safely.

Desk density changes only these:

| Token | Escape Vektor | Desk | Why |
|---|---|---|---|
| `--r-card` | 30px | 22px | More cards per screen |
| Body size | 14.5px | 13.5px | Tables and labels |
| Card padding | 20px 22px | 16px 18px | Density |
| Grid gap | 16px | 14px | Density |
| Hero height | 236px | 150px | A band, not a poster |
| Grain opacity | .32 | .22 | Quieter behind tables |

Type is unchanged: Bebas Neue for poster titles, big prices and the departures board; League Spartan for card titles; DM Sans for everything read, with tabular figures in tables and axes only.

### Chart palette

Validated with the dataviz palette checker against the card surfaces (`#fffaf0` light, `#202126` dark). All five slots pass lightness, chroma, colour-blind separation and normal-vision checks in both modes. Light slot 4 sits under 3:1 contrast, so any chart using it must also show direct labels or its table view.

| Slot | Hue | Light | Dark | Use |
|---|---|---|---|---|
| `--s1` | teal | `#1f9a96` | `#21a39d` | You, the portfolio, the first item |
| `--s2` | coral | `#e0603f` | `#e6603f` | Plan shadow, the second item |
| `--s3` | violet | `#8f6fc8` | `#9a7ad6` | S&P 500 shadow, the third item |
| `--s4` | amber | `#c98a12` | `#b37f14` | Fourth item |
| `--s5` | blue | `#3f8fc4` | `#4a8fd0` | Fifth item |
| `--s-other` | grey | `#b9c6c2` | `#4f6b72` | Everything folded into "Other" |

Rules:

- **Colour follows the item, never its rank.** In Compare, FTEC stays coral when another item is removed.
- **Five items at most** on lines and bars. Scatter and other every-pair charts take only the first three slots (they pass the all-pairs check; five do not).
- **Gain and loss** use teal (`--up`) and amber (`--dn`) with a grey midpoint (`--mid`). Coral never marks a loss or a market drop, per the tone sheet.
- **Magnitude** (overlap, density) uses one teal ramp, `--seq-0` to `--seq-4`.
- **Status** keeps its own tokens and always travels with a word or an icon: `--ok` (mint ink), `--watch` (mustard ink), `--act` (coral ink), `--info` (sky ink).

### Tone

Copy follows Escape Vektor's tone sheet. Desk-specific lines:

- A blocked proposal reads "Two lights need a reason" and states the cost: "about $10 a month in interest". Never "Blocked", "Warning" or a red wall.
- Losses are facts: "−$693 long-term", not "lost".
- Agent text renders as plain text only, never HTML or Markdown links.

## Shell and navigation

| Piece | Behaviour |
|---|---|
| **Pill nav** | Bridge, Results, Portfolio, Strategies, Decisions, Research. Decisions carries a coral count of waiting items |
| **Phone dock** | The same six at 390px, short labels ("Decide"), fixed to the bottom |
| **Gear** | Settings sits behind a gear button in the top bar tools, not in the menu |
| **Hero band** | Kicker, poster title, one headline number, subtabs, one or two actions; a small poster window on the right (art per area) |
| **Subtabs** | Results: Day, Week, Month, Year. Portfolio: Holdings, Stock plans, Risk, Tax. Strategies: Race, Mixes, My habits. Decisions: Queue, Journal, Flight record. Research: Dossiers, Sources, Watchlist, Calendar, Compare, Boards. Settings: Desk, Crew, Data, Box, Risk check, First run |
| **Slicer row** | Sticky under the top bar. Combo boxes only (Account, Period, Versus, plus page filters), then data freshness and, in mockups, "Sample data". One row scopes everything on the page |
| **Top bar tools** | Symbol search (`/`), market clock with a live pulse, Console (the robot), theme toggle, Settings gear |

Menu map, regrouped in November 2026 (review items U1 and U2). Old links redirect, keeping their query and hash.

| Area | Route | Holds | Old route |
|---|---|---|---|
| Bridge | `/` | Today's run, what changed, steps due | `/` |
| Results | `/results/day`, `week`, `month`, `year` | The period review and debrief | Bridge hero button |
| Portfolio | `/portfolio`, `/stocks`, `/risk`, `/tax` | Holdings board, drift, funds, rules, deposits, FI path; stock plans; risk; tax calendar | `/plan`, `/plan/stocks`, `/lab/risk` |
| Strategies | `/strategies`, `/mixes`, `/habits`, `/habits/replay`, `/:id` | The paper race and strategy list; mixes; patterns, rule tests and the replay; strategy detail | `/lab/strategies`, `/lab/mixes`, `/lab/patterns` |
| Decisions | `/decisions`, `/journal`, `/flight` | Queue, Journal, Flight record | Same |
| Research | `/research`, `/sources`, `/watchlist`, `/calendar`, `/compare`, `/boards` | Dossiers and the rest, plus Compare and Saved boards | `/lab`, `/lab/boards` |
| Settings (gear) | `/settings`, `/crew`, `/data`, `/box`, `/risk`, `/first-run` | Desk: profile, start here, this desk. Crew: desks, usage, run log. Data: freshness, inbox, keys. Box: jobs, box buttons, token | `/settings` with `#jobs`, `#inbox`, `#keys` |

Account combo lists All accounts, Individual, HSA and 401(k); the 401(k) row stays disabled with "Not linked yet" until Empower is connected. Period uses Escape Vektor's PeriodPicker values (1D, 1W, 1M, 3M, YTD, 1Y, Max). Versus switches the benchmark between the plan shadow and the S&P 500 shadow.

## Drill model

Built the way a Power BI report drills, with the Escape Vektor popup rules.

| Gesture | Result |
|---|---|
| Click a KPI tile | **Drill drawer** from the right with the breakdown and breadcrumbs (Bridge › Mix › US core) |
| Click a bar, row or day on a chart | Drill drawer one level down (a sleeve's funds, a day's contribution by holding) |
| Click any symbol chip, board row, table row or dot | **Symbol sheet** (drill-through), centred on desktop and a bottom sheet on phones |
| Hover or focus any mark | Tooltip with every series at that point and a hint when a click does more |
| Click a mark that filters (Compare item, sleeve on Plan) | Cross-filter: the page re-renders and a removable chip appears in the slicer row |
| Escape or outside click | Closes the top layer; breadcrumbs step back |

Tooltips never hold the only copy of a value: every chart has a table view (Compare shows it inline as "Side by side"; elsewhere a table toggle in the card head).

## Live tracking

Live tracking is not a page (concept). It shows up in three places:

1. **Departures board** on Bridge: every holding as a row with split-flap symbol, last price, day move in percent and dollars, value and a session sparkline against the prior close. A changed price briefly tints and the flaps flip.
2. **Symbol sheet** from anywhere: live price, a one-year line with buy dots and an average-cost line, position, gain and today, plan target against actual, lots with term and days to long-term, the dossier's thesis and bear case, open decisions and upcoming events, then Draft a decision, Dossier and Compare.
3. **Market clock** in the top bar: open or closed, the time in ET, and the price source on hover.

States:

| State | Shows |
|---|---|
| Market open | Pulse, prices from `/api/live` every 5 seconds (Finnhub free tier: 60 calls a minute) |
| Closed | Grey dot, "Closed · last close Nov 6", no pulse, no flashing |
| Mutual fund | "NAV" tag on the board and "prices at 4 PM NAV" on the sheet; never shown as live |
| Order marked placed | "Pending" chip on the row until the next mirror confirms the shares |
| Feed down | "Prices paused · last at 11:42 AM" in the clock; values hold the last tick, never zeros |

## Pages

KPI ids are from the statistics output contract. Each value shows its `as_of` on hover and its `quality` as a lilac tag when it is not `ok` (`modelled`, `pro forma`, `insufficient history`, `stale`).

### Bridge

Question: what changed, and does anything need me? Budget: one desktop screen (1440 by 1000) and two phone screens (review item U3).

| Order | Card | Content |
|---|---|---|
| 1 | Hero band | Value, today in dollars and percent, Clear the queue, and three drawer buttons: Holdings, Mix, Discounts |
| 2 | KPI row (4) | `value.market` + `value.day_change`, `bm.excess` against the safe mix, `cash.ready` + `cash.pending`, `margin.debit` + `margin.cost_month` |
| 3 | Today's run | The five stages of the daily run |
| 4 | What changed | Plan keeper's 3–5 line brief and today's three largest movers |
| 4 | Steps due | Up to four rows: waiting proposals (Approve when all lights are clear, Review otherwise) and plan steps due in 14 days, plus any no-buy window |

Everything else is one tap away in a drawer:

| Opens from | Drawer |
|---|---|
| Holdings button | Departures board; a row opens the Symbol sheet |
| Mix button (mustard when a fund is outside its band) | Drift and single-stock gauges, margin line, drift bullets, single stocks |
| Discounts button | Discount days with the research case for each |
| Market value tile | Value by account, today by holding |
| Vs the safe mix tile | Value against the safe mix and S&P 500 shadows, then the excess table by window |
| Cash and Margin tiles | Cash ready, pending, margin cost, cash by account |

On a phone the order is the same, so the daily check is: glance at the hero, read what changed, clear the steps due.

### Decisions

Question: what am I doing and why?

- **Queue** (left) of proposal cards from the contract: desk and kind, title, one-line thesis, six mini Preflight lights, funding chip, a dollar-cost chip when margin is involved, a Skeptic chip, expiry and a five-step confidence meter.
- **Detail** (right, sticky): symbol, amount, funding, horizon; thesis and bear case; Skeptic counter-case and invalidation beside them for Research and Scout; rule served.
- **Preflight annunciator**: six lamps on the board colour (concentration, drift after, funding, wash sales, lots and tax, plan rules), each with before → after. Any coral lamp opens the override box: one-line reason, "Go ahead anyway" or "Pass and log it". It never disables Approve.
- **Order ticket**: stamped card (DRAFT or READY) with copy buttons per field for Fidelity; Approve, Snooze a day, Dismiss.
- **Sources**: primary and web sources with dates; engine-only proposals say so.
- **Journal**: 20 entries a page with Newer and Older, filters for origin, status, kind and symbol kept in the URL; stamped ledger (day stamp, symbol, kind, status chip, quoted reason, origin, amount and its 30-day score against the plan), with the discipline streak, overrides against clean decisions and unmatched Fidelity trades beside it.
- **Flight record**: KPI row (`dec.score_by`, `dec.desk_record`, saves, `dec.offplan_gap`, `dec.lag`, `dec.brier`), diverging bars of each origin against the plan at 30 or 90 days (Scored at combo), a calibration line against the honest diagonal, and the desk record table with keep, behind and too-early chips.

### Portfolio

Question: what do I hold, and is it inside the rules?

| Tab | Content |
|---|---|
| Holdings | KPI row (`plan.drift_max`, `plan.next_deposit`, `plan.rules`, `plan.in_mix`, `plan.single_stock`, `fi.progress`), the departures board, drift bullets (actual dot, target tick, band, amber when outside), rules with pass or heads-up and their `desk.yaml` version, funds with data bars, the next deposit and drift after it, and the FI path as p10, p50 and p90 lines (no band fill) |
| Stock plans | One plan card per holding |
| Risk | The risk page below, moved from Lab |
| Tax | Realized and unrealized gains by term, then the tax calendar as a timeline with wash windows as bars |

Wording: there is no single plan. Targets belong to the safe mix, shadows are "safe mix shadow" and "S&P 500 shadow", and "plan" means a stock plan (review item U4).

### Research

Question: what do I know about this? Dossier list and watchlist on the left; the open dossier on the right: verdict chip, valuation range strip with today's marker, thesis and bear case, price against its sleeve's core fund rebased to 100, "What would change the call" as flagged triggers, key engine numbers, filings and events, and sources (primary, web, his own notes). Request a deep dive and Refresh now open the Console with the request filled in.

### Strategies, Risk and Compare

Strategies opens on the Race (the paper leaderboard, the stage rail and the strategy list), then Mixes and My habits. Risk sits under Portfolio and Compare under Research.

- **Compare**: slot chips (up to five, each keeps its colour, plus Add), growth of 100 with end labels, holdings overlap heatmap from N-PORT look-through, six small-multiple bar charts (1-year return, volatility, max drawdown, return per unit of risk, expense ratio, correlation to the S&P 500) and the side-by-side table. Small multiples instead of a combined chart because the metrics have different scales.
- **Risk**: KPI row (`risk.vol`, `risk.sharpe`, `risk.beta`, `risk.eff_n`, `risk.lookthrough`, `risk.var95`), return against risk scatter (holdings, you, the plan), correlation heatmap, drawdown lines, scenario shocks in dollars, look-through top holdings (direct ones highlighted) and a month-by-holding return grid.
- **My habits** (was Patterns): the replay card, rule tests, market context KPIs, his own buys scored by type against plan buys (with sample sizes), drawdown base rates, correlation shifts and seasonality labelled "description, never a signal".
- **Replay** (opens from the card at the top of My habits, `/strategies/habits/replay`): "you versus the capped you". Rule and Level combos pick one rule; three lines (you, the rule, the S&P 500 on the same dollars), four tiles, the picks-or-size read for the cap rules and the tax tile for the holding rule; bars by name for where it helped and hurt, the largest things the rule did, every rule side by side in three groups (tap a bar to replay it) and six sizing tiles. Costs read in mustard, never red.
- **Saved boards** (Research → Boards): a Compare, Risk or My habits view with its slicers pinned by "Save as a board". Boards saved under the old Lab routes move with them.

### Settings

Behind the gear, in four tabs with Risk check and First run beside them (review item U2).

| Tab | Cards |
|---|---|
| Desk | Desk profile with its editor, Start here (Risk check and First run), This desk (version, build, theme) |
| Crew | Desks with switches and the kill switch, weekly usage and the run log |
| Data | Data freshness with the mirror tables drawer, inbox upload, keys |
| Box | Scheduled jobs, box buttons, Claude token |

Data freshness and the token card read `/api/status` (mirror state and age, token days left). Desk profile dials (risk level, satellite cap, harvest threshold, horizon, tilt, lot method, industry focus) with the profile version; global kill switch; weekly usage per desk against its cap; the crew (six desks with model, last and next run, turns used and an on/off switch); data freshness including the Claude token renewal date; phone alert toggles.

### Console

Escape Vektor's Ask terminal look in a popup from the robot button: the question in mono, the brief fields the desk read, then a plain answer. Suggested questions as chips, and two buttons: Tonight (default) and Run now.

## Components

| Component | Where | Notes |
|---|---|---|
| KPI tile | Every page | Label, value, one line, optional sparkline, quality tag; whole tile is a button |
| Brief | Bridge | Coloured dot per line by tone; three to five lines |
| Proposal card | Bridge, Decisions | Built on the proposal contract; actions only where the queue is cleared |
| Preflight lights | Cards, detail | Mini row of six on cards; annunciator in the detail. Each lamp has a text label, never colour alone |
| Order ticket | Decisions | Dashed stamped card, copy per field |
| Departures board | Bridge | Board colours from Escape Vektor; flaps flip on change; reduced motion stops it |
| Stamped ledger | Journal, trade history | Day stamp, whole row opens the Symbol sheet |
| Drift bullet | Bridge, Plan, Symbol sheet | Band, target tick, actual dot |
| Cockpit gauge | Bridge | Cartoony instrument, zones in mint, mustard, coral |
| Symbol sheet | Global | Opened by any `data-sym` chip; `?sym=` deep link |
| Drill drawer | Global | Breadcrumbs, mini KPIs, one chart |
| Console | Global | Terminal popup; `?open=console` deep link |
| Crew tile | Settings | Desk icon, switch, runs, usage meter |

Charts are hand-rolled SVG React components, as in Escape Vektor (no chart library): `LineChart`, `HBars`, `Columns`, `Heatmap`, `Scatter`, `Spark`, `Gauge`, `DriftRows`. The mockups' `assets/desk.js` is a working reference for each, including hover, crosshair and resize.

## Chart rules

| Data job | Form |
|---|---|
| One headline number | KPI tile, not a chart |
| Value over time against benchmarks | Lines, one axis, end labels, 2px strokes |
| Rebased comparison | Growth of 100 with a dashed 100 line |
| Gain or loss by item | Diverging horizontal bars around zero |
| Actual against target | Drift bullets |
| Many metrics across items | Small multiples, one per metric |
| Pairwise relation | Heatmap (diverging for correlation, teal ramp for overlap) |
| Risk against return | Scatter, three colours at most |
| Daily or monthly pattern | Grid heatmap |
| Distribution of outcomes | Percentile lines or columns |

Never: area or band fills, two y-axes, pies or donuts, a number on every point, red for a loss, dashed gridlines. Legends are present whenever there are two or more series; end labels name lines directly on wide screens.

## Responsive

| Width | Layout |
|---|---|
| 1920 | 12-column grid, content capped at 1840px, KPI row of 6 or 7 |
| 1440 | Same grid; search narrows |
| ≤1360 | KPI rows wrap to 3 or 4; side-by-side cards stack to halves |
| ≤1100 | Nav keeps icons with short labels |
| ≤860 (phones, 390 tested) | Dock replaces nav, one column, slicer row scrolls sideways, board drops name and sparkline columns, sheets become bottom sheets, tables scroll inside their card |

Page width never scrolls sideways at 390px; every mockup was checked for `scrollWidth` at 1920, 1440 and 390 in both themes.

## Accessibility

Keyboard reaches every tile, row and mark; Escape closes the top layer; focus rings use `--focus`. Lights and chips always carry text. Charts have a table view and an `aria-label`. Reduced motion (device or profile) stops flaps, pulses, card rise and the board tint. Text never uses series colours; values stay in ink.

## Phases and dependencies

Mapped to `ROADMAP.md`.

| Phase | Design work | Needs first |
|---|---|---|
| 1 Foundation | Tokens, shell, pill nav, dock, theme, Settings data freshness and token date | `ui/` Vite app built to `ui/dist` and served by the API; `/api/status` for freshness and token (infra) |
| 2 Bridge and Symbol sheet | Departures board, Symbol sheet, KPI tile, line and spark charts, market clock states | `/api/live`, positions and lots tables |
| 3 Engine core and Plan | Full Bridge KPI row, drift bullets, gauges, Plan page | Output contract v1 (`/api/metrics`, `/api/series`) |
| 4 Decisions and Preflight | Queue, proposal card, Preflight annunciator, override box, order ticket, Journal ledger | `POST /api/preflight`, decision records |
| 5 Plan keeper and tax desk | Brief card, crew tiles and usage in Settings, tax calendar | Proposal records, run log |
| 6 Research | Dossier, sources, watchlist, Console | Dossier store, EDGAR and FRED fetchers |
| 7 Lab | Compare, Risk, heatmap and scatter components, Saved boards shell | `/api/compare`, risk metrics |
| 10 Flight record and Patterns | Flight record and Patterns pages | 30 days of scored decisions |
| 11 Scout and FI scenarios | FI path card | Monte Carlo percentiles |

Not mocked yet: the **Strategy lab** (phase 9). It needs its own page (strategy list, walk-forward results, trial ledger, forward paper portfolios) once its spec settles.

## Mockups

Open [`mockups/index.html`](../mockups/index.html). Keys 1–9, 0, - and = jump between the twelve views, arrows step, T flips the theme, P shows the phone frame, `[` hides the list. Pages also take `?theme=dark`, `?sym=FTEC` and `?open=console`. All numbers are synthetic sample data from `mockups/assets/data.js`; prices on the board tick every few seconds to show the live behaviour (`?still` turns that off).

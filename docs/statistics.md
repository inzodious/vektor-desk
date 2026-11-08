# Statistics and data plan

How Vektor Desk gets its data, stores it, and turns it into the numbers every other part of the desk uses: KPIs, dashboards, live tracking, comparisons, patterns and the agents' evidence. Status: plan, November 7, 2026. Nothing built.

Siblings: [architecture.md](architecture.md) (mirror, compose app), [agents.md](agents.md) (what reads this output), [design.md](design.md) (how it is shown), [concept.md](concept.md), and the [roadmap](../ROADMAP.md).

## Principles

1. **The engine is the calculator.** Every number comes from deterministic Python over SQLite. Agents quote numbers by metric id; they never compute them. A proposal whose figures do not match the engine is rejected before it is shown.
2. **Reconcile before you publish.** A day's metrics are only marked good once holdings match the broker. A desk that is confidently wrong is worse than no desk.
3. **Describe, do not predict.** Statistics say what happened and how unusual it is. Nothing in the engine outputs a price target or a "buy" signal.
4. **Every number carries its quality.** Sample size, as-of time, and a flag (`ok`, `stale`, `pro_forma`, `modelled`, `insufficient_history`). The UI shows any flag that is not `ok`.
5. **Free only.** Every source below is free for personal use. No paid feeds, no scraping sites whose terms forbid it.

## Data sources

| Source | What the desk takes | Limits and terms | Cadence |
|---|---|---|---|
| **Escape Vektor mirror** (read-only service account, `/data/mirror.db`, see [architecture.md](architecture.md)) | Every collection under `lockIn/{uid}`; the engine uses `positions`, `snapshots`, `activity`, `plans`, `transactions`, `paystubs`, `prices/board`, `priceCloses/{SYM}_{YEAR}`, `priceProfiles/{SYM}` | One-way, never writes back | 8:00 and 17:00 ET |
| **Fidelity lot export** (CSV dropped in `/data/inbox/fidelity/`) | Tax lots: acquired date, shares, cost per lot, term; realized gain/loss export for the year | Manual. SimpleFIN only gives average cost | Monthly, and before any sale |
| **Tiingo** (existing key) | Daily OHLC, `adjClose`, `divCash`, `splitFactor` for benchmarks and comparison symbols not already in the mirror | Free tier is personal use; request and unique-symbol caps apply ([docs](https://api.tiingo.com/documentation)) | Nightly, incremental |
| **Finnhub** (existing key) | Live quotes in market hours, earnings calendar, basic financials, insider transactions where the free tier allows | 60 calls a minute; some endpoints are premium, checked at build time | Every 5 min in market hours |
| **SEC EDGAR** | Filings index, XBRL company facts (revenue, margins, share count), Form 4 insider trades, N-PORT fund holdings | Free; a `User-Agent` with contact details is required (`DESK_SEC_USER_AGENT`), at most 10 requests a second | Nightly for holdings and watchlist |
| **FRED** (free key, `FRED_API_KEY`) | Risk-free rate (3-month T-bill), 10y and 2y yields, CPI, high-yield spread, VIX close | Free key, generous rate limit | Nightly |
| **Ken French data library** | Daily and monthly Fama-French 5 factors plus momentum, US market back to 1926 | Free CSV ([library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.French/data_library.html)) | Monthly |

Escape Vektor's `priceCloses` only refresh when Joshua opens it, so they can lag. Price sources, in order:

| Day | Close used |
|---|---|
| Any day with a Tiingo bar | Tiingo's official close (it wins over the mirror) |
| Any other day | The mirror's close, else the last close before it |
| A snapshot day whose newest close predates its last trading day | The broker's own price (value ÷ shares), unless it equals an older close (a stale snapshot), then the newest close |
| A symbol nothing prices (Empower plan codes) | The broker's snapshot price; backfill lists it under `unpriced`, not `errors` |

A held symbol is fetched from Tiingo unless the mirror already has a close for the last trading day. Weekends and holidays resolve to the last trading day.

**Gaps, stated plainly.**

- **401(k) at Empower** has no feed. Until it is connected in SimpleFIN, the desk models it from the plan's contribution schedule and the funds' proxy tickers, flagged `modelled`. It never mixes a modelled number into a broker-reconciled total without saying so.
- **Options data.** No free source is reliable enough, so there are no options statistics (implied volatility, open interest) in v1.
- **Intraday history.** Finnhub's free tier gives live quotes, not reliable minute bars. Live tracking stores the 5-minute quotes it sees from the day the desk starts; there is no intraday backfill.

## Storage

Two SQLite files on the TrueNAS dataset, both WAL mode, each with one writer. Nightly TrueNAS dataset snapshots are the backup.

- **`/data/mirror.db`** is owned by the mirror ([architecture.md](architecture.md)): `rows(tbl, id, json, at)` is current Firestore state, with one view per table `ev_<tbl>(id, json, at)`; `row_history(seq, tbl, id, json, at, pulled_at, op)` is append-only, one row each time a document changes or disappears; `runs` and `tables` (with `full_at`, `max_at`) give freshness. Pulls read only rows whose `at` moved, with a full pass per table once a week, so a delete can reach `row_history` up to 7 days late. The engine never writes to it.
- **`/data/desk.db`** is owned by the engine, which `ATTACH`es `mirror.db` read-only. The API and the agents' brief builder open `desk.db` read-only.

- **`/data/lab/data`** holds point-in-time copies the engine drops for the lab (SQLite backup API, as in `desk.backup.snapshot`, plus the Parquet price and filing files). The lab never opens a live WAL database.

Long engine jobs wrap themselves in `desk.runlock.job_lock("<name>")` so a deploy waits for them. Engine code builds on the shared scaffold: `desk/config.py`, `desk/db.py`, `desk/runlock.py`, and schedule lines in `deploy/crontab`.

**Late deletes.** Current holdings always come from the latest snapshot (by `asOf`), so a deleted older snapshot that lingers for a week changes nothing. A lingering deleted activity or transaction row could double a flow; the cash check below catches it, marks the day `stale` and names the row, and the weekly full pass clears it.

| Layer | Where | Tables | Rule |
|---|---|---|---|
| **raw** | `mirror.db`, plus `desk.db` | Mirror: `rows`, `row_history`. Engine: `raw_lot_files`, `raw_api(source, key, body, fetched_at)` | Verbatim, append-only. Lets any later number be recomputed from what was known on the day |
| **core** | `desk.db` | `accounts`, `engine_snapshots` (every snapshot the mirror ever saw, with the one per day used as the anchor), `holdings_daily(date, account, symbol, shares, close, value, cost, reported_value, is_cash, source, anchor, quality)`, `lots`, `cash_flows(date, account, amount, kind, external)`, `prices_daily(symbol, date, close, adj_close, source)`, `benchmarks`, `factors_daily`, `macro_daily`, `fund_holdings(fund, as_of, holding, name, cusip, weight, asset_cat, country, accession)`, `quotes_live(symbol, at, price)` | Normalized, deduplicated, one row per fact |
| **derived** | `desk.db` | `metric_values`, `series_daily`, `signals`, `proposals_scored`, `data_health` | Written by the engine run, tagged with `engine_version` |

**Keep every pull.** Escape Vektor collapses synced snapshots to one per week. `row_history` keeps every version of every snapshot and position the mirror saw (`positions.json.snapshotId` joins to `snapshots.json.id`), so the engine rebuilds `holdings_daily` for every pull and, from the first day the mirror runs, has a daily history Escape Vektor does not. Earlier history is rebuilt the way Escape Vektor's `market.js` does it: the earliest snapshot's quantities rolled forward by activity rows, priced with daily closes, flagged `pro_forma` where no snapshot confirms it.

**Cash flows.** External flows are deposits, withdrawals, HSA contributions and 401(k) contributions. Internal moves (the margin and cash sub-account journals, transfers between your own accounts at the portfolio level, core fund sweeps, dividend reinvestment) are not flows. Getting this wrong is the most common way personal return math lies, so the classifier ships with fixtures for every Fidelity action text seen so far.

| Activity row | External flow when |
|---|---|
| `deposit`, `withdrawal` | Always (not core, not a cash symbol) |
| `transfer`, `other`, money in | `desk.decisions.plan.is_cash_in`: EFT, ACH, electronic, deposit, contribution, received or wire wording, and no out wording |
| `transfer`, `other`, money out | EFT, ACH, electronic, transfer, withdraw or wire wording |
| Any row with a non-core symbol | Never (share transfers are holdings moves) |

Same-amount opposite moves between two of your accounts within 3 days are internal at the portfolio level.

## Reconciliation and data health

Before metrics are published for a day, the engine checks:

| Check | Pass when |
|---|---|
| Value | Shares × close per account is within $1 or 0.05% of SimpleFIN's account value. A price-only gap is `warn` and names the biggest gaps; positions that don't add up are `fail` |
| Shares | The lot export's shares per symbol equal the positions' shares exactly |
| Cash | Change in cash equals flows plus trades plus income, within $0.01 |
| Freshness | Mirror pull under 14 hours old |
| Closes | Every held symbol has a close for the last trading day, or is a code nothing prices |
| Flows | Lists any snapshot-day change that prices and recorded activity don't explain. The engine counts it as money in or out, not return (unlogged deposits, payroll contributions, a margin buy without a debit row). Always `ok`; it's there to explain the number |
| Market keys | Tiingo, Finnhub, FRED and the SEC contact are all set; any missing one warns with `set … in desk.env, then redeploy the app` |
| Symbol kinds | Every holding is known as a fund or a stock: Escape Vektor's profiles, then SEC's fund list, the benchmark ETFs, ticker shape (5 letters ending in X, plan codes with digits) and SEC titles |

Every non-ok detail ends with `Fix:` and the one step that clears it.

**Implied flows.** On each snapshot day, per account: residual = snapshot value − the prior day's holdings repriced at today's closes − recorded deposits and withdrawals − dividends and interest. A residual over $1 or 0.05% is added to that day's flows for the account and the portfolio, so TWR, MWR, day change, shadows and risk see price moves only.

**Roll-forward.** A buy or sell with no quantity (synced rows often have none) moves shares by −amount ÷ that day's close, or the anchor's price. With neither, both legs are skipped, so cash never goes negative on a buy that bought nothing.

**Triggers on a recompute.** Re-running a day replaces its detected triggers: changed details update in place, triggers that no longer hold are withdrawn (`withdrawn` in the run result), and nothing re-alerts. Lot-export triggers are kept.

**Holding moves.** The per-holding `daily_move` trigger uses market closes only (Tiingo bars or the mirror's), dated on the run day, against a close at most 5 days older. Symbols valued at the broker's snapshot price, such as plan codes, never fire it.

**Dry run.** `python -m desk.engine daily --dry-run` (also `holdings`, `core`) runs on a throwaway copy of the data, sends no alerts, and prints the result plus `health_detail` for every check. Nothing in `/data` changes.

A failed check marks the day `stale`, keeps the last good values on screen with their date, and writes the reason to `data_health`. Agents read `data_health` first and stop if it is not green. The Phase 1 exit test ("numbers match Fidelity to the cent on a test day") is this table passing.

## Metrics catalog

Each metric has an id, a formula, a minimum sample, and scopes (portfolio, account, sleeve, holding). The registry lives in `engine/metrics.yaml`; this table is the plan for it.

### Value and flow

| Id | Metric | Notes |
|---|---|---|
| `value.market` | Market value | Live in market hours, close otherwise |
| `value.day_change` | Day change in dollars and percent | Against the prior close |
| `value.market`, `value.weight` (scope `holding`) | Value and weight per holding | Summed across accounts |
| `flow.net_contrib` | Net contributions | External flows only, by window |
| `value.gain` | Investment gain | Change in value minus net contributions. The honest "how much did the market give me" |
| `income.dividends` | Dividend and interest income | Trailing 12 months and by window |
| `cash.share` | Cash share | Core fund and settled cash as a share of value |
| `cash.ready` | Cash ready to invest | Settled core cash minus any margin debit |
| `cash.pending`, `cash.pending_days` | Next deposit and days until it | From the profile's deposit schedule, else the plan; `modelled` |
| `flow.invest_rate` | Investing rate | External investment flows divided by take-home pay (from `paystubs`) |

### Returns

| Id | Metric | Notes |
|---|---|---|
| `ret.twr` | Time-weighted return | Daily linked; flows at end of day. Judges the investments, ignores deposit timing |
| `ret.mwr` | Money-weighted return (XIRR) | Judges your actual dollars, including timing |
| `ret.twr_ann` | Annualized TWR | 3Y and since start, only at 365 days or more |
| `ret.contrib` | Contribution to return | Weight × return per holding; sums to the portfolio return |
| `ret.after_tax` | After-tax return per account | Windows `YTD`, `1Y`, `ITD`. HSA, IRA, Roth and 401(k) keys equal `ret.twr`; taxable accounts subtract dividends and realized short-term gains at `tax.marginal_rate` and long-term gains at `DESK_LTCG_RATE_PCT` (default 15); `modelled` |

Windows: 1D, 1W, MTD, QTD, YTD, 1Y, 3Y, since start. **Returns under a year are never annualized.** A 9% month shown as 180% a year is noise in a costume.

### Benchmarks and comparison

| Id | Metric | Notes |
|---|---|---|
| `bm.plan_shadow` | Plan-mix shadow portfolio | Every external dollar, on its real date, buys the plan's target weights at that day's close; deposits steer drift the way the plan does; never sells |
| `bm.sp500_shadow` | S&P 500 shadow | Same dollars, same dates, all in an S&P 500 index fund (total return) |
| `bm.excess` | Excess return vs each shadow | In percent and in dollars. Dollars are the headline |
| `bm.tracking_error` | Tracking error | Annualized volatility of daily excess return |
| `bm.capture` | Up and down capture | Against the S&P 500, geometric, scope `benchmark` with `scope_id` `up` or `down`, window `ITD`, 63 days or more |
| `bm.active_share` | Active share vs plan | Half the sum of absolute weight differences, invested weights against the plan targets |

The shadows answer the only question that matters for a personal portfolio: would the same paychecks have done better on autopilot? The cumulative dollar gap to `bm.plan_shadow` is the desk's most important number and feeds the agent scorecard.

### Risk

Portfolio rows use your actual daily returns once there are enough of them. Before that, they use today's invested weights over five years of holding prices (scaled by invested over total value, so margin shows), flagged `pro_forma`; a holding with less history borrows the S&P 500's return until it starts. The S&P 500 proxy is the first of SPY, FXAIX, VOO, IVV with prices.

| Id | Metric | Min sample | Notes |
|---|---|---|---|
| `risk.vol` | Annualized volatility | 63 days | 63-day and 252-day windows |
| `risk.downside_dev` | Downside deviation | 63 days | Annualized, below zero; windows `63D`, `252D` |
| `risk.mdd` | Max drawdown, duration, recovery | none | Plus `risk.dd_now` (current drawdown from the high) and `risk.mdd_days` (longest days under water) |
| `risk.var95`, `risk.cvar95` | Historical 1-day and 1-month VaR and expected shortfall | 250 days | Loss in percent (positive), windows `1D` and `1M` (overlapping 21-day returns), up to five years of returns |
| `risk.beta` | Beta to the S&P 500 | 252 days | Portfolio, and per holding (scope `holding`) on its own prices |
| `risk.corr` | Correlations | 252 days | Scope `holding`: each holding against the S&P 500, windows `63D` and `252D`. Scope `pair`, `scope_id` `A\|B`: the matrix for the ten largest holdings |
| `risk.sharpe`, `risk.sortino` | Risk-adjusted return | 1 year | Actual returns only, windows `1Y` and `ITD`. Risk-free is the average FRED 3-month bill over the window, else `DESK_RISK_FREE_PCT`, else 0 (`modelled`) |
| `risk.top1`, `risk.top5` | Largest one and five weights | none | |
| `risk.eff_n` | Effective number of holdings | none | 1 / sum of squared weights (inverse HHI) |
| `risk.lookthrough` | Look-through exposure | none | Fund weights × N-PORT holdings plus direct stocks, so an index fund and a sector fund that both hold the same megacaps show the true overlap. Portfolio row (window `top10`) is the ten largest underlyings combined; scope `underlying` lists the top 25. `risk.lookthrough_coverage` is the share of invested value seen through |
| `risk.sector` | Sector exposure | none | Scope `sector`. Underlyings by their Finnhub industry (or Escape Vektor's profile), mapped to the 11 GICS sectors; non-equity fund holdings are `Bonds and other`; sector ETFs without N-PORT map whole; anything else is `Unclassified` or `Funds without look-through` |
| `risk.factor` | Factor exposure | 3 years | Market, size, value, profitability, investment and momentum betas from the French factors; on holdings' own histories, weighted (phase 11). Scope `factor`, scope_id the factor, window `3Y`; each holding needs about 680 of the last 756 factor days. `risk.factor_coverage` is the weight covered. Per-holding loadings and alpha at `GET /api/engine/factors` |
| `risk.scenario`, `risk.scenario_pct` | Scenario shocks in dollars and percent of value | none | Scope `scenario`. Historical replays on current positions: `gfc_2008` (2007-10-09 to 2009-03-09), `covid_2020` (2020-02-19 to 2020-03-23), `rates_2022` (2022-01-03 to 2022-10-12); a holding without prices then uses the S&P 500 times its beta (`pro_forma`). Set shocks: `market_-20` (beta-scaled, `modelled`), `satellite_-50` (single stocks outside the plan), `rates_+2` (each holding's sensitivity to daily 10-year yield moves over three years, `modelled`) |
| `risk.corr_shift` | Correlation shift | 252 days | 63-day minus 252-day correlation with the market per holding; a move of 0.3 or more means diversification is quietly changing |

### Margin

| Id | Metric | Notes |
|---|---|---|
| `margin.debit` | Margin debit | From the margin sub-account balance |
| `margin.cost_day`, `margin.cost_month` | Interest cost in dollars | Daily accrual at `DESK_MARGIN_RATE_PCT`, assuming a 360-day year until the first margin statement confirms the broker's day count |
| `margin.funded_share` | Margin-funded share of positions | |
| `margin.call_drop` | Price drop to a maintenance call | `1 − debit / ((1 − m) × value)`, with `m` the maintenance requirement (per security where the export gives it, otherwise `DESK_MARGIN_MAINT_PCT`, default 30) |
| `margin.call_price` | Call price for the largest single stock | The price at which that holding alone, with everything else flat, triggers a call |
| `margin.breakeven` | Return a margin-funded position needs to beat its interest | Annual rate × days held / 360 |

### Plan and drift

| Id | Metric | Notes |
|---|---|---|
| `plan.weight`, `plan.target`, `plan.drift` | Actual weight, target and drift in points per fund | Against the active plan version from the mirror |
| `plan.in_mix` | Share of value in plan funds | |
| `plan.drift_max` | Largest drift, in points, and which fund | The Bridge headline |
| `plan.single_stock` | Single-stock share vs its band | |
| `plan.next_deposit` | Where the next deposit goes | The split that closes the most drift without selling |
| `plan.adherence` | Plan adherence | Share of buy dollars (activity, core sweeps excluded) that went to plan funds; windows `MTD`, `QTD`, `YTD`, `1Y`, `ITD` |
| `plan.rules` | Rule checks | Single-stock band, no new single stocks, no margin-funded buys, drift over 5 points. Each a pass or fail with the evidence |

### Tax (needs the lot export)

| Id | Metric | Notes |
|---|---|---|
| `tax.lots` | Lots with unrealized gain or loss | Short or long term, days to long term. Totals ship as `tax.unrealized_st` and `tax.unrealized_lt` |
| `tax.harvestable` | Harvestable loss | Total and per holding: losses at or over `tax.harvest_threshold_usd` (default $250) with no buy in the last 30 days |
| `tax.wash_window` | Wash-sale calendar | Days until each symbol's window clears (scope `holding`). Windows open on every loss sale and every buy (activity, reinvests and lots acquired in the last 30 days), across all accounts unless `tax.wash_sale_accounts` narrows them. S&P 500 and total-market trackers that could be substantially identical are flagged for review rather than decided. Served by `GET /api/engine/wash` |
| `tax.realized_st`, `tax.realized_lt`, `tax.wash_disallowed` | Realized short- and long-term gains this year, and disallowed wash losses | From the realized gain/loss export, window `YTD` |
| `tax.offset` | Ordinary-income offset used and carryforward | The $3,000 annual limit |
| `tax.harvest_value` | Tax value of a harvest | Loss × `tax.marginal_rate` |
| `tax.marginal_rate` | Marginal federal and state rate | Escape Vektor's PolicyEngine estimate (`prefs.taxEngine`, tax on $1,000 more pay), else `tax.marginal_rate_pct` in `desk.yaml`, else `DESK_MARGINAL_RATE_PCT`; scope `tax` splits `federal` and `state`; quality `modelled` |
| `tax.lot_realized` | Realized gain or loss per lot sold | Short or long term, with the sale it came from |
| `tax.div_drag` | Tax drag from taxable dividends | |

### Research signals and macro (nightly fetchers)

Single stocks only (held, `market_symbols` role `watch`, or `DESK_WATCHLIST`); funds are skipped. Scope `holding` unless noted.

| Id | Metric | Source and notes |
|---|---|---|
| `sig.earnings_days` | Days to the next earnings date | Finnhub earnings calendar |
| `sig.earnings_since` | Days since the last report | |
| `sig.eps_surprise`, `sig.revenue_surprise` | Last report vs estimate, in percent | |
| `sig.earnings_reported` | 1 when a report landed since the previous engine day | Fires the `earnings` trigger |
| `sig.insider_net`, `sig.insider_buyers` | Open-market insider dollars (buys minus sells) and distinct buyers, window `90D` | Finnhub insider transactions (codes P and S only) |
| `sig.dilution` | Share count change, window `1Y` | XBRL `dei:EntityCommonStockSharesOutstanding` |
| `fund.revenue_growth`, `fund.gross_margin`, `fund.operating_margin`, `fund.net_margin` | Latest fiscal year, window `FY` | XBRL company facts, full-year periods only |
| `macro.rf_3m`, `macro.y2`, `macro.y10`, `macro.curve_10y2y`, `macro.hy_spread`, `macro.vix`, `macro.cpi_yoy` | Latest values, scope `macro` | FRED |

Tables: `sec_tickers`, `filings` (last two years, with archive links), `fundamentals` (one row per concept and period), `macro_daily`, `earnings`, `insider_trades`. The `research` job runs at 00:40, refreshes each symbol at most every 20 hours, keeps SEC at about 8 requests a second, and skips any source whose key is missing. `GET /api/engine/research?symbol=` serves filings, facts, earnings, insiders and signals; `GET /api/engine/macro?start=` serves the FRED series.

### Costs

| Id | Metric | Notes |
|---|---|---|
| `cost.expense`, `cost.expense_usd` | Weighted expense ratio and dollars a year | Expense ratios from the plan's funds; scope `holding` carries each fund's ratio |
| `income.yield` | Trailing dividend yield | Scope `holding`, window `TTM`, from Escape Vektor's symbol profiles |
| `cost.total` | All-in yearly cost | Expenses plus margin interest plus estimated dividend tax drag |

### FI progress

| Id | Metric | Notes |
|---|---|---|
| `fi.progress` | Progress to the FI number | The FI number comes from Escape Vektor's plan, never retyped |
| `fi.required_return` | Return needed to hit the target date at the current deposit rate | |
| `fi.date_pctl` | FI date at the 10th, 50th and 90th percentile | Monte Carlo, below |

**Monte Carlo.** Block bootstrap (12-month blocks) of real US market and bond returns since 1926 from the French library, scaled to the plan's mix and fees, with the plan's deposit schedule. Ten thousand paths, fixed seed per run so numbers do not wobble between refreshes. Output is percentiles, not a single date. It repeats history's range; it cannot imagine a worse one, and the page says so.

**As built (phase 11).** `desk.engine.fi`, inside every core run (about 1.5 s for 10,000 paths of 50 years).

| Input | From |
|---|---|
| FI number, target date | Escape Vektor pref `fi`: `fiYearlySpend × fiMultiple`, birth date plus `fiTargetAge` |
| Real or nominal | The same pref's `inflationAdjusted` and `inflation`; real paths deflate each month at that rate |
| Start value | `value.market` (the desk's accounts only) |
| Deposits | Mean of the plan's `monthly_plan` contributions, else `accounts.individual.monthly_contribution`, else none (caveat) |
| Mix and fees | Plan targets; bond funds (a known list, `DESK_BOND_FUNDS`, or a sleeve named bond or fixed income) earn the French T-bill rate, the rest the French US market; weighted expense ratios come off monthly |
| History | `F-F_Research_Data_Factors` monthly (`mkt_rf_m`, `rf_m`, July 1926 on), fetched by the `french` job |

| Metric | Unit | Notes |
|---|---|---|
| `fi.number` | usd | From the pref |
| `fi.progress` | pct | `value.market` / FI number, `modelled` |
| `fi.required_return` | pct | Annual return that reaches the number by the target date with the current deposits (bisection) |
| `fi.date_pctl` | days from `as_of` | Windows `p10`, `p50`, `p90` of the first month a path reaches the number; null when fewer paths than that percentile reach it within the horizon (target plus 10 years, at least 30, at most 50) |
| `fi.on_time` | pct | Share of paths that reach it by the target date |

`GET /api/engine/fi` has the dates, the yearly p10, p50 and p90 value lines for the chart (lines, never a band), the inputs and the caveats. `DESK_MC_PATHS` sets the path count.

### Decision KPIs

| Id | Metric | Notes |
|---|---|---|
| `dec.score_30`, `dec.score_90`, `dec.score_365` | Decision score at 30, 90 and 365 days | Dollar result of the decision minus putting the same dollars in the plan mix on the same day; agent proposals are scored whether taken or not |
| `dec.score_by` | Scores summarized | By origin (agent desk or you), type (buy, sell, harvest, margin), and override vs clean |
| `dec.brier` | Calibration of agent confidence | Brier score, per desk |
| `dec.desk_record` | Each agent desk's cumulative score | The six-month keep-or-cut test in the roadmap |
| `dec.offplan_gap` | Cost of off-plan trades | Your own trades outside the plan, scored the same way |
| `dec.lag` | Decision lag | Days from proposal to your approve, dismiss or trade |

## Patterns

Patterns are descriptive context with a base rate attached, never a trigger. Each signal ships with its definition, its sample size, how often it was followed by what (with a confidence interval), and one line on what it is not.

| Group | Signals |
|---|---|
| **Market context** | S&P 500 drawdown from its high, VIX percentile (10 years), 10y minus 3-month yield spread, high-yield spread percentile |
| **Holding** | Position in the 52-week range, distance from the 200-day average, realized volatility percentile, next earnings date, average absolute move on the last eight earnings, insider buys and sells (Form 4) over 90 days, share count change (dilution) from XBRL |
| **Drawdown and recovery** | For the market and each fund: past drawdowns of a similar depth and how long they took to recover. A base-rate table, not a call on this one |
| **Seasonality** | Monthly return table per holding, shown as description with its sample size. Never a signal (see below) |
| **Correlation shifts** | `risk.corr_shift`, surfaced when a holding's short-window correlation with the market moves by 0.3 or more |
| **Your behavior** | Buys after drops vs after rises, off-schedule buys, margin-funded buys vs scheduled plan buys (each scored with `dec.score_*`), trade frequency, holding period of single stocks |

**Left out on purpose as signals:** day-of-week and calendar effects (seasonality is shown, never acted on), chart patterns, and anything found by searching many rules on the same data. They test well and trade badly.

## Comparative analysis

One comparison engine (`desk.engine.compare`) serves every "this vs that" view: `GET /api/compare?ids=&window=`.

- **Inputs:** two to five ids, comma separated: a ticker, `portfolio`, `account:<key>`, or `shadow:plan_shadow` / `shadow:sp500_shadow`. Windows `1M`, `3M`, `6M`, `YTD`, `1Y` (default), `3Y`, `5Y`, `10Y`, `MAX`.
- **Alignment:** common days only, total return (`adjClose`, else close; portfolio, accounts and shadows use their `twr_index`), rebased to 100 at the start.
- **Rule:** a window longer than the shortest history is never silently shortened: the shortest series sets the start, `clipped` is true and `note` names it. A bad id, window or count is a 400.

| Field | Meaning |
|---|---|
| `series` | `{id: [{date, value}]}`, rebased |
| `start`, `end`, `days`, `requested_start`, `clipped`, `note` | The window actually used |
| `table[]` | Per id: `return_pct`, `ann_return_pct` (365 days or more only), `vol_pct`, `mdd_pct`, `return_per_risk`, `corr` and `beta` to the first id, `corr_sp500`, `expense_pct`, `yield_pct`, `overlap_pct` (look-through overlap with the first id), `after_tax_pct` (accounts, `YTD`, `1Y`, `MAX`) |

Standard comparisons: actual vs plan shadow vs S&P 500 shadow; fund vs fund inside a sleeve; any watchlist symbol vs the fund it would replace; Individual vs HSA vs 401(k).

### Look-through job

`python -m desk.engine lookthrough` runs Sundays at 02:10 and skips any source whose key is missing.

| Step | Source | Notes |
|---|---|---|
| Fund to series | SEC `company_tickers_mf.json` | Weekly; `sec_funds` |
| Latest N-PORT | Fund trust's submissions, newest `NPORT-P` whose series matches | Up to 40 documents scanned per fund; each document's series is cached in `nport_filings`, so a trust is read once a quarter. Refreshed every 30 days |
| Holdings | `primary_doc.xml` | Name, CUSIP, ticker, percent of net assets, asset category, country into `fund_holdings`. Ticker from the filing, else the SEC company title match. DTDs are refused |
| Sectors | Finnhub `stock/profile2` | Top underlyings plus direct stocks, up to `DESK_SECTOR_PROFILES` (default 150) a run, refreshed every 90 days, about one call a second; `sym_profiles` |

The core run writes the exposure to `lookthrough(as_of, holding, name, weight, direct, via)` and warns in `data_health` (`lookthrough`) when a held fund has no holdings yet or its filing is over 150 days old. `GET /api/engine/lookthrough?fund=&limit=` serves the exposure rows (direct share and the funds behind each), sectors, funds covered, and one fund's holdings.

## Preflight (what-if)

Before a proposal or one of your own trade ideas reaches an order ticket, the engine runs it as a hypothetical against today's holdings and returns the after-trade picture:

| Check | Uses |
|---|---|
| Concentration and drift after the trade | `risk.top1`, `plan.single_stock`, `plan.drift_max` |
| Plan rules | `plan.rules` (a margin-funded buy is a hard flag with `margin.cost_month` in dollars) |
| Margin | New `margin.debit`, `margin.call_drop`, `margin.breakeven` |
| Wash sales | `tax.wash_window` across the brokerage, HSA and 401(k), including scheduled 401(k) and plan buys |
| Lots | For a sale: the lot pick (highest cost first by default), realized short- and long-term gain or loss, `tax.harvest_value` |

Preflight is engine code, owned here: `preflight(holdings, trade) -> lights`. Agents call it on every proposal (their block and flag statuses are in [agents.md](agents.md)), the Decisions page calls it on hand-typed ideas, and both get the same answer. It never changes stored metrics; it writes `preflight(ticket_id, metric_id, before, after, flag)` rows the ticket shows side by side.

Code: `desk.engine.preflight.check_trade(cfg, trade, ticket_id=None)`; the trade is `{kind, symbol, account, side, amount_usd, shares, funding, lot_method, limit}`. The answer:

| Field | Shape |
|---|---|
| `status` | `clear`, `flagged` (any `watch`) or `blocked` (any `act`) |
| `lights` | Six lamps `{id, label, status: ok\|watch\|act, before, after, detail}`: `concentration`, `drift_after`, `funding`, `wash_sales` (plus `clears`), `lots_tax`, `plan_rules` |
| `tax` | `{lot_method, lots: [{acquired, shares, cost, proceeds, gain, term}], realized_st, realized_lt, realized, harvest_loss, wash_clear_date}` |
| `metrics` | `{metric_id, before, after, flag}` for `value.market`, `risk.top1`, `plan.single_stock`, `plan.drift_max`, `margin.debit`, `margin.cost_month`, `margin.call_drop`, `cash.share`, and `tax.realized` on a sale |
| `trade` | The trade as checked: account picked, shares and dollars filled in at the latest price (or the limit) |

| Lamp | `act` when | `watch` when |
|---|---|---|
| Concentration | A buy opens a new single stock, takes one past its band (default: the satellite cap), or takes all single stocks past `opportunity.satellite_cap_pct` | A sale leaves one past its band; a buy of a symbol whose kind is unknown |
| Drift after | | Largest drift grows past the drift limit |
| Funding | A buy is margin-funded or cash runs short, with the monthly interest in dollars and the drop to a call | |
| Wash sales | A buy within 30 days of a loss sale of that symbol; a loss sale within 30 days of a buy of it in any account | A scheduled deposit or dividend reinvest would buy it back; a possibly identical fund |
| Lots and tax | | No lot export; lots cover fewer shares than the sale; a harvest that realizes a gain |
| Plan rules | A buy breaks a rule that held before | A sale breaks one; a rule already off before and no worse |

## Scoring decisions

The method behind `dec.score_*` and the agents' scorecard.

- **Baseline:** the same dollars into the plan mix. Both sides start at the **next trading day's close** after the decision is recorded (desks run after the close, so the same-day close would be look-ahead).
- **Total return:** dividends reinvested through `adjClose`, the same for both sides.
- **By kind:** a buy is scored as the bought position vs the baseline; a sell or trim as the sale proceeds in the plan mix vs keeping the shares; a `hold_off` by what it avoided (margin interest not paid, a wash sale not triggered); a harvest as realized loss × marginal rate, plus or minus the replacement fund's tracking difference.
- **Per desk:** total excess dollars, hit rate, and a bootstrap 90% interval for the mean excess. With a few dozen proposals the interval will usually include zero, and the scorecard says that rather than ranking noise.
- **Calibration:** Brier score of `confidence` against "beat the baseline at 90 days", plus a calibration table once a desk has 30 scored proposals.

### As built (phase 10)

Scoring and patterns run inside every core run (`desk.engine.scoring`, `desk.engine.patterns`), from `desk.decisions.records.scoring_rows`; nothing new is fetched.

**One decision.** Day zero is the first close after the decision's local day: `created_at` for proposals, `filled_at` for your own logged trades. A horizon is scored once its day has passed (last close on or before day zero plus 30, 90 or 365 calendar days). The plan side is the plan mix bought at day zero and held; missing fund prices renormalize the mix (`pro_forma`), no plan prices at all fall back to the S&P 500 (`modelled`). Proposals with status `rejected` are skipped; every other status counts, taken or not.

| Kind | Score in dollars |
|---|---|
| `buy`, `deposit_route`, `rebalance` (buy side) | amount × (symbol return − plan return), less margin interest at `DESK_MARGIN_RATE_PCT` (360-day year) when funded on margin |
| `sell`, `trim`, `rebalance` (sell side) | amount × (plan return − symbol return) |
| `harvest` | realized loss from Preflight's `tax_impact` × marginal rate; tracking difference is not modelled |
| `hold_off` | amount × (plan return − symbol return) when it names a symbol, plus margin interest avoided |
| `alert`, `memo` | Not scored |

**Summaries.**

| Metric | Scope, scope_id, window | What |
|---|---|---|
| `dec.score_30`, `_90`, `_365` | `decision`, decision id, `30D` / `90D` / `365D` | The score above; the Journal reads these |
| `dec.score_by` | `group`, `origin:…`, `kind:…`, `path:clean\|flagged\|override`, `taken:taken\|not_taken` | Total dollars, `n_obs` = decisions |
| `dec.desk_record` | `desk`, desk, `90D` | Cumulative 90-day dollars |
| `dec.brier` | `desk`, desk, `90D` | Brier of `confidence` against beating the plan at 90 days |
| `dec.lag` | `desk` and portfolio | Median days from proposal to your decision |
| `dec.offplan_gap` | portfolio, `90D` | Your own trades with an override, margin funding, or a buy outside the plan |
| `dec.saves` | portfolio, `90D` | Ideas not taken that would have lost money, plus `hold_off` savings |

`GET /api/engine/scorecard[?origin=]` returns the full card: `groups` (n, total, mean, hit rate, 90% bootstrap interval of the mean with a note when it includes zero), `desks` (record, approvals, calibration bins from 30 scored, lag, days on, chip `too_early` under 182 days or 10 scored, else `keep` or `behind`), `saves`, `offplan_gap`, and each decision's scores. The bootstrap is seeded, so numbers do not wobble.

**Patterns.** Each pattern row in `signals` carries its value, the base rate of "higher later" for past days in the same bucket, a 90% Wilson interval, the sample count, and one line on what it is not. Base rates need 5 samples; samples are month ends, so overlapping windows make the interval optimistic.

| Pattern | Bucket | Followed by |
|---|---|---|
| `pat.mkt_drawdown` | 0–5, 5–10, 10–20, 20–30, 30%+ below the high | S&P 500 higher 12 months later |
| `pat.vix_pctl`, `pat.hy_pctl` | Quintile of the trailing 10 years | Same |
| `pat.curve_10y3m` | Inverted or not | Same |
| `pat.range_52w`, `pat.vol_pctl` (own 5 years) | Quintile | Holding higher 3 months later |
| `pat.ma200_gap` | Below −10, −10–0, 0–10, above 10% | Same |
| `pat.earnings_move` | Mean absolute two-day move on the last 8 reports | No base rate |

`GET /api/engine/patterns` adds drawdown base-rate tables (market and each fund: past drawdowns at least as deep, median and longest trading days back to the high), monthly seasonality per symbol labelled "description, never a signal", correlation shifts of 0.3 or more, and your behavior: buys after a 5% drop, a 5% rise or flat (90-day scores), scheduled vs off-schedule vs margin-funded buys, trades a month, and the median holding period of sold single stocks.

## Strategy lab

Where a strategy from deep research gets tested: a backtest over 3, 5 and 10 years that only sees data as it was known on each day, then forward paper trading with fake money. The research desk proposes; the engine runs the rules; nothing in the lab touches real money.

### The catch: the model has already seen the future

Any model writing a strategy in 2026 knows how 2016 to 2025 turned out. A strategy it writes for a 2016 start can be fitted to that knowledge without anyone meaning to ("favor AI chip makers" looks brilliant from 2016). Hiding the dates from it does not fix this. So:

1. **The model writes rules, never trades.** A strategy is a spec (below). The engine executes it day by day; the model never sees a simulated day's data or results while the run is going.
2. **Universes are rules, not ticker lists.** "Top 500 US stocks by market cap on each rebalance date" is allowed; "NVDA, AMD, AVGO" is not. A hand-picked list is the leak.
3. **Backtests screen; forward paper trading decides.** Only trading after the spec is registered is truly out of sample, for the model and for us. A strategy needs both a passing backtest and six months of forward paper trading before any proposal may cite it.

### Strategy spec

The strategy desk ([agents.md](agents.md)) hands the lab a `strategy.json`, frozen and hashed when registered. Stages: `draft` → `lab` → `paper` → `eligible`.

| Field | Meaning |
|---|---|
| `id`, `version`, `parent_id` | Identity; `parent_id` links variants so every one counts in the trial ledger |
| `title`, `hypothesis` | The claimed edge and why the market might miss it, in two sentences |
| `predicted_effect` | Expected excess return and over what horizon, stated before any run |
| `universe` | A point-in-time rule: index members as of each date, a fixed fund list, or a screen. Never today's tickers |
| `signals` | `[{metric_id, window, transform}]` from the engine's feature library only: returns over N days, volatility, distance from an average, 52-week range, valuation and growth from XBRL facts, insider buys, earnings vs prior year. No free-form code |
| `entry`, `exit`, `rebalance`, `sizing` | Rules on signals; sizing by equal weight, volatility, or signal rank |
| `params` | Each tunable number with the range the desk may search |
| `constraints` | Long only, no margin, max position %, max turnover |
| `success_criteria` | Pre-registered: excess vs plan mix, max drawdown, minimum trades, the windows it must hold in |
| `horizons` | Any of 3, 5 and 10 years |
| `written_at`, `desk`, `model`, `effort` | Provenance; `model` sets the training-cutoff window below |

| `benchmark`, `account` | Optional. Defaults: plan mix (S&P 500 always shown alongside) and taxable |

The lab, not the desk, sets costs and tax rates. This table is the canonical field list; [agents.md](agents.md) points here.

The feature library grows by pull request, with tests, so a new signal is reviewed code, not something a model writes on the fly. Claude-written strategy code is out of scope for now; if the library ever proves too narrow, code would run in the same sandbox under the same bars, as a new trial.

### Claude drives, the engine runs

Joshua's ask is Claude directing simulations, tuning them and reading the statistics. The loop, with the honesty built into what Claude can see:

1. **Explore.** The strategy desk returns an experiment in its structured output, and the agent runner writes it to `/data/lab/queue/*.json`: a registered spec, a parameter grid inside `params`, a date range, a seed, and a trial budget (default 200 variants per spec). It may also ask for analyses on finished runs: parameter sensitivity, regime splits (bull, bear, high and low rates), factor regression, turnover and cost sensitivity.
2. **Run.** The `lab` service (`python -m desk.lab`, no network, reads only the copies in `/data/lab/data`, writes only to `/data/lab/runs`; see [architecture.md](architecture.md)) runs the grid with walk-forward. Each variant is a row in the trial ledger.
3. **Read.** The next desk run gets the results as `lab_result` in its prompt: walk-forward fold summaries and the analyses, never the holdout or the post-cutoff window. It can tune and resubmit until the trial budget is spent. Every variant raises the bar through the deflated Sharpe ratio, so tuning harder makes passing harder.
4. **Finalize.** One `finalize` request per spec version opens the holdout and the post-cutoff window and produces the verdict. After that the spec is closed; a change is a new version and a new trial.

Claude never executes code and never sees a simulated day before the engine has finished it. It chooses what to test and explains what came back, which is what it is good at.

### Backfill and sizing

Data the lab needs for 10-year windows, sized for the box (Ryzen 5 5600GT, 6 cores; 15 GiB RAM today, 32 GB soon; desk budget 20 GiB on the NVMe pool).

| Data | Source | Size on disk | How long it takes |
|---|---|---|---|
| ETFs, sector and factor funds, benchmarks (about 150 symbols) | Tiingo | Under 50 MB | First month |
| Large caps: S&P 500 members over the last 15 years, removed ones included (about 1,000 symbols) | Tiingo; its ticker list carries start and end dates, which finds delisted symbols | About 150 MB | Months 2 to 4 |
| Broader universe, optional (about 1,500 more) | Tiingo | About 250 MB | Months 5 to 8 |
| Fundamentals with filing dates, 2009 on | SEC Financial Statement Data Sets (quarterly bulk files) | Raw zips deleted after import; about 1 to 2 GB extracted | One weekend, then one file a quarter |
| Insider trades, 2006 on | SEC Insider Transactions Data Sets (quarterly) | About 0.5 GB | One weekend |
| Factor and industry portfolios, 1926 on | Ken French library | Under 100 MB | Minutes |
| Macro with vintages | FRED and ALFRED | Under 100 MB | Minutes |

**The bottleneck is Tiingo's free tier, not the hardware**: 50 requests an hour, 1,000 a day, and 500 unique symbols a month, shared with Escape Vektor. One request returns a symbol's full history, so the desk takes about 400 new symbols a month overnight and leaves the rest for Escape Vektor. Bars are cached forever and only topped up after that. Caps are set by `DESK_TIINGO_HOURLY` (40), `DESK_TIINGO_DAILY` (800) and `DESK_TIINGO_MONTHLY_SYMBOLS` (400); held and benchmark symbols top up daily, universe symbols rotate every 90 days, so a 1,000-stock universe stays inside the monthly cap. **Backfill starts in roadmap phase 3**, so the large-cap universe is ready when the lab lands in phase 9. ETF and French-portfolio strategies can run from day one of the lab.

Storage is Parquet files under `/data/lab/data`, read with DuckDB (free, embedded), so a backtest never loads more than its universe. Totals stay under 5 GiB, well inside the 20 GiB budget.

**Compute.** A universe of 1,000 stocks over 10 years is 1,000 × 2,520 days, about 10 MB per field in float32, so a whole backtest fits in memory many times over. One vectorized variant takes well under a second. Under today's limits (3 workers, 1.5 GiB, 01:00 to 06:00 ET, never overlapping an agent run under `job_lock`) that is tens of thousands of variants a night, far more than the trial budget allows. After the RAM upgrade the limit rises to 8 workers and 8 GiB, which matters for the broader universe and for running beside Ollama and Jellyfin, not for speed. Workers stream one symbol's history at a time where they can, use float32 except for cash and tax math, and cap memory per chunk. Results are stored as summaries plus the top runs; raw run files in `/data/lab/runs` are pruned after 30 days. Trial ledger rows are never pruned.

### Data, point in time

| Need | Free source | Limit |
|---|---|---|
| Prices, splits, dividends | Tiingo EOD, including delisted symbols where it carries them | 500 new symbols a month on the free tier, so a broad universe is backfilled over months (below) |
| Long, survivorship-free test bed | Ken French portfolios (industry, size, value, momentum, profitability sorts) back to 1926 | Portfolio returns, not single stocks. The honest place to test factor-style ideas over many decades |
| Fundamentals as known that day | SEC Financial Statement Data Sets, each figure dated by its filing | From 2009; earlier years are out of scope |
| Insider trades | SEC Insider Transactions Data Sets (Form 4), by filing date | From 2006 |
| Macro | FRED, using first-release values where ALFRED vintages exist | |
| Index membership history | No clean free source | Rebuilt from published change lists and flagged `reconstructed` |
| Analyst estimates, options, intraday | None free | Strategies that need them are out of scope |

**Delisted stocks.** A stock that vanishes from the data without a merger price is booked at −30% on its last day, a common conservative assumption, rather than quietly dropped. Survivorship is the cheapest way to make a backtest look good.

### How a run works

- **Execution:** signals use data up to the close; trades fill at the next day's open plus a cost of 5 to 25 basis points by liquidity. No margin unless the spec says so, and then at the real rate.
- **Taxes:** taxable runs pay short- and long-term rates on realized gains at each year end, using `tax.marginal_rate`.
- **Walk-forward:** parameters are chosen on a training window and tested on the next window, rolling forward. Every start month in the horizon is run, not one lucky start date.
- **Locked holdout:** the most recent two years are opened once per spec, after the walk-forward is final.
- **After the model's training cutoff:** results for the days after the writing model's cutoff are reported separately. That window is the only past data the model cannot have seen.
- **Result:** per-horizon metrics, the post-cutoff window, variants tried, caveats (survivorship, reconstructed membership), and a verdict of `pass`, `fail` or `inconclusive` against both the pre-registered `success_criteria` and the bars below.
- **Trial ledger:** every variant run is logged in `strategy_trials`. The count feeds the overfitting statistics; nothing gets deleted.

### What a strategy must show

| Test | Bar |
|---|---|
| Excess return vs benchmark after costs and taxes | Positive with a 90% interval above zero across start dates |
| Deflated Sharpe ratio (Bailey and López de Prado) | Above 0.95, which accounts for every trial in the ledger |
| Probability of backtest overfitting (combinatorial cross-validation) | Below 0.2 |
| Factor check | Alpha after market, size, value, profitability, investment and momentum. A strategy that is just momentum in disguise is labelled that; buying a cheap momentum fund does the same job |
| Holdout | Same sign and at least half the walk-forward excess |
| Forward paper trading | Six months, scored like decisions (`dec.score_*`), with no edits to the spec |

A strategy that passes graduates to a paper portfolio that keeps running, and the scout may cite it in proposals inside the satellite cap, still through Preflight. Edit a spec and it starts over as a new trial.

### Plainly

Daily prices and public filings are the most-mined data in the world. Strategies that "the market has not caught onto" in them are rare, small, and often gone after costs and taxes. Expect most ideas to fail the bars above, and count that as the lab working. The likely wins are rules about your own behavior (deposit timing, rebalance bands, harvest thresholds, margin) and plain factor exposure, cheaply held. Horizons: 10 years is about one market cycle, 5 is short, and 3 is mostly noise; the tear sheet says so next to each one.

### Lab outputs

`strategies(id, spec_hash, registered_at, status)`, `strategy_trials(strategy_id, params, window, metrics, run_at)`, `paper_positions(strategy_id, date, symbol, shares, value)`, `paper_trades(strategy_id, date, symbol, side, shares, price, cost)`, plus a tear sheet per run: equity curve vs benchmark (lines, no fill), drawdowns, yearly returns, turnover, after-tax return, factor loadings, deflated Sharpe, overfitting probability, and the trial count.

### As built (phase 9, first cut)

**Where things live.** The lab is `desk.engine.lab`; its service is `python -m desk.engine.lab` (overnight window `DESK_LAB_HOURS`, default `1-6` ET, under `job_lock("lab")`; `--once` runs the queue now). It has no network and opens nothing but:

| Path | Writer | Holds |
|---|---|---|
| `lab/data/lab.db` | Engine `lab-export` job (00:55 nightly), atomic replace | `bars` (price bars plus mirror closes), `symbols` (kind, role, first and last day), `macro`, `plan_mix`, `settings` (marginal rate), `factors` and `french` (phase 9b). SQLite in rollback-journal mode, never WAL, so it opens read-only on the lab's read-only mount |
| `lab/queue/*.json` | Strategy desk runner | Experiment and finalize requests |
| `lab/runs/ledger.db` | Lab only | `strategies` (status `lab`, `paper`, `research`, `failed`, `inconclusive`), `strategy_trials` (kinds `train`, `test`, `full`, `holdout`, `rule`; never pruned), `lab_results` (`experiment`, `finalize`, `rejected`, `rule` bodies), `queue_done`. Older ledgers migrate in place |
| `desk.db` | Engine `lab-export` job | `paper_portfolios`, `paper_positions`, `paper_trades` |

**Spec grammar** (also served as `grammar` by `GET /api/lab/strategies` and in every `desk_view`):

| Field | Accepted |
|---|---|
| `universe` | `{"type": "fund_list", "set": "sector_etfs" \| "core_etfs" \| "benchmarks"}`, `{"type": "fund_list", "symbols": [funds only]}`, a `rule` naming a set, or `{"type": "screen", "min_history_days", "min_price"}` for single stocks (survivorship caveat). A hand-picked stock list is rejected |
| `signals` | Feature `ret`, `ret_skip`, `vol`, `ma_gap`, `range_52w`, `dd`; window `63d`, `6m`, `1y` or `{param}d`; transform `raw`, `rank`, `inverse_rank`, `zscore`, `inverse`. Score is the mean of the transformed signals |
| `entry` | `{"top_n": 3 \| "param:top_n", "min_signal": 0}` or "top 3 by rank". `min_signal` applies to the first signal's raw value; slots it leaves empty stay in cash |
| `exit` | `"rebalance"`, or `{"hold_rank": 5}` / "falls out of top 5" to keep a holding while it ranks in the top 5 |
| `rebalance`, `sizing` | Weekly, monthly or quarterly; `equal`, `inverse_vol` (63-day) or `rank`. `max_position_pct` caps a weight, the rest stays cash |
| `params`, `grid` | `{"top_n": {"min": 1, "max": 4, "default": 3}}` or a list; grid values must sit inside. Over the trial budget (max 200), a seeded, deterministic subset runs |

**A run.** Signals at the close, fills at the next open (`adjClose`-scaled), costs 5 bps for funds, 15 for stocks, 25 under $20M a day. FIFO lots, year-end tax on net realized gains at the exported marginal rate (else 24%) and 15% long-term, losses carried. Cash earns the 3-month bill. A symbol whose bars stop before the data ends is sold at its last price less 30%. The benchmark is `spec.benchmark`, else the plan mix, else the S&P 500, rebalanced monthly; the S&P 500 is always reported.

**Walk-forward.** The two years before the newest bar are the holdout and never run before finalize. The range before it splits into folds of 3 years train and 1 year test (2 and 0.5 under 4 years; under 2.5 years is rejected). Each fold picks the variant with the best training Sharpe that meets `max_turnover` (read as turnover a year), then runs it on the test year; test years are stitched into the walk-forward record. Every variant also runs over the whole range for the overfitting tests.

**What the desk sees** (`desk_view`): folds, the walk-forward summary, the start-month distribution per horizon (walk-forward when long enough, else the full range flagged `in_sample`), deflated Sharpe (trials counted across the spec's whole `parent_id` family, Sharpe variance across variants), PBO by combinatorial cross-validation over 10 blocks, the factor check, the analyses it asked for (`param_sensitivity`, `regime_split` bull/bear and high/low rates, `turnover_cost` at 1×, 2×, 4×, `factor_regression`), caveats, and rejection reasons. A changed spec under the same version, or any spec after finalize, is rejected.

**Finalize** runs the last fold's parameters on the holdout and on the days after the writing model's cutoff (`DESK_LAB_MODEL_CUTOFFS`, a JSON map of model to date, default 2026-06-30), then checks the bars: start-month 5th percentile above zero on the longest horizon, deflated Sharpe over 0.95, PBO under 0.2, holdout excess positive and at least half the walk-forward excess, and the spec's own `excess_vs_plan_pts`, `max_drawdown_pct`, `min_trades`. Any failed bar is `fail`; all computed bars passing is `pass`; anything missing is `inconclusive`. The factor bar is alpha t of 2 or more; it is `null`, and does not block, only when the factors are missing or overlap fewer than 252 days. A pass moves a fund or screen strategy to `paper` and a French one to `research`.

**Paper.** Each night the engine replays a paper strategy with its finalized parameters from the finalize day to the newest bar on fresh data, so it can never be tuned after the fact. After 182 days it becomes `eligible` if it is level with or ahead of its benchmark, otherwise `retired`. `desk.engine.lab.eligible` lists the eligible ones for Scout.

**API.** `GET /api/lab/strategies` (list with `hypothesis`, trial counts, paper state, feature catalog, grammar) and `GET /api/lab/strategies/{id}` (the desk view plus paper trades, and `spec`: the frozen title, hypothesis, predicted effect, universe, signals, entry, exit, rebalance, sizing, params, success criteria, horizons, `written_at` and `model`; null for a rejected version). Paper graduation is `paper.days` ≥ 182 calendar days; `paper.summary` is a JSON string. Workers: `DESK_LAB_WORKERS` (default 1) processes.

**Not in this cut.** Point-in-time fundamentals and insider signals from the SEC bulk data sets, and reconstructed index membership.

### As built (phase 9b)

**French data.** Engine job `french` (03:30 on the 2nd of each month, skips files fetched in the last 25 days) downloads the daily zips into `desk.db`:

| Table | From | Holds |
|---|---|---|
| `factors_daily(series, date, value)` | 5 factors (2x3) and momentum, daily; 3 factors monthly | `mkt_rf`, `smb`, `hml`, `rmw`, `cma`, `rf`, `mom`, and monthly `mkt_rf_m`, `rf_m` (dated the 1st), in percent |
| `french_returns(set_name, name, date, ret)` | Value-weighted block only | `industry_12`, `industry_49`, `size_deciles`, `momentum_deciles` (deciles by name) |

The lab loads a French set only when a spec asks for it, sharing one calendar across the set, so 49 industries over 60 years cost about 40 MB per worker. `FF.MKT` (market plus bill) is built from the factors.

**French universes.** `{"type": "french", "set": "industry_12"}`. Runs on the factor calendar (from July 1963), benchmark `FF.MKT` unless the spec names one, 5 bps costs, cash earns the French bill rate. The portfolios are not investable, so a pass is `research` and never goes to paper; the caveat says so.

**Factor check.** Every experiment regresses the walk-forward record's daily excess return on the six factors (OLS, Newey-West errors with 5 lags, 252 overlapping days minimum). It reports annual alpha, its t, each loading with its t, and R².

| Label | When |
|---|---|
| `alpha` | Alpha t of 2 or more: the factor bar passes |
| `factor_in_disguise` | No significant alpha and a size, value, profitability, investment or momentum loading with t above 3; the caveat names the tilt |
| `no_alpha` | Neither |

**Rule backtests.** A queue file `{"request": "rule", "id", "rule", "params", "horizons"}` tests a habit, not a stock picker, on the plan mix (or `mix`, funds only) with synthetic money: `start_value` 10,000 and `deposit_monthly` 1,000 by default.

| Rule | Params (grid of up to 12) | Against |
|---|---|---|
| `rebalance_band` | `band_pts`: rebalance to target when any weight drifts past it, checked monthly | Deposits split pro rata, never selling |
| `deposit_steering` | none: deposits fill underweights first (`shadows.deposit_split`) | Same |
| `harvest` | `threshold_usd`: sell a position down that much into a substitute (new basis), $3,000 a year against ordinary income | Same, never harvesting |
| `margin` | `dip_pct`, `borrow_pct`, and `rate_pct` as one fixed number: borrow once per dip, deposits repay first, margin call at 30% equity | Same, never borrowing |

Both sides are sold and taxed at the end, so deferring a gain is not a win. The score is the after-liquidation difference in points of money put in, for every start month in each horizon before the holdout (p5, p50, p95, share better), plus the holdout run.

| Verdict | When |
|---|---|
| `helps` | p5 above zero on the longest horizon and the holdout not negative |
| `hurts` | p95 below zero |
| `no_clear_edge` | Otherwise; `inconclusive` when no horizon fits |

Rule results are `lab_results` kind `rule`, each variant logged in `strategy_trials`. `GET /api/lab/strategies` lists them under `rules`; `GET /api/lab/strategies/{id}` returns `kind: "rule"` with the full body.

**Watchlist.** `GET /api/engine/watchlist` lists `market_symbols` role `watch` (`source: "desk"`) and `DESK_WATCHLIST` (`"env"`, read-only) with name, last two closes, last bar and whether research exists. `POST {symbol}` and `DELETE /{symbol}` change desk rows only; a bad symbol, an env row or a symbol not on the list is a 400 `{detail}`.

## Honest limits

Rule backtests (rebalance bands, deposit steering, harvest thresholds, margin rules) use the same simulator rules, holdout and start-month scoring as strategies, with their own verdict.

What the desk will say out loud:

- **Your own track record is too short to judge skill for years.** Telling a 2-point yearly edge from luck at a 5% tracking error takes about `(2 × 5 / 2)² = 25` years of data at a t-stat of 2. A single-stock satellite at 10% tracking error chasing 3 points takes about 44. The scorecard compares against the plan to catch big losses, not to prove brilliance.
- **More rules tested means more false winners.** A rule that only works on one window, one parameter, or with hindsight is reported as such.
- **Survivorship.** Screens over "today's tickers" skip the companies that died. Scout ideas are tested against that bias or labelled with it.
- **Monte Carlo is not a forecast.** It samples the past; fat tails and new regimes are outside it.
- **Pro forma is not history.** Risk numbers built from current weights over past prices describe the portfolio you hold now, not the one you held.
- **Fund look-through is quarterly.** N-PORT holdings lag up to about two months.

## Output contract

What agents and dashboards build against. Owned by this doc; changes go through it.

**Tables** in `desk.db` (read-only to everyone but the engine):

```
metric_values(metric_id, scope, scope_id, window, as_of, value, unit, n_obs, quality, engine_version)
series_daily(series_id, scope, scope_id, date, value, quality)
signals(signal_id, scope_id, as_of, value, base_rate, ci_low, ci_high, n_obs, note)
engine_views(name, as_of, body)   (latest scorecard, patterns, fi and factors JSON)
data_health(as_of, check, status, detail)
preflight(ticket_id, metric_id, before, after, flag)
triggers(as_of, kind, scope_id, detail)
paper_portfolios, paper_positions, paper_trades   (Strategy lab; the trial ledger is lab/runs/ledger.db)
```

- `scope`: `portfolio`, `account`, `sleeve`, `holding`, `benchmark`, `shadow`, plus `pair`, `underlying`, `sector`, `scenario`, `macro`, `rule`, `tax`, `decision`, `group`, `desk`, `factor`.
- `quality`: `ok`, `stale`, `pro_forma`, `modelled`, `insufficient_history`.
- `unit`: `usd`, `pct`, `pts`, `ratio`, `days`, `date`.

**Agent brief.** Agents never open the SQLite file. The brief builder ([agents.md](agents.md)) calls `desk.engine.brief.desk_slice(cfg, desk)` and writes the result as that run's `brief.json`: `{desk, as_of, data_as_of, data_health: [{check, status, detail}], sections}`. It raises `brief.NotReady` before the first engine run. Every metric value is `{metric_id, scope, scope_id, window, value, unit, as_of, quality}`; portfolio-level rows use `scope_id` `all`.

| Desk | Sections |
|---|---|
| Plan keeper | value, cash, drift, rules, margin, benchmarks |
| Tax | tax, holdings, cash, drift, `lots` (per lot gain and term), `wash_windows` |
| Risk | risk, margin, concentration, returns |
| Research | holdings, returns, room |
| Scout | room, holdings |
| Skeptic | value, drift, margin, risk, tax, `wash_windows` |
| Strategy | returns, benchmarks, risk |

Every slice also carries `triggers` for its day. A proposal's `numbers_used[].field` is the key `metric_id:scope_id:window` (for example `plan.drift:FXAIX:now`), so Preflight can match it to the brief exactly.

**Triggers.** After each core run the engine writes `triggers(as_of, kind, scope_id, detail)` for the agents' scheduler (`desk.engine.triggers.today(cfg)`); each fires at most once a day. The first day a condition appears, it also sends a phone alert on `alerts` (no dollar amounts). Live quotes failing during market hours sends one `ops` alert a day.

| Kind | Fires when | Scope |
|---|---|---|
| `margin_debit` | `margin.debit` above zero | `portfolio` |
| `daily_move` | Portfolio 1D TWR past the risk dial (1 to 4% for risk level 1 to 5), or a holding past 2.5 times it | `portfolio` or ticker |
| `concentration` | A single stock, or all of them together, past `opportunity.satellite_cap_pct` | ticker or `satellite` |
| `rule_breach` | A `plan.rules` check is 0 | rule id |
| `lot_export` | A lot or realized export was imported | `lots` or `realized` |
| `deposit_landed` | A scheduled deposit landed in the last 3 days | deposit id |
| `earnings` | A holding reported (phase 6 fetchers) | ticker |

**API for the UI.**

| Endpoint | Returns |
|---|---|
| `GET /api/engine/health` | `data_health` for the latest run, plus the last engine run |
| `GET /api/engine/metrics?ids=&scope=&scope_id=&window=&as_of=` | Latest values with quality; `ids` takes a comma list and `ret.*` prefixes |
| `GET /api/engine/series?id=&scope=&scope_id=&start=&end=` | Daily series (`value`, `twr_index`) for portfolio, account and shadow scopes |
| `GET /api/engine/holdings?date=` | Holdings for a day |
| `GET /api/engine/value?start=&end=&account=&symbol=` | Value over time, optionally one account or one position |
| `GET /api/engine/prices?symbol=&start=&end=` | Daily closes `[{date, close}]` |
| `GET /api/engine/lots?symbol=&account=` | Current tax lots and recent lot files |
| `GET /api/compare?ids=&window=` | Aligned, rebased series plus the comparison table; 400 on bad input |
| `GET /api/engine/lookthrough?fund=&limit=` | Look-through exposure, sectors, funds covered, one fund's holdings |
| `GET /api/live` | Latest quotes, live value, day change (market hours) |
| `GET /api/live/intraday` | Today's quote ticks `{SYM: [{t, price}]}` |
| `POST /api/preflight` | The Preflight answer for a hypothetical trade (nothing stored); 400 on a bad trade |
| `GET /api/engine/preflight?ticket_id=` | Stored before and after rows for a ticket |
| `GET /api/engine/wash` | Open wash-sale windows `{symbol, kind, date, clears, account, amount}` |
| `GET /api/lab/strategies`, `/api/lab/strategies/{id}` | Strategy list, status, feature catalog and grammar; one strategy's tear sheet, verdict and paper trades |
| `GET /api/engine/scorecard?origin=` | Flight record: groups, desks, saves, off-plan gap, per-decision scores |
| `GET /api/engine/patterns` | Patterns: market, holdings, drawdown tables, seasonality, correlation shifts, behavior |
| `GET /api/engine/fi` | FI Monte Carlo: dates, percentile lines, inputs, caveats |
| `GET /api/engine/factors` | Factor loadings per holding and weighted |
| `GET`, `POST /api/engine/watchlist`, `DELETE /api/engine/watchlist/{symbol}` | Watchlist rows; desk rows editable, `DESK_WATCHLIST` rows read-only |

**Display rules for design.** Show `as_of` on every KPI; show any non-`ok` quality as a small, friendly tag, not a red error; never annualize under a year; Monte Carlo as percentile lines or markers, not a filled band.

## Compute schedule

| When | Runs |
|---|---|
| Every 5 min, 9:30 to 16:00 ET weekdays | Quotes, live value, day change, intraday drawdown, margin call distance |
| After each mirror (8:00, 17:00 ET) | Reconciliation, holdings, flows, returns, drift, rules, margin, tax (if lots are fresh), risk, correlations, scenarios, look-through exposure, signals, brief for the agents. Comparisons are computed on request |
| Nightly | Tiingo, EDGAR, FRED pulls (the scorecard and patterns refresh with each core run) |
| Nightly, 00:55 | `lab-export`: fresh `lab/data/lab.db`, then paper portfolios replay to the newest bar. Queued lab experiments run 01:00 to 06:00 ET under `job_lock("lab")` |
| Weekly, Sunday 02:10 | N-PORT look-through and sector profiles |
| Monthly, 2nd at 03:30 | `french`: daily and monthly factors and portfolios from the Ken French library. The Monte Carlo and factor exposure refresh with each core run |

## Stack and tests

**Python, not JavaScript** (the open question in the project plan). The engine is dataframes, regressions, bootstraps and XIRR; pandas, numpy, scipy and statsmodels do that well, all free and open source. The one piece worth sharing with Escape Vektor is the Fidelity action-text classifier (`src/lib/fidelityActivity.js`); it is ported, and both repos run the same synthetic fixture file so they cannot drift apart.

Metric math is written in the repo, not taken from an unmaintained analytics library, so every formula is readable and tested.

Tests use synthetic fixtures only (no real positions, lots or statements in the repo):

- Hand-worked cases for every metric (a two-deposit TWR and XIRR, a drawdown with recovery, a wash-sale window crossing accounts).
- Identities: TWR equals simple return with no flows; contributions sum to the portfolio return; a shadow funded with the actual trades equals the actual portfolio.
- Reconciliation fixtures that must fail (a missed split, an internal journal counted as a deposit).

## Phasing

Mapped to the [roadmap](../ROADMAP.md) phases; the lead thread owns the final order.

| Roadmap phase | Statistics work |
|---|---|
| 1. Foundation | Raw layer and `holdings_daily` from the mirror (start keeping every pull from day one), synthetic fixtures |
| 2. Bridge and Symbol sheet | Live quotes (`quotes_live`, `/api/live`), lot export parser and `lots`, `value.market`, `value.day_change` |
| 3. Engine core and Plan | Flow classifier, reconciliation and `data_health`, value and flow, returns, both shadows, plan and drift, margin, costs, `risk.top1`, `risk.top5`, `risk.eff_n`, `risk.mdd`, output contract v1 |
| 4. Decisions and Preflight | Preflight, tax lots, wash-sale calendar, realized gain or loss, decision records captured with the inputs scoring will need |
| 5. Plan keeper and tax desk | Per-desk brief slices, triggers, `tax.marginal_rate`, `tax.harvest_value` |
| 6. Research | EDGAR, FRED and Finnhub fetchers; holding signals (earnings, insiders, dilution) |
| 7. Lab: Compare and risk | Comparison engine, full risk table, look-through and sectors, scenarios, correlation shifts |
| 9. Strategy lab | Feature library, spec validation, experiment queue and `desk.lab` runner, walk-forward, trial ledger, deflated Sharpe and overfitting tests, finalize step, forward paper portfolios, rule backtests. ETF and French universes first |
| 10. Flight record and Patterns | Decision scoring and calibration, pattern tables |
| 11. Scout and FI scenarios | Monte Carlo, factor exposure |

Price backfill for the lab starts in phase 3 and runs in the background (see Backfill and sizing).

Tier 1 metrics are everything through phase 5. The December 6 target depends on the lot export (phase 2) and the wash-sale calendar (phase 4); if those slip, the December loss sale is planned at Fidelity as before.

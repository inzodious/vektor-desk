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

Held symbols already have closes in Escape Vektor's `priceCloses` (with `adjClose`), so the desk reads those from the mirror and only calls Tiingo for symbols Escape Vektor does not price. That keeps the two apps well inside one free key.

**Gaps, stated plainly.**

- **401(k) at Empower** has no feed. Until it is connected in SimpleFIN, the desk models it from the plan's contribution schedule and the funds' proxy tickers, flagged `modelled`. It never mixes a modelled number into a broker-reconciled total without saying so.
- **Options data.** No free source is reliable enough, so there are no options statistics (implied volatility, open interest) in v1.
- **Intraday history.** Finnhub's free tier gives live quotes, not reliable minute bars. Live tracking stores the 5-minute quotes it sees from the day the desk starts; there is no intraday backfill.

## Storage

Two SQLite files on the TrueNAS dataset, both WAL mode, each with one writer. Nightly TrueNAS dataset snapshots are the backup.

- **`/data/mirror.db`** is owned by the mirror ([architecture.md](architecture.md)): `rows(tbl, id, json, at)` is current Firestore state, with one view per table `ev_<tbl>(id, json, at)`; `row_history(seq, tbl, id, json, at, pulled_at, op)` is append-only, one row each time a document changes or disappears; `runs` and `tables` give freshness. The engine never writes to it.
- **`/data/desk.db`** is owned by the engine, which `ATTACH`es `mirror.db` read-only. The API and the agents' brief builder open `desk.db` read-only.

Long engine jobs wrap themselves in `desk.runlock.job_lock("<name>")` so a deploy waits for them.

| Layer | Where | Tables | Rule |
|---|---|---|---|
| **raw** | `mirror.db`, plus `desk.db` | Mirror: `rows`, `row_history`. Engine: `raw_lot_files`, `raw_api(source, key, body, fetched_at)` | Verbatim, append-only. Lets any later number be recomputed from what was known on the day |
| **core** | `desk.db` | `accounts`, `holdings_daily(date, account, symbol, shares, close, value, source)`, `lots`, `cash_flows(date, account, amount, kind, external)`, `prices_daily(symbol, date, close, adj_close, div, split)`, `benchmarks`, `factors_daily`, `macro_daily`, `fund_holdings(fund, as_of, holding, weight)`, `quotes_live(symbol, at, price)` | Normalized, deduplicated, one row per fact |
| **derived** | `desk.db` | `metric_values`, `series_daily`, `signals`, `proposals_scored`, `data_health` | Written by the engine run, tagged with `engine_version` |

**Keep every pull.** Escape Vektor collapses synced snapshots to one per week. `row_history` keeps every version of every snapshot and position the mirror saw (`positions.json.snapshotId` joins to `snapshots.json.id`), so the engine rebuilds `holdings_daily` for every pull and, from the first day the mirror runs, has a daily history Escape Vektor does not. Earlier history is rebuilt the way Escape Vektor's `market.js` does it: the earliest snapshot's quantities rolled forward by activity rows, priced with daily closes, flagged `pro_forma` where no snapshot confirms it.

**Cash flows.** External flows are deposits, withdrawals, HSA contributions and 401(k) contributions. Internal moves (the margin and cash sub-account journals, transfers between your own accounts at the portfolio level, core fund sweeps, dividend reinvestment) are not flows. Getting this wrong is the most common way personal return math lies, so the classifier ships with fixtures for every Fidelity action text seen so far.

## Reconciliation and data health

Before metrics are published for a day, the engine checks:

| Check | Pass when |
|---|---|
| Value | Shares × close per account is within $1 or 0.05% of SimpleFIN's account value |
| Shares | The lot export's shares per symbol equal the positions' shares exactly |
| Cash | Change in cash equals flows plus trades plus income, within $0.01 |
| Freshness | Mirror pull under 14 hours old, closes present for every held symbol |

A failed check marks the day `stale`, keeps the last good values on screen with their date, and writes the reason to `data_health`. Agents read `data_health` first and stop if it is not green. The Phase 1 exit test ("numbers match Fidelity to the cent on a test day") is this table passing.

## Metrics catalog

Each metric has an id, a formula, a minimum sample, and scopes (portfolio, account, sleeve, holding). The registry lives in `engine/metrics.yaml`; this table is the plan for it.

### Value and flow

| Id | Metric | Notes |
|---|---|---|
| `value.market` | Market value | Live in market hours, close otherwise |
| `value.day_change` | Day change in dollars and percent | Against the prior close |
| `flow.net_contrib` | Net contributions | External flows only, by window |
| `value.gain` | Investment gain | Change in value minus net contributions. The honest "how much did the market give me" |
| `income.dividends` | Dividend and interest income | Trailing 12 months and by window |
| `cash.share` | Cash share | Core fund and settled cash as a share of value |
| `cash.ready` | Cash ready to invest | Settled core cash minus any margin debit |
| `cash.pending` | Pending deposits | Deposits in flight plus the next scheduled deposit and its date, from the plan |
| `flow.invest_rate` | Investing rate | External investment flows divided by take-home pay (from `paystubs`) |

### Returns

| Id | Metric | Notes |
|---|---|---|
| `ret.twr` | Time-weighted return | Daily linked; flows at end of day. Judges the investments, ignores deposit timing |
| `ret.mwr` | Money-weighted return (XIRR) | Judges your actual dollars, including timing |
| `ret.contrib` | Contribution to return | Weight × return per holding; sums to the portfolio return |

Windows: 1D, 1W, MTD, QTD, YTD, 1Y, 3Y, since start. **Returns under a year are never annualized.** A 9% month shown as 180% a year is noise in a costume.

### Benchmarks and comparison

| Id | Metric | Notes |
|---|---|---|
| `bm.plan_shadow` | Plan-mix shadow portfolio | Every external dollar, on its real date, buys the plan's target weights at that day's close; deposits steer drift the way the plan does; never sells |
| `bm.sp500_shadow` | S&P 500 shadow | Same dollars, same dates, all in an S&P 500 index fund (total return) |
| `bm.excess` | Excess return vs each shadow | In percent and in dollars. Dollars are the headline |
| `bm.tracking_error` | Tracking error | Annualized volatility of daily excess return |
| `bm.capture` | Up and down capture | Against the S&P 500 |
| `bm.active_share` | Active share vs plan | Half the sum of absolute weight differences |

The shadows answer the only question that matters for a personal portfolio: would the same paychecks have done better on autopilot? The cumulative dollar gap to `bm.plan_shadow` is the desk's most important number and feeds the agent scorecard.

### Risk

| Id | Metric | Min sample | Notes |
|---|---|---|---|
| `risk.vol` | Annualized volatility | 63 days | 63-day and 252-day windows |
| `risk.downside_dev` | Downside deviation | 63 days | |
| `risk.mdd` | Max drawdown, duration, recovery | none | Plus `risk.dd_now`, the current drawdown from the high |
| `risk.var95`, `risk.cvar95` | Historical 1-day and 1-month VaR and expected shortfall | 250 days | On short history, uses current weights over five years of holding prices, flagged `pro_forma` |
| `risk.beta` | Beta to the S&P 500 | 252 days | |
| `risk.corr` | Correlation matrix of holdings | 252 days | Feeds the comparison view |
| `risk.sharpe`, `risk.sortino` | Risk-adjusted return | 1 year | Risk-free from FRED. Not shown under a year |
| `risk.top1`, `risk.top5` | Largest one and five weights | none | |
| `risk.eff_n` | Effective number of holdings | none | 1 / sum of squared weights (inverse HHI) |
| `risk.lookthrough` | Look-through exposure | none | Fund weights × N-PORT holdings, so an index fund and a sector fund that both hold the same megacaps show the true overlap |
| `risk.sector` | Sector exposure | none | Through look-through holdings and profiles |
| `risk.factor` | Factor exposure | 3 years | Market, size, value, profitability, investment and momentum betas from the French factors; on holdings' own histories, weighted |
| `risk.scenario` | Scenario shocks in dollars | none | Historical (2008, March 2020, 2022) replayed on current weights, plus set shocks: market −20%, the single-stock satellite −50%, rates +2 points |
| `risk.corr_shift` | Correlation shift | 252 days | 63-day vs 252-day correlation between each holding and the market; flags when diversification is quietly vanishing |

### Margin

| Id | Metric | Notes |
|---|---|---|
| `margin.debit` | Margin debit | From the margin sub-account balance |
| `margin.cost_day`, `margin.cost_month` | Interest cost in dollars | Daily accrual at the rate in `desk.yaml`, assuming a 360-day year until the first margin statement confirms the broker's day count |
| `margin.funded_share` | Margin-funded share of positions | |
| `margin.call_drop` | Price drop to a maintenance call | `1 − debit / ((1 − m) × value)`, with `m` the maintenance requirement (per security where the export gives it, otherwise the setting) |
| `margin.call_price` | Call price for the largest single stock | The price at which that holding alone, with everything else flat, triggers a call |
| `margin.breakeven` | Return a margin-funded position needs to beat its interest | Annual rate × days held / 360 |

### Plan and drift

| Id | Metric | Notes |
|---|---|---|
| `plan.weight`, `plan.drift` | Actual weight and drift in points per fund | Against the active plan version from the mirror |
| `plan.drift_max` | Largest drift, in points, and which fund | The Bridge headline |
| `plan.single_stock` | Single-stock share vs its band | |
| `plan.next_deposit` | Where the next deposit goes | The split that closes the most drift without selling |
| `plan.adherence` | Plan adherence | Share of invested dollars that went to the plan mix, by window |
| `plan.rules` | Rule checks | Single-stock band, no new single stocks, no margin-funded buys, drift over 5 points. Each a pass or fail with the evidence |

### Tax (needs the lot export)

| Id | Metric | Notes |
|---|---|---|
| `tax.lots` | Lots with unrealized gain or loss | Short or long term, days to long term |
| `tax.harvestable` | Harvestable loss | Total and per lot, highest cost first |
| `tax.wash_window` | Wash-sale calendar | 30 days either side of every sale and buy, across the brokerage, HSA and 401(k) (where a fund could be substantially identical, it is flagged for review rather than decided) |
| `tax.realized_ytd` | Realized short- and long-term gains this year | From the realized gain/loss export |
| `tax.offset` | Ordinary-income offset used and carryforward | The $3,000 annual limit |
| `tax.harvest_value` | Tax value of a harvest | Loss × `tax.marginal_rate` |
| `tax.marginal_rate` | Marginal federal and state rate | From Escape Vektor's tax estimate in the mirror, else `desk.yaml`; quality `modelled` either way |
| `tax.lot_realized` | Realized gain or loss per lot sold | Short or long term, with the sale it came from |
| `tax.div_drag` | Tax drag from taxable dividends | |

### Costs

| Id | Metric | Notes |
|---|---|---|
| `cost.expense` | Weighted expense ratio and dollars a year | Expense ratios from fund profiles |
| `cost.total` | All-in yearly cost | Expenses plus margin interest plus estimated dividend tax drag |

### FI progress

| Id | Metric | Notes |
|---|---|---|
| `fi.progress` | Progress to the FI number | The FI number comes from Escape Vektor's plan, never retyped |
| `fi.required_return` | Return needed to hit the target date at the current deposit rate | |
| `fi.date_pctl` | FI date at the 10th, 50th and 90th percentile | Monte Carlo, below |

**Monte Carlo.** Block bootstrap (12-month blocks) of real US market and bond returns since 1926 from the French library, scaled to the plan's mix and fees, with the plan's deposit schedule. Ten thousand paths, fixed seed per run so numbers do not wobble between refreshes. Output is percentiles, not a single date. It repeats history's range; it cannot imagine a worse one, and the page says so.

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

One comparison engine serves every "this vs that" view:

- **Inputs:** two to five series (holdings, funds, benchmarks, shadows, accounts), one window.
- **Alignment:** common trading days, total return (`adjClose`), rebased to 100 at the start.
- **Table:** return, volatility, max drawdown, correlation, beta, expense ratio, yield, look-through overlap, and for accounts, after-tax return.
- **Rule:** a window shorter than both series' histories is never silently chosen; the shorter history sets the start and the view says so.

Standard comparisons: actual vs plan shadow vs S&P 500 shadow; fund vs fund inside a sleeve; any watchlist symbol vs the fund it would replace; Individual vs HSA vs 401(k).

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

## Scoring decisions

The method behind `dec.score_*` and the agents' scorecard.

- **Baseline:** the same dollars into the plan mix. Both sides start at the **next trading day's close** after the decision is recorded (desks run after the close, so the same-day close would be look-ahead).
- **Total return:** dividends reinvested through `adjClose`, the same for both sides.
- **By kind:** a buy is scored as the bought position vs the baseline; a sell or trim as the sale proceeds in the plan mix vs keeping the shares; a `hold_off` by what it avoided (margin interest not paid, a wash sale not triggered); a harvest as realized loss × marginal rate, plus or minus the replacement fund's tracking difference.
- **Per desk:** total excess dollars, hit rate, and a bootstrap 90% interval for the mean excess. With a few dozen proposals the interval will usually include zero, and the scorecard says that rather than ranking noise.
- **Calibration:** Brier score of `confidence` against "beat the baseline at 90 days", plus a calibration table once a desk has 30 scored proposals.

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

1. **Explore.** The strategy desk writes an experiment into `/data/lab/queue/*.json`: a registered spec, a parameter grid inside `params`, a date range, a seed, and a trial budget (default 200 variants per spec). It may also ask for analyses on finished runs: parameter sensitivity, regime splits (bull, bear, high and low rates), factor regression, turnover and cost sensitivity.
2. **Run.** The `lab` service (`python -m desk.lab`, no network, read-only data mounts, writes only to `/data/lab/runs`; see [architecture.md](architecture.md)) runs the grid with walk-forward. Each variant is a row in the trial ledger.
3. **Read.** The next desk run gets the results: walk-forward fold summaries and the analyses, never the holdout or the post-cutoff window. It can tune and resubmit until the trial budget is spent. Every variant raises the bar through the deflated Sharpe ratio, so tuning harder makes passing harder.
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

**The bottleneck is Tiingo's free tier, not the hardware**: 50 requests an hour, 1,000 a day, and 500 unique symbols a month, shared with Escape Vektor. One request returns a symbol's full history, so the desk takes about 400 new symbols a month overnight and leaves the rest for Escape Vektor. Bars are cached forever and only topped up after that. **Backfill starts in roadmap phase 3**, so the large-cap universe is ready when the lab lands in phase 9. ETF and French-portfolio strategies can run from day one of the lab.

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

## Honest limits

Rule backtests (rebalance bands, deposit steering, harvest thresholds, margin rules) use the same lab machinery and the same bars.

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
data_health(as_of, check, status, detail)
preflight(ticket_id, metric_id, before, after, flag)
triggers(as_of, kind, scope_id, detail)
strategies, strategy_trials, paper_positions, paper_trades   (see Strategy lab)
```

- `scope`: `portfolio`, `account`, `sleeve`, `holding`, `benchmark`, `shadow`.
- `quality`: `ok`, `stale`, `pro_forma`, `modelled`, `insufficient_history`.
- `unit`: `usd`, `pct`, `pts`, `ratio`, `days`, `date`.

**Agent brief.** Agents never open the SQLite file. The brief builder ([agents.md](agents.md)) asks the engine for one desk's slice and writes it as that run's `brief.json`: `data_health`, headline metrics, holdings, drift and rule checks, risk, margin, tax (when lots are fresh), active signals and triggers. Every value is `{metric_id, scope_id, window, value, unit, as_of, quality}`. A proposal's `numbers_used[].field` is the key `metric_id:scope_id:window` (for example `plan.drift:FXAIX:now`), so Preflight can match it to the brief exactly.

**Triggers.** The engine writes `triggers(as_of, kind, scope_id, detail)` for the agents' scheduler: margin debit appeared, daily move past the risk dial, concentration band crossed, earnings reported, new lot export. Each fires at most once a day.

**API for the UI.**

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `data_health` for the latest run |
| `GET /api/metrics?ids=&scope=&scope_id=&window=` | Latest values with quality |
| `GET /api/series?id=&scope_id=&from=&to=` | Daily series for charts and drill-down |
| `GET /api/compare?ids=&window=` | Aligned, rebased series plus the comparison table |
| `GET /api/live` | Latest quotes, live value, day change (market hours) |
| `POST /api/preflight` | Before and after metrics for a hypothetical trade |
| `GET /api/lab/strategies`, `/api/lab/strategies/{id}` | Strategy list, status and tear sheet |

**Display rules for design.** Show `as_of` on every KPI; show any non-`ok` quality as a small, friendly tag, not a red error; never annualize under a year; Monte Carlo as percentile lines or markers, not a filled band.

## Compute schedule

| When | Runs |
|---|---|
| Every 5 min, 9:30 to 16:00 ET weekdays | Quotes, live value, day change, intraday drawdown, margin call distance |
| After each mirror (8:00, 17:00 ET) | Reconciliation, holdings, flows, returns, drift, rules, margin, tax (if lots are fresh), brief for the agents |
| Nightly | Tiingo, EDGAR, FRED pulls; risk, correlations, comparisons, signals, scorecard |
| Nightly, after the 17:00 run | Forward paper portfolios step one day; queued lab backtests run overnight under `job_lock("lab")` |
| Monthly | French factors, N-PORT look-through, Monte Carlo refresh, factor regression on holdings with three years or more of history |

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

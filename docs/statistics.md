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
| **Fidelity history** (activity-and-orders JSON dropped in `/data/inbox/fidelity/`) | Every transaction with real quantities, prices, deposits, dividends, splits and margin rows (see [Fidelity history](#fidelity-history)) | Manual. Last 4 digits of each account only | Whenever you export it; the `lots` job (every 15 min) and `daily` import it |
| **Tiingo** (existing key) | Daily OHLC, `adjClose`, `divCash`, `splitFactor` for benchmarks and comparison symbols not already in the mirror | Free tier is personal use; request and unique-symbol caps apply ([docs](https://api.tiingo.com/documentation)) | Nightly, incremental |
| **Finnhub** (existing key) | Live quotes in market hours, earnings calendar, basic financials, insider transactions where the free tier allows | 60 calls a minute; some endpoints are premium, checked at build time | Every 5 min in market hours |
| **Alpaca market data** (paper keys, free plan) | Daily bars for the small-cap universe, raw and split/dividend adjusted, plus the asset list (exchange, tradable) | `data.alpaca.markets` is a fixed constant, read only; the asset list comes from the paper trading host via `desk.paper_check.paper_base()`. SIP feed by default (`DESK_ALPACA_FEED`), 20 minutes behind, so bars end there | Weekdays 19:30 ET |
| **SEC EDGAR** | Filings index, XBRL company facts (revenue, margins, share count), Form 4 insider trades, N-PORT fund holdings | Free; a `User-Agent` with contact details is required (`DESK_SEC_USER_AGENT`), at most 10 requests a second | Nightly for holdings and watchlist |
| **FRED** (free key, `FRED_API_KEY`) | Risk-free rate (3-month T-bill), 10y and 2y yields, CPI, high-yield spread, VIX close | Free key, generous rate limit | Nightly |
| **Ken French data library** | Daily and monthly Fama-French 5 factors plus momentum, US market back to 1926 | Free CSV ([library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.French/data_library.html)) | Monthly |

Escape Vektor's `priceCloses` only refresh when Joshua opens it, so they can lag. Price sources, in order:

| Day | Close used |
|---|---|
| Any day with a Tiingo bar | Tiingo's official close (it wins over the mirror) |
| Any other day | The mirror's close, else the last close before it |
| A snapshot day whose newest close predates its last trading day | The broker's own price (value ÷ shares), unless it equals an older close (a stale snapshot), then the newest close |
| A symbol nothing prices (Empower plan codes) | The snapshot unit price, drawn in a straight line across trading days between two snapshots (flat after the last), `pro_forma`; backfill lists it under `unpriced`, not `errors` |

**Stale snapshots.** A snapshot dates itself by the closes it carries. When at least 60% of its priced holdings match one older close date, it counts as that day's snapshot, so a sync that re-sends Wednesday's positions on Friday cannot undo Thursday's trades or invent a withdrawal. A snapshot that really was taken that day wins a tie.

A held symbol is fetched from Tiingo unless the mirror already has a close for the last trading day. Weekends and holidays resolve to the last trading day.

**Price backfill** (`desk.engine.backfill`, job `backfill`, every hour at 13 past; `ASK_MINUTE` and `ASK_WORDS` hold the schedule and a test ties them to it). Tiingo publishes most closes by 17:30 ET and mutual fund prices after midnight, sometimes the next afternoon, so the desk asks every hour. The day it asks for rolls at 00:00 UTC, so the 19:13 ET run (20:13 in summer) is the first to fetch that day's closes. Minute 13 keeps clear of the deploy check on the 5 minute marks and of `restate` at 2 past them.

| Piece | Rule |
|---|---|
| Who is asked | Held, benchmark, plan and watched names and the scanner's quality list while their newest bar is older than the last trading day; never-fetched names once; the rest every 90 days |
| Public stock list | Role `public`, last in the order. Full history once, then a top-up when a name's last ask is 7 days old, only while Tiingo still lists it as trading. Never asked from 16:00 to 01:00 ET, so the evening run is held, benchmark, plan, watched, quality and library names only. A list name he also holds keeps its own role and its daily refresh |
| Order | By role (held first), never-fetched first inside a role, so a history backlog never delays a held name |
| Nothing behind | The run makes no call and says so |
| An error | Asked again next run; a rate limit or no answer also ends the run. A name is parked only when Tiingo says "no prices" and has never had a bar for it: 7 days, or 20 hours for a held name |
| Result | `fetched`, `advanced` (a new bar landed), `behind` (answered with nothing new for `target`), `unpriced`, `errors`, `left`, and `detail`, one sentence the jobs page keeps |
| Lock | `engine-backfill` only, never `engine-daily`; each name is its own short write, the request itself holds nothing |

**`GET /api/engine/backfill`.** `{target, asks, limits, used, last_run, symbols}`. Each symbol: `symbol, role, priority, daily, first_bar, last_bar, fetched_at, error, parked_until, behind, due`. `last_run` is the newest run's `finished_at, ok, detail` and name lists. Read-only; no account data.

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

**Table shape.** A `WITHOUT ROWID` table must not end on a primary-key column unless every column is in the key. SQLite 3.40.1 (the image's library) reports false NOT NULL errors from `quick_check` on that shape, which fails the backup check and blocks a deploy. `quotes_live` is a rowid table for this reason; `schema.apply` rebuilds an older copy in place, and `tests/engine/test_schema.py` holds the rule.

**Late deletes.** Current holdings always come from the latest snapshot (by `asOf`), so a deleted older snapshot that lingers for a week changes nothing. A lingering deleted activity or transaction row could double a flow; the cash check below catches it, marks the day `stale` and names the row, and the weekly full pass clears it.

| Layer | Where | Tables | Rule |
|---|---|---|---|
| **raw** | `mirror.db`, plus `desk.db` | Mirror: `rows`, `row_history`. Engine: `raw_lot_files`, `raw_api(source, key, body, fetched_at)` | Verbatim, append-only. Lets any later number be recomputed from what was known on the day |
| **core** | `desk.db` | `accounts`, `engine_snapshots` (every snapshot the mirror ever saw, with the one per day used as the anchor), `holdings_daily(date, account, symbol, shares, close, value, cost, reported_value, is_cash, source, anchor, quality)`, `lots`, `cash_flows(date, account, amount, kind, external)`, `prices_daily(symbol, date, close, adj_close, source)`, `benchmarks`, `factors_daily`, `macro_daily`, `fund_holdings(fund, as_of, holding, name, cusip, weight, asset_cat, country, accession)`, `quotes_live(symbol, at, price)`, `closes_provisional` | Normalized, deduplicated, one row per fact |
| **derived** | `desk.db` | `metric_values`, `series_daily`, `signals`, `proposals_scored`, `data_health` | Written by the engine run, tagged with `engine_version` |

**Keep every pull.** Escape Vektor collapses synced snapshots to one per week. `row_history` keeps every version of every snapshot and position the mirror saw (`positions.json.snapshotId` joins to `snapshots.json.id`), so the engine rebuilds `holdings_daily` for every pull and, from the first day the mirror runs, has a daily history Escape Vektor does not. Earlier history is rebuilt the way Escape Vektor's `market.js` does it: the earliest snapshot's quantities rolled forward by activity rows, priced with daily closes, flagged `pro_forma` where no snapshot confirms it. Days before the earliest snapshot come from the Fidelity history (see History before the first snapshot).

**Cash flows.** External flows are deposits, withdrawals, HSA contributions and 401(k) contributions. Internal moves (the margin and cash sub-account journals, transfers between your own accounts at the portfolio level, core fund sweeps, dividend reinvestment) are not flows. Getting this wrong is the most common way personal return math lies, so the classifier ships with fixtures for every Fidelity action text seen so far.

| Activity row | External flow when |
|---|---|
| `deposit`, `withdrawal` | Always (not core, not a cash symbol) |
| `transfer`, `other`, money in | `desk.decisions.plan.is_cash_in`: EFT, ACH, electronic, deposit, contribution, received or wire wording, and no out wording |
| `transfer`, `other`, money out | EFT, ACH, electronic, transfer, withdraw or wire wording |
| Any row with a non-core symbol | Never (share transfers are holdings moves) |

Same-amount opposite moves between two of your accounts within 3 days are internal at the portfolio level.

**Unsettled and margin-funded buys.** Escape Vektor's sync drops pending and margin lines, so a snapshot can show new shares while its cash is unchanged. Left alone, the engine would book the gap as money in and show no margin debit. `holdings.settle` runs over each pair of snapshots:

| Step | Rule |
|---|---|
| Expected cash | The earlier snapshot's cash (after any earlier adjustment) plus every cash move in the activity between the two |
| Gap | Reported cash − expected cash |
| Room | The debit already carried, plus buys in the window whose shares show up in the later snapshot. New buys count only when the Fidelity history covers the whole window, since only then is a missing deposit ruled out |
| Adjustment | The smaller of gap and room, when over $1. The account's cash row is lowered by it and marked `modelled`; `reported_value` keeps what the snapshot said |
| Ends | A deposit or sale in the activity pays it down. A snapshot that carries its own negative cash line is trusted as it stands |

`margin.debit` is `modelled` while it rests on such a row. A gap with no matching buys is still counted as money in or out, as before.

## Reconciliation and data health

Before metrics are published for a day, the engine checks:

| Check | Pass when |
|---|---|
| Value | Shares × close per account is within $1 or 0.05% of SimpleFIN's account value. A price-only gap is `warn` and names the biggest gaps; positions that don't add up are `fail` |
| Shares | The lot export's shares per symbol equal the positions' shares exactly. Rebuilt lots name the method, and warn per symbol where they differ from holdings or the history misses opening shares. A note is kept only for an account whose lots are still rebuilt, so a lot export for that account clears it |
| History | Shows the Fidelity history's dates, rows and accounts, and how many Escape Vektor rows it replaced. Warns when Escape Vektor rows inside those dates have no broker match, or a broker account has no Escape Vektor account with the same last 4 digits |
| Cash | Change in cash equals flows plus trades plus income, within $0.01 |
| Freshness | Mirror pull under 14 hours old |
| Closes | Every held symbol has a close for the last trading day, or is a code nothing prices. A name one session behind warns with when the desk asks again (`backfill.ASK_WORDS`) and nothing to do; more than one session behind points to Backfill in Settings, Box. A held name whose last ask failed or found no prices says so, with when it is asked again |
| Flows | Lists any snapshot-day change that prices and recorded activity don't explain. The engine counts it as money in or out, not return (unlogged deposits, payroll contributions, a margin buy without a debit row). Always `ok`; it's there to explain the number. For an account the Fidelity history covers on that day it says a history lists a day's deposits and dividends a day or two later; it never asks for an upload, because none would clear it that day, and the long form lists accounts with no Fidelity history apart |
| Market keys | Tiingo, Finnhub, FRED, the SEC contact and the Alpaca paper keys are all set; any missing one warns in plain words ("the Tiingo key") and its fix points to Settings, Data, Keys. No health line names a setting variable, a shell command or a file path: fixes point to Settings (Keys and Inbox under Data, job buttons under Box). The words live in `desk.engine.KEY_WORDS` and `key_fix` |
| Symbol kinds | Every holding is known as a fund or a stock: Escape Vektor's profiles, then SEC's fund list, the benchmark ETFs, ticker shape (5 letters ending in X, plan codes with digits) and SEC titles |

Every non-ok detail ends with `Fix:` and the one step that clears it. That detail is the long form, kept for diagnosis; it is not what he reads.

**What he reads, and who fixes it.** Each check also stores a plain sentence, a kind and, where a job can fix it, that job (`data_health.say`, `kind`, `job`). `GET /api/engine/health` serves the plain sentence as `detail` and the long form as `diagnosis`.

| Kind | Means | Counts toward `status` | Examples |
|---|---|---|---|
| `fixes_itself` | The desk is already on it; the sentence says when | No | A fund price not out yet; broker totals from an older price; fund breakdowns not fetched yet |
| `needs_you` | Only a file or a setting of his can clear it, and the sentence names the step that does | Yes, as `warn` | A history whose account names do not match; a lot export; a missing key; the tax rate |
| `blocks` | Numbers cannot be trusted until it clears (every `fail`) | Yes, as `fail` | Accounts not read for over 14 hours; positions that do not add up; no holdings |

| Sentence rule | |
|---|---|
| One or two short sentences a person would say | "Two fund prices for Monday are not out yet. The desk checks every hour." |
| No method, table, column, job or variable names, and no ISO dates | Days read "Monday" inside a week, else "Nov 3" |
| A name where the desk knows one, else the ticker; a count when there are several | `heal.names`, `heal.count` |
| Funds nothing prices (plan codes) are valued at the broker's price and are never a problem | They appear in `diagnosis` only. A fund that files no holdings no longer warns in the look-through check either |

**The desk heals itself** (`desk/engine/heal.py`). After every 5-minute catch-up (`restate`), `heal.run` reads the latest checks and asks for the job of each one that is not ok, through the same request folder the Run buttons use (`jobrun.request_run`, client `desk`). App open or not; a dry run asks for nothing.

| Check | Job asked for | Cool-down |
|---|---|---|
| Freshness, no holdings, positions that do not add up | Accounts (`mirror`) | 1 hour |
| A price never fetched, or more than a day behind | Price backfill (`engine-backfill`) | 1 hour |
| Symbol kinds, company facts | Research (`engine-research`) | 12 hours |
| Fund breakdowns missing or over 150 days old | Look-through (`engine-lookthrough`) | 24 hours |
| Checks written by an older build; or Accounts, Research or Look-through finished after being asked | Daily numbers (`engine-daily`), once, so the checks are read again | 30 minutes |

| Rule | |
|---|---|
| Never asked | While that job is queued, running or waiting its turn, inside its cool-down, or when the scheduler is not running |
| A price one session late | No job: the hourly backfill already asks |
| During the overnight run (23:30 to 06:30 ET) | Only the price backfill is asked for. Accounts, Research, Look-through and Daily numbers wait until 06:30, so a self-asked run can never move the book day or disturb the night's steps |
| After 3 tries | The cool-down is 6 times longer. For prices, and for any `fail`, the sentence adds "The desk has tried 3 times and it has not cleared. Settings, Box shows why." and a `fixes_itself` price check becomes `needs_you` |
| State | `run/heal.json`: per job, when it was asked, how many tries, which checks. A job whose checks are ok again is forgotten |
| Payload | Each check: `check_name, status, detail, kind, counts, job, heal {job, asked_at, attempts, stuck}, diagnosis`. Top level: `status` (fail if any fail, warn if any `needs_you`, else ok) and `kinds` (count per kind) |

**Implied flows.** On each snapshot day, per account: residual = snapshot value − the prior day's holdings repriced at today's closes − recorded deposits and withdrawals − dividends and interest. A residual over $1 or 0.05% is added to that day's flows for the account and the portfolio, so TWR, MWR, day change, shadows and risk see price moves only.

**Roll-forward.** A buy or sell with no quantity (synced rows often have none) moves shares by −amount ÷ that day's close, or the anchor's price. With neither, both legs are skipped, so cash never goes negative on a buy that bought nothing.

**Triggers on a recompute.** Re-running a day replaces its detected triggers: changed details update in place, triggers that no longer hold are withdrawn (`withdrawn` in the run result), and nothing re-alerts. Lot-export triggers are kept.

**Holding moves.** The per-holding `daily_move` trigger uses market closes only (Tiingo bars or the mirror's), dated on the run day, against a close at most 5 days older. Symbols valued at the broker's snapshot price, such as plan codes, never fire it.

**Dry run.** `python -m desk.engine daily --dry-run` (also `holdings`, `core`, `history`) runs on a throwaway copy of the data, sends no alerts, and prints the result plus `health_detail` for every check. Nothing in `/data` changes.

A failed check marks the day `stale`, keeps the last good values on screen with their date, and writes the reason to `data_health`. The daily job's own `health` result uses the same counting as the endpoint. Stale wins over every other flag except `insufficient_history`: a `modelled` or `pro_forma` number from a failed run is stored as `stale`, so nothing acts on it. Agents read `data_health` first and stop if it is not green. The Phase 1 exit test ("numbers match Fidelity to the cent on a test day") is this table passing.

## Fidelity history

`broker.import_inbox` reads `inbox/fidelity/*.json` into `broker_txns`. A file imports once (sha-256), a row once (last 4, `txnNum`, date, type, symbol, quantity, amount and text), and `isCancelled` rows are skipped. Only the last 4 digits of the account number are stored; the account id is the Escape Vektor account ending in those digits, else `individual-NNNN` (`hsa-NNNN` when HSA wording appears). Long digit runs in descriptions are masked.

| Fidelity sub-category | Kind | Cash |
|---|---|---|
| Buy, Sell, Dividend reinvest | `buy`, `sell`, `reinvest` with quantity and price | `depositWithdrawalCode` D is money in, W money out; size is `net` |
| Deposit, Withdrawal | `deposit`, `withdrawal` | External flows |
| Other Cash | `margin_interest` (MARGIN INTEREST), `deposit` (HSA contributions), else a journal | Journals that pair with the same amount in another account within 3 days become a withdrawal and a deposit (internal to the portfolio); other journals (cash/margin sub-accounts) are dropped |
| Dividend Paid, Other Interest | `dividend`, `interest`; IN LIEU rows are `in_lieu` | Income; a core fund's dividend credits cash |
| Taxes | `tax` | A cost, not a flow |
| Reverse Split | `split`, the old shares out and the new shares in, paired by account and date | None |
| Distribution/Split spin-off | `distribution`, shares in | None |

Symbols come from `securityDetail.symbol`, else another row with the same CUSIP, else the ticker in the description, else the other side of the split.

**Broker rows win.** Inside a history's dates (from the fetch window start to its end, per account), an Escape Vektor activity row that matches a broker row (same account and symbol, within 3 days, amount within $0.02 or 0.5%, same sign) is dropped and the broker row used. Unmatched Escape Vektor rows are kept and listed in the History check. Outside those dates Escape Vektor's rows are used as before. Roll-forward, flows, income, the FI deposit average, adherence, wash windows and Preflight all read this merged stream.

**Lots, rebuilt.** `quality` is `modelled`.

| Item | Rule |
|---|---|
| Method | Fidelity's defaults: FIFO for stocks and ETFs, average cost for mutual funds (`sec_type` Mutual Fund, or a 5-letter symbol ending in X). Average cost re-averages the pool at each sale; the holding period is still first in, first out |
| Reverse split | The old symbol's lots move to the new one, shares × new ÷ old, cost and dates unchanged. Cash in lieu is a sale of the fraction with $0 basis |
| Distribution | Of a held symbol: a split (shares scale, cost unchanged). Otherwise new shares at $0 cost, noted in the Shares check |
| Sold before the history | A sale with no lots left books shares with unknown basis; it counts as `unknown` and is left out of realized totals, and the Shares check names the symbol |
| Wash sales | A loss sale with buys of the same symbol within 30 days either side (any account, not the sold lot itself): the loss is disallowed in proportion to the shares bought, and added to that buy's lot cost |
| Precedence | A lot-export CSV wins for its accounts; a realized export wins for its account and year |

**History before the first snapshot.** The first snapshot is only as old as the desk. `holdings.backcast` walks back from it through the Fidelity history, undoing each day's activity, so the value and holdings series start where the history does. Rows carry `source` `history`.

| Item | Rule |
|---|---|
| Accounts | Those in the first snapshot whose history runs from before it to on or after it. Each starts on its own history start. Others are listed under `left_out` and join at the first snapshot |
| Shares and cash | The first snapshot's, minus every buy, sale, split, dividend, deposit and fee after that day. `pro_forma`, the same grade as a rolled-forward day |
| Prices | The close on or before the day. With none, the nearest trade price in the history (else the snapshot price), `modelled`, and the symbol joins the price backfill with role `past`. The `daily` job runs that backfill itself, once per symbol never tried, and rebuilds holdings before the core run, so the first evening already has real closes where Tiingo carries the symbol |
| Opening shares unknown | If undoing a buy takes a holding below zero, the history is missing where those shares went. The holding shows as zero and that account's rows are `modelled` from that day back. Cash that goes negative is `modelled` too |
| An account that starts later | Its opening value counts as money in on that day, not as return |
| Day grade | `modelled` when any back-cast row is, else `pro_forma` |
| Job result | `holdings` returns `backcast {from, days, accounts, left_out, unknown, unpriced}` |

Limits: an account the history does not cover is not in the totals before the first snapshot, so earlier values are smaller than the whole portfolio was. Returns are for the covered accounts only.

Tables: `broker_files`, `broker_txns`, `broker_lots`, `broker_realized` (rewritten by each core run). `desk.decisions` reads the same merged stream with `desk.engine.broker.decision_rows(conn, since)` (`conn` is `desk.db` with the mirror attached), which returns `(id, row)` pairs in the activity shape with `source` set to `broker` on broker rows.

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
| `cash.ready` | Cash ready to invest | Cash you can invest without borrowing: each account's core cash net of its own debit, floored at zero, then summed. Never negative; the debt lives only in `margin.debit`. Also per account (`scope=account`). `modelled` when a cash row is. One helper, `desk.engine.cash.picture`, feeds `cash.ready`, `cash.share` and `margin.debit`, so ready cash minus margin debit is always net cash |
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
| `bm.plan_shadow` | Safe-mix shadow portfolio | Every external dollar, on its real date, buys the reference mix's weights at that day's close; deposits steer drift the way the mix does; never sells |
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
| `margin.cost_day`, `margin.cost_month` | Interest cost in dollars | Daily accrual at one rate from `desk.engine.cash.margin_rate`: `DESK_MARGIN_RATE_PCT`, else the profile's `margin.rate_pct` (`modelled` while that is the built-in default). Assumes a 360-day year until the first margin statement confirms the broker's day count. Preflight and the scorecard use the same rate |
| `margin.funded_share` | Margin-funded share of positions | |
| `margin.call_drop` | Price drop to a maintenance call | `1 − debit / ((1 − m) × value)`, with `m` the maintenance requirement (per security where the export gives it, otherwise `DESK_MARGIN_MAINT_PCT`, default 30) |
| `margin.call_price` | Call price for the largest single stock | The price at which that holding alone, with everything else flat, triggers a call |
| `margin.breakeven` | Return a margin-funded position needs to beat its interest | Annual rate × days held / 360 |
| `margin.interest_paid` | Margin interest charged | From the Fidelity history's MARGIN INTEREST rows; windows `YTD`, `1Y` |

### Plan and drift

| Id | Metric | Notes |
|---|---|---|
| `plan.weight`, `plan.target`, `plan.drift` | Actual weight, target and drift in points per fund | Against the reference mix (below) |
| `plan.in_mix` | Share of value in plan funds | |
| `plan.drift_max` | Largest drift, in points, and which fund | The Bridge headline |
| `plan.single_stock` | Single-stock share vs its band | |
| `plan.next_deposit` | Where the next deposit goes | The split that closes the most drift without selling. Only when a deposit is expected from your activity (auto-detected series or a schedule); the plan's contributions never predict one |
| `plan.adherence` | Plan adherence | Share of buy dollars (activity, core sweeps excluded) that went to plan funds; windows `MTD`, `QTD`, `YTD`, `1Y`, `ITD` |
| `plan.rules` | Rule checks | Single-stock band, no new single stocks, no margin-funded buys, drift over 5 points, conviction holds (pass while the symbol's weight sits inside `band_min_pct`–`band_max_pct`). A conviction symbol is exempt from the single-stock band and from no new single stocks. Unit `flag`: 1 holds, 0 broken. It is not a count |
| `plan.rule_breaks` | What breaks a rule | Per rule, how many things break it (margin-funded buys in 30 days, stocks outside a band, funds past the drift limit). 0 whenever `plan.rules` is 1. The plain sentences sit in the `rules` view and in the `rule_breach` trigger's `detail {breaks, what}` |

**Reference mix.** `core.reference_mix(plan)` gives the weights these metrics are measured against: the Escape Vektor plan when the mirror has one, else the built-in safe mix (`catalog.SAFE_MIX`). `GET /api/engine/reference` returns `{as_of, source (plan or safe_mix), name, weights, judged, note}`.

| On the built-in mix | What happens |
|---|---|
| `bm.plan_shadow`, `bm.excess`, `bm.tracking_error` | Run on the mix, FXAIX and FTIHX as IVV and VXUS, the same weights the catalog's Safe mix uses |
| `plan.target`, `plan.drift`, `plan.drift_max`, `plan.in_mix`, `plan.adherence` | Run on the mix, flagged `modelled`. A distance from a yardstick, not a to-do |
| `plan.next_deposit` | The split that would close the gap to the mix, `modelled`. One reference for the Plan keeper; its deposit route is still judged against your risk band |
| `plan.rules` drift check | Not judged, so no rule fails and no alert fires for being away from the mix |
| `bm.active_share`, the scorecard's plan return and off-plan gap, replay's broad-fund list | Run on the mix |
| Preflight, the FI path, fund look-through, the lab export | Unchanged: they read the Escape Vektor plan only |

### Tax (needs the lot export or the Fidelity history)

| Id | Metric | Notes |
|---|---|---|
| `tax.lots` | Lots with unrealized gain or loss | Short or long term, days to long term. Totals ship as `tax.unrealized_st` and `tax.unrealized_lt` |
| `tax.harvestable` | Harvestable loss | Total and per holding: losses at or over `tax.harvest_threshold_usd` (default $250) with no buy in the last 30 days |
| `tax.wash_window` | Wash-sale calendar | Days until each symbol's window clears (scope `holding`). Windows open on every loss sale and every buy (activity, reinvests and lots acquired in the last 30 days), across all accounts unless `tax.wash_sale_accounts` narrows them. S&P 500 and total-market trackers that could be substantially identical are flagged for review rather than decided. Served by `GET /api/engine/wash` |
| `tax.realized_st`, `tax.realized_lt`, `tax.wash_disallowed` | Realized short- and long-term gains this year, and disallowed wash losses | From the realized gain/loss export, else the lots rebuilt from the Fidelity history (`modelled`), window `YTD` |
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

Tables: `sec_tickers`, `filings` (last two years, with archive links), `fundamentals` (one row per concept and period), `macro_daily`, `earnings`, `insider_trades`. The `research` job runs at 00:40, refreshes each symbol at most every 20 hours, keeps SEC at about 8 requests a second, and skips any source whose key is missing. `GET /api/engine/research?symbol=` serves filings, facts, earnings, insiders, signals and `filing_signals` (the last 3 scored filings, newest first; `in_lane` when a filings lane bought on that score, `lane_open` while it still holds it); `GET /api/engine/macro?start=` serves the FRED series.

### Costs

| Id | Metric | Notes |
|---|---|---|
| `cost.expense`, `cost.expense_usd` | Weighted expense ratio and dollars a year | Expense ratios from the plan's funds; scope `holding` carries each fund's ratio |
| `income.yield` | Trailing dividend yield | Scope `holding`, window `TTM`, from Escape Vektor's symbol profiles |
| `cost.total` | All-in yearly cost | Expenses plus margin interest plus estimated dividend tax drag |

### FI progress

| Id | Metric | Notes |
|---|---|---|
| `fi.progress` | Progress to the FI number | The FI number comes from Escape Vektor's `fi` pref; when that is missing, from the desk profile's `fi` section (`desk.decisions.profile.fi_goal`) |
| `fi.required_return` | Return needed to hit the target date at the current deposit rate | |
| `fi.date_pctl` | FI date at the 10th, 50th and 90th percentile | Monte Carlo, below |

**Monte Carlo.** Block bootstrap (12-month blocks) of real US market and bond returns since 1926 from the French library, scaled to the plan's mix and fees, with the plan's deposit schedule. Ten thousand paths, fixed seed per run so numbers do not wobble between refreshes. Output is percentiles, not a single date. It repeats history's range; it cannot imagine a worse one, and the page says so.

**As built (phase 11).** `desk.engine.fi`, inside every core run (about 1.5 s for 10,000 paths of 50 years).

| Input | From |
|---|---|
| FI number, target date | Escape Vektor pref `fi`: `fiYearlySpend × fiMultiple`, birth date plus `fiTargetAge`. Fallback: the desk profile's `fi` section |
| Real or nominal | The same pref's `inflationAdjusted` and `inflation`; real paths deflate each month at that rate |
| Start value | `value.market` (the desk's accounts only) |
| Deposits | Your net external cash flow (deposits and transfers in, minus withdrawals and transfers out) over the trailing 12 months ÷ 12, or ÷ the months since your first deposit when there are fewer, floored at 0; the view says "from your last N months of deposits, net of withdrawals". None seen: no deposits (caveat). The plan is not used |
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

## Rule replays

`desk.engine.replay` replays the imported Fidelity history under a different rule and reports "you versus the capped you". It runs inside the daily core pass and is stored as the `replay` view (`GET /api/engine/replay`). It needs the history import and S&P 500 prices; every traded name joins the price backfill with role `past`, the same role the back-cast uses.

| Family | Variants | What changes |
|---|---|---|
| `house` (headline) | No single name over 10% of the account, nothing on margin | Position cap plus no margin |
| `buy_cap` | 5, 10, 15, 20% | A single-name buy larger than the cap is cut to it |
| `position_cap` | 5, 10, 15, 20% | A buy is cut so the name stays under the cap, counting what is already held |
| `stop` | 15, 20, 25, 30% | The name is sold at the first close that far under the average price paid; later buys start a new position |
| `trend` | 200 days | A single name is sold at the first close under its 200-day average and not bought while under it |
| `no_margin` | one | The part of any buy that cash could not cover is not bought; margin interest falls with the debit |
| `long_term` | one | A sale of shares held under a year waits until a year and a day after the buy, then sells at that close |

| Convention | Detail |
|---|---|
| Same dollars, same dates | Deposits, withdrawals and every other trade stay as they were. One replay changes one rule |
| The index is the other side | Every dollar a rule moves goes into, or comes out of, the S&P 500 (first of `SPY`, `FXAIX`, `VOO`, `IVV` with prices, total return). A rule that leaves you short of what you really had carries that gap at the index's return |
| Later sales scale | When you sold a share of a position, the replay sells the same share of whatever it holds, and dividends follow the shares held |
| Single names | Everything except mutual funds, plan funds and the broad index and sector ETFs the desk benchmarks against. Commodity, leveraged and thematic ETFs count as single names. Funds are never capped or stopped |
| The account | Cap percentages are of everything in the history's accounts on the day of the buy, after that day's deposits and sales |
| Margin | Per account. Same-day sales and deposits count before buys, so a swap is not a margin buy |
| Prices | Raw closes with the history's own splits; the 200-day average uses adjusted closes. A name without prices sits at its last trade price and no rule touches it (`pro_forma`, `status: partial`) |
| Old positions | Shares sold but never bought inside the history are seeded on the first day at no cost and left out of the tax lines (`modelled`) |
| Tax lines | Short and long-term realized gains on the stock legs in taxable accounts, FIFO, times the marginal rate and 15% federal plus state. Index trades are not taxed. End values are before tax |
| Check | The replayed "you" is compared with today's holdings in the same accounts; a gap over 1% marks the view `modelled` |

View shape: `{as_of, status, quality, start, end, index, accounts, headline, dates, you{end_value, values, realized, tax_usd, holdings_value, gap_usd}, index_only{end_value, values}, sizing{buys, median_pct, over_10, on_margin, largest}, margin{days, peak_usd, interest_usd}, tax_rates, variants[], unpriced, notes, note}`. Each variant: `{id, family, label, params, end_value, change_usd, change_pct, helped_usd, hurt_usd, by_symbol[{symbol, usd}], actions, moved_usd, events[{date, symbol, what, usd}], realized, tax_usd, tax_change_usd, values}`. `values` line up with `dates` (weekly plus the last day). `by_symbol` adds up to `change_usd`. `events.what` is `cap`, `margin`, `stop`, `trend` or `wait`.

Selection against size: `variant.end_value - index_only.end_value` is what the picks earned at the capped size; `you.end_value - variant.end_value` is what the extra size added or cost.

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
| Latest N-PORT | The fund's own filing list (EDGAR company browse by series id, `NPORT-P`, atom), so one document is fetched however many funds the trust has | If that list is empty: the trust's submissions, up to 40 documents a run, skipping documents already known to be another fund's (`nport_filings`), so each run gets further. Refreshed every 30 days |
| Not on the fund list | A one-fund trust listed as a company (SPY, QQQ) is read from its own `NPORT-P` filings, whatever series they name | If it has none, `STAND_INS` reads a fund on the same index in its place (SPY through VOO or IVV); the job result lists `stand_ins` |
| Not found | The run logs the miss (`api_calls`, provider `nport_miss`) and tries again next week | The health line promises a fund only until a run has looked for it; after a miss it reads ok and says the fund counts as one holding |
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
| Conviction hold | A buy of the symbol that ends above `band_max_pct`, or any margin-funded buy of it (also breaks the hold in Plan rules). The symbol is left out of the single-stock band and the satellite total | Nothing; inside or under the band is ok |
| Drift after | | Largest drift grows past the drift limit |
| Funding | A buy is margin-funded or cash runs short, with the monthly interest in dollars and the drop to a call. Cash and debit come from the same `desk.engine.cash.picture` as `cash.ready` and `margin.debit`, so "Cash covers" is the account's ready cash. A cash buy with no account named is checked against the account holding the most ready cash | |
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

## Filings lane: data

Forward-only test of one edge: Claude reads filings of small caps nobody covers. The engine supplies the universe, the filings and the signal table; the agents' scorer fills the signals.

| Piece | Module | Rule |
|---|---|---|
| Universe | `desk.engine.universe`, table `universe_daily(date, symbol, cik, name, exchange, close, shares, shares_end, market_cap, dollar_volume)` | Alpaca asset on NYSE, Nasdaq or NYSE American, tradable, a plain 1 to 5 letter ticker, with a SEC CIK; not in SEC's fund list; name without ETF, fund, ADR, depositary, warrant, unit, right, preferred, notes or SPAC wording. Market cap = SEC `dei:EntityCommonStockSharesOutstanding` (latest of the last 3 quarterly frames, under 400 days old) × that day's raw close, $50M to $2B. 20-session median close × volume at least $500K, with at least 15 sessions and a bar on the day. Each night writes its own date; past dates are never rewritten |
| Bars | `desk.engine.alpaca`, table `alpaca_bars(symbol, date, open, high, low, close, adj_close, volume, vwap)` | 45 days for a new symbol, then a 7-day overlap. `close` is raw, `adj_close` is split and dividend adjusted |
| Filings | `desk.engine.filings`, table `filings_feed` | EDGAR's daily `master.idx` for each weekday since the last good day (at most 10 back), filtered to universe CIKs and to 8-K, 10-Q, 10-K (and amendments), S-1, S-3, 424B*, Form 4. Each company's submissions JSON adds the acceptance time (`filed_at`), 8-K item numbers, primary document and SIC sector. Up to 120 excerpts a night, most material first: the primary document as plain text, first 12,000 characters, three tries |
| Materiality | `filings.materiality(form, items)` | 8-K by its weightiest item (1.03 bankruptcy 10, 3.01 delisting and 4.02 non-reliance 9, 2.01 and 3.02 8, 2.02 and 2.06 7 …), S-1/S-3/424B 6, 10-K 5, 10-Q 4, Form 4 3; amendments one less |
| Signals | table `filing_signals(accession, symbol, filed_at, form, items, scored_at, model, direction, confidence, event_type, horizon_days, rationale, numbers_cited, run_id)` | Point in time, never backfilled. The lane starts at the first `scored_at` (`filings.lane_start(conn)`) |

**The scorer's seam.**

| Call | Does |
|---|---|
| `filings.pending(cfg, limit)` | Unscored filings with an excerpt, most material first, then newest: `accession, symbol, form, items, filed_at, url, excerpt, company{name, market_cap, sector}`. `[]` before the first fetch; `NotReady` when the tables don't exist |
| `filings.record(cfg, accession, result)` | First write wins per accession. `ValueError` on a direction outside −2..2, confidence outside 0..1, an `event_type` not in `filings.EVENT_TYPES`, `horizon_days` under 1, no `model` or `scored_at`, or an unknown accession. `rationale` is cut to 280 characters |

## Insider-buying clusters: data

Backtestable small-cap family: directors and officers buying their own stock on the open market. Module `desk.engine.insider`, job `insider` nightly 23:20 ET.

| Piece | Table | Rule |
|---|---|---|
| Bulk history | `insider_buys`, `insider_quarters` | SEC Insider Transactions data sets, one zip per quarter from 2016 Q1 (Alpaca bars start 2016), 8 quarters a night until caught up. Form 4 and 4/A, transaction code P, acquired, shares and price above 0, owner is a director or officer (10% owners alone are left out). One row per filing and owner: shares, dollars, latest trade date, filing date |
| Live | `insider_buys` (`source` form4), `insider_form4_seen` | Form 4s in `filings_feed` (universe names) after the last bulk quarter: the raw XML, same rules, 200 a night. Bulk rows replace them when the quarter is published |
| Known date | | The session after the filing date. Nothing counts before then |
| Prices | `alpaca_bars`, `alpaca_history` | Names with any director or officer buy since 2016, cluster names (2+ insiders within 30 days) and IWM first: daily bars since 2016-01-01 (raw and adjusted), 300 names a night in batches of 25, each batch saved as it lands so a stopped run keeps its progress. Roughly 2,500 rows a name. The job's five steps (clean, bulk files, live Form 4s, share counts, price history) fail one at a time: an SEC or Alpaca error or a dropped connection in one step is written to that step's `error`, the others still run, and the job exits 1 with every error in `error` |
| Symbols | | `insider.clean_symbol`: quotes and exchange prefixes stripped, a ticker in brackets used, class shares written `BRK.B`; anything else (names, numbers, `--`) is dropped, at parse time and from stored rows at the start of each run. A batch Alpaca refuses is split until the one bad name is found; that name is skipped and listed in the job result with Alpaca's path and message |
| Share counts | `sec_shares`, `sec_frames` | SEC `dei:EntityCommonStockSharesOutstanding` frames since late 2014, each quarter once (the last two refresh) |
| Membership | `smallcap_months` | At each month's first session: shares from a period ending 45+ days earlier (under 400 days old) × raw close between $50M and $2B, and median dollar volume over the prior 20 sessions at least $500K. The whole month uses that answer |

**In the lab.** `lab-export` adds tables `insider(symbol, known, owner, usd)` and `smallcap(symbol, month)`, and the member names' bars (kind `stock`, role `small_cap`, Tiingo wins where both exist).

| Feature | Value on day d |
|---|---|
| `insider.buyers` | Distinct insiders with a buy known in the window's sessions up to d |
| `insider.buy_usd` | Dollars of those buys |

A cluster rule is `{"metric_id": "insider.buyers", "window": "21d", "transform": "raw"}` with `{"min_signal": 1}` (two or more buyers). Names come from SEC filings, not today's listings, so companies that later vanished stay in; a name whose bars stop more than 10 sessions before the data ends sells at its last close less the lab's haircut. Before the first history load a `small_caps` spec is refused with "the engine's insider job builds it". `desk.engine.lab.universe_ready(cfg, kind)` answers the same question without a spec: true once the lab data holds rows for that universe (`small_caps`, `french`, `fund_list`; for `screen`, a symbol with role `public`).

**Survivorship.** Free bars can miss names that died. `lab-export` writes `insider.coverage(conn)` into the lab settings: cluster names that are priced, unpriced (history fetched but no bars within a week of the first cluster), still pending, and priced names that stopped trading within a year. Finalize on a `small_caps` spec adds two bars and a `survivorship` block with the counts:

| Bar | Passes when |
|---|---|
| `price_coverage` | Nothing pending and at most 5% of cluster names unpriced; otherwise `null`, so the verdict is at best inconclusive |
| `delist_total_loss` | The holdout, rerun with every delisting sold at zero instead of the usual 30% haircut, still beats the benchmark |

The counts and the stressed excess also go into the verdict's caveats.

## Post-earnings drift: data

Second small-cap family: prices keep drifting after a big earnings change. Module `desk.engine.earnings`, job `earnings` nightly 23:50 ET, same `small_caps` universe and survivorship bars.

| Piece | Table | Rule |
|---|---|---|
| EPS | `eps_facts` | SEC `companyconcept` `us-gaap/EarningsPerShareDiluted` (basic if none) per company, from 10-Q and 10-K only, the first-filed value for each period (restatements ignored). Quarters are 80–100 day facts; Q4 = the fiscal year less its three quarters |
| News time | `earnings_releases` | 8-K item 2.02 acceptance times from the submissions JSON (recent plus older files since 2015). The quarter is known at the first 2.02 release after the period end and within 50 days before the 10-Q/10-K, else the filing date; then the next open (before 9:30 ET counts that day) |
| Companies | `earnings_ciks` | Insider names that have price history, plus today's universe; 300 a night; refreshed every 30 days |
| Events | `earnings_events` | Since 2015: (EPS − EPS of the quarter ending about a year earlier) ÷ the close before the known day; closes under $1 skipped |

| Feature | Value on day d |
|---|---|
| `earnings.surprise` | The latest event's surprise, if it was known inside the window |
| `earnings.days_since` | Sessions since that event, if inside the window |

A drift rule is `{"metric_id": "earnings.surprise", "window": "63d", "transform": "rank"}` with `top_n` and `min_signal: 0`. `lab-export` adds table `earnings(symbol, known, surprise)` and `earnings_coverage` (companies wanted, priced, unpriced, pending, ended within a year, events); a drift spec's verdict uses that count for `price_coverage`.

## Paper trading: lanes, sub-ledgers, leaderboard

Every strategy on paper shares the one Alpaca **paper** account. The URL comes only from `desk.paper_check.paper_base()`; the account number must start with `PA` or nothing is sent.

| Piece | Module | Rule |
|---|---|---|
| Lanes | `desk.engine.lane` | Forward-only filing strategies. `filings-lane` v1: score ≥ +1, confidence ≥ 0.6, next open after `max(scored_at, filed_at)`, hold 20 sessions, 10 equal slots, $1,000 notional, benchmark IWM. Starts at the first score |
| Lane variants | `lane.register(conn, id, title, params)`, `lane.register_variant(cfg, …)`, table `lane_variants` | Params `min_direction` 1–2, `min_confidence` 0.5–0.95, `hold_sessions` 5–60, `max_names` 3–20, `event_types` from `filings.EVENT_TYPES`. Same id again = next version (the latest runs). Duplicate params refused; at most 12. A variant starts at its registration and ignores signals known before it |
| Forward record | `paper_portfolios`, `paper_positions`, `paper_trades` | Lanes rebuild after each universe and paper run; lab strategies replay nightly (`lab-export`). Status comes from the paper gate below, never from the night's excess |
| Sub-ledgers | `paper_exec.books`, tables `paper_legs`, `paper_ledger_daily` | Each strategy has its own sleeve (`DESK_PAPER_BUDGET`, default $1,000, cap $5,000), holdings and cash built only from its own filled legs, never from account positions |
| Orders | `paper_exec.run` | Before the open only, once per day. Lanes buy whole shares per slot and sell on exit; lab strategies follow `paper_positions` weights × the sleeve's value, rebalancing a name only when it moves $25 or 10%. Retired strategies flatten. Legs net into one market day order per symbol (`vd-{day}-{symbol}-{side}`), so strategies never trade against each other on Alpaca; a sell never exceeds the account's shares. Names Alpaca can't trade are skipped and listed |
| Fills | `paper_exec.allocate` | Filled quantity goes to same-side legs pro rata at the average fill price; crossed quantity fills at that price too, or at the day's open when the symbol netted to zero. Rejected orders leave the books alone |
| Limits | env | `DESK_PAPER_EXECUTE=0` stops orders (reconciling continues); `DESK_PAPER_MAX_STRATEGIES` (default 20) |

### Paper gate

`desk.engine.gate`. Half a year of paper proves the plumbing, not the edge, so the gate is a stored verdict against a noise band and every row carries the chance its lead is luck.

| Piece | Rule |
|---|---|
| Checkpoints | Day 182 from the start, then every 91 days. A verdict uses only the days up to its checkpoint date, so a late run decides the same thing |
| Stored once | Table `paper_verdicts` (strategy_id, version, checkpoint, as_of, verdict, reason, excess_pts, band_pts, retire_pts, luck, tracking_error_pct, obs, events, family_size, decided_at). A row is never rewritten. Status is the latest verdict: `eligible`, `unproven` (stays `paper`) or `retired`. A retire is final; nothing changes between checkpoints |
| Noise | Daily excess return against the row's own benchmark. `noise_pts` = its standard deviation × √days × 100; `score` = cumulative excess ÷ noise; `tracking_error_pct` is the yearly figure |
| Chance it is luck | `luck_alone` = 1 − Φ(score): how often a strategy with no edge would lead by this much. `luck` = 1 − (1 − luck_alone)^k for a family of k tries |
| Family size k | Lanes: every lane variant ever registered plus the default. Lab strategies: paper strategies sharing a family key (`insider-`, `drift-`, `filings-`) or a `parent_id` root. Mixes: 1 |
| Pass | `luck` ≤ 0.10, so excess ≥ `band_pts` (1.28 × noise for one try, wider for a family, never under 1 point), plus 30 buys by the checkpoint (lanes and lab strategies) and a lab pass on every backtest bar (lab strategies). Reasons when it does not pass: `noise`, `events`, `bars`, `short_record` (under 60 priced days) |
| Retire | Excess ≤ `retire_pts` (−1.28 × noise, never inside 1 point) at a checkpoint. A superseded mix version still retires at once |
| Summary | Each `paper_portfolios.summary` carries `benchmark` and `gate`: `{luck, luck_alone, luck_bar, family_size, score, tracking_error_pct, band_pts, retire_pts, obs, events, min_events, bars, checkpoints, next_checkpoint: {day, on}, verdict: {checkpoint, as_of, verdict, reason, excess_pts, band_pts, retire_pts, luck, events}}` |

Chance of each verdict at day 182, simulated (40,000 paths). The old rule (excess ≥ 0) passed a strategy losing 5 points a year 33 to 44% of the time.

| True yearly edge | Tracking error 8%: pass / retire | 15% | 25% |
|---|---|---|---|
| −5 pts | 4% / 20% | 7% / 15% | 8% / 13% |
| 0 | 10% / 10% | 10% / 10% | 10% / 10% |
| +5 pts | 20% / 4% | 15% / 7% | 13% / 8% |
| +10 pts | 34% / 2% | 21% / 4% | 16% / 6% |

Most rows stay `unproven` at day 182 and go on to the next checkpoint. Over seven checkpoints (two years) a strategy with no edge is eligible at some checkpoint about 24% of the time, so `eligible` means "worth a decision", not "proven".

**`/api/engine/lab/leaderboard`.** `{as_of, benchmark: "IWM", gate_days: 182, step_days: 91, young_days: 60, luck_bar: 0.1, groups, rows, note}`. `groups`: `[{benchmark, rows, racing}]` in display order (largest group first). Each row: `id, version, name, kind ("lane" | "mix" | "strategy"), benchmark` (its own: IWM for lanes and small-cap strategies, IVV for mixes, the spec's benchmark or `Plan mix` for other lab strategies), `status, started, as_of, days_live, young` (under 60 days), `checkpoint_day, checkpoint_on, days_to_checkpoint` (the next verdict; null once retired), `return_pct, bench_return_pct, excess_pts, score, luck, tracking_error_pct, band_pts, gate` (the summary's gate, or null), `max_drawdown_pct` (negative), `trades, open_positions, account` (`{as_of, sleeve, cash, value, return_pct}` from the sub-ledger, or null). `reward_risk`: `{source, days, ann_return_pct, sharpe, sortino, max_drawdown_pct, calmar, hit_rate}` from the sub-ledger's daily values once it has 20 days (`source: "sub_ledger"`; hit rate = share of up days, Sharpe and Sortino annualized on 252 days, annual return and Calmar from 63 days), else from the forward record (`"forward_record"`; a lane's hit rate is its share of winning closed trades), else nulls. `backtest`: the same keys plus `start, end` from the mix's real-price backtest in the bands (`"bands"`) or a lab strategy's holdout (`"lab_holdout"`), or null. Order: by benchmark group; inside a group eligible, paper, retired; then rows of 60 days or more before younger ones; then `score` desc (nulls last), then days live desc. Raw excess never ranks: a 20-day row cannot outrank a 150-day row. Empty: `rows: []` and a note. Returns and the gate use the forward record; `account` shows what the paper fills did.

## Strategy catalog and probability bands

There is no single target. Four named mixes run side by side on paper and in the bands, and each is scored against his risk band and against the others. `desk.engine.catalog` defines them; `desk.engine.bands` measures them.

| id | Name | Mix | Paper |
|---|---|---|---|
| `safe-mix` | Safe mix | Built in (`catalog.SAFE_MIX`), his October index plan: FXAIX 40, SCHD 20, FTIHX 10, FTEC 10, and NLR, GRID, ICLN, UFO 5 each. FXAIX trades as IVV and FTIHX as VXUS. It does not read the Escape Vektor plan | Rebalances when a name moves $25 or 10% |
| `as-held` | As held | His book today, ASTS kept, cash share kept, margin debit left out. A drifting hold (`policy: "hold"`): nothing sold, nothing topped up | Buys his weights once, then holds those shares (same version). `paper_positions` shows what the sleeve holds |
| `tech-tilt` | Aggressive tech tilt | 50% IVV, 30% FTEC, 10% SMH, 10% VXUS (proposal) | As safe mix |
| `dip-buy` | Dip-buy | Safe mix with 20% cash; a third goes in at each 5, 10, 20% drop of IVV from its high; back to 20% cash at a new high | Cash target from IVV's closes |

| Piece | Rule |
|---|---|
| Proxies | Mutual funds trade as ETFs on Alpaca: FXAIX → IVV, FSKAX/FZROX → ITOT, FTIHX/FZILX → VXUS, FXNAX → AGG, VFIAX → VOO, VTSAX → VTI, VBTLX → BND, and a few more in `catalog.PROXIES`. A fund or 401(k) code with no twin trades as IVV, and the row says so in `proxy_note` |
| Registry | `catalog_strategies` (id, version, title, mix, registered_at, retired_at). The daily engine syncs it. A fixed mix whose weights move more than 0.5 points gets a new version; the old one retires and flattens. Each mix's symbols join the price backfill |
| Paper | `catalog.rebuild` runs in each paper job before orders. It writes targets to `paper_positions` and the record to `paper_portfolios` (kind `mix`, benchmark IVV) from the sub-ledger's values. The paper gate applies at its checkpoints, so a mix is not flattened for dipping under IVV |
| Price history | For each proxy, whichever of the proxy and the funds it stands for has the longest prices. The record starts in the first month where 80% of the weight has real prices; missing months use the US market, noted per symbol |
| Model | Monthly excess return regressed on the US market over that record: beta plus leftover swings. Alpha is dropped (reported as `alpha_dropped_pct`) |
| Simulation | `DESK_BANDS_PATHS` paths (default 2,000), fixed seeds: one stream for the market blocks, so every mix and policy walks the same market paths, and one for leftover swings. 12-month blocks of French monthly market history since 1926; each month adds a leftover swing drawn from the fit. The start is his market value; each month adds his trailing net deposit (the FI rule); today's dollars when his FI goal says so |
| As held | Fitted holding by holding (`bands.held_sleeves`): each single stock or conviction hold with 2% of the book and 36 months of prices is its own sleeve (six at most), the funds and the rest are one sleeve, cash earns the bill rate. Sleeves drift. New money goes to a `new-money` sleeve on the safe mix's fit (the rest of the book when there is no plan). The old model, topped back up to today's weights each month, stays as `variants[0]` (`id: "rebalanced"`) |
| Fees | Every mix pays its funds' yearly expense ratio: the plan's figure when it lists the fund, else `catalog.EXPENSE_PCT`, else its ETF twin's; single stocks pay nothing. Taxes and the margin debit are not modelled |
| Lower-return case | The same paths with `premium_cut_pts` (2) a year taken off what stocks earn over cash, scaled by each sleeve's beta. Stored under `lower` on each row |
| Time to FI | For each level in `deposit_ladder` ($500 to $10,000 a month, plus his own), the months until each path first holds the FI number. Start holdings and the deposit stream are tracked apart, so one set of paths prices every level |
| Conviction holds | For each conviction hold that has its own sleeve: hold, rebalance (back to today's weight monthly) and trim (sold back to `band_max_pct` whenever it grows past it, proceeds to new money), over `policy_years` on the same draws |
| Risk rank | 1–5: the first band whose `worst_year_loss_pct` covers the mix's 1-year p10. Ladder from `desk.decisions.risk.BANDS` when present, else 10/18/25/33/45 |
| Fit | Against `desk.decisions.risk.current(cfg)`: `above` when the 1-year p10 loses more than his band allows, `below` when it fits the band under his, else `fits`. Null until he answers |

**`GET /api/engine/bands`.** `{as_of, status, book: "as-held", rows, convictions, start_value, monthly_deposit, deposit_source, deposit_note, deposit_ladder, fi_number, target_date, fi_years_max: 40, real, horizons: [1, 5, 10, 20, 40], policy_years: [1, 5, 10, 20], premium_cut_pts: 2, paths, history, ladder, ladder_source, profile, method, caveats}`. Rows run safe → risky. Each row:

| Field | Meaning |
|---|---|
| `id, name, weights, cash, priced_from, status` | `status` `not_ready` with a note when under 36 months of prices |
| `risk_rank, fit` | Above |
| `bands[]` | Per horizon: `years, p10, p50, p90` (dollars), `contributed`, `chance_loss` (time-weighted return below zero), `chance_below_contributed`, `return_p50_pct` (a year) |
| `worst_year_p10_pct, cvar95_1y_pct` | p10 and the mean of the worst 5% of 1-year returns over each path's first 10 years |
| `drawdown_10y, max_drawdown_pct` | p10/p50/p90 of each path's worst 10-year drawdown; `max_drawdown_pct` is the p50 |
| `p50_value_10y, chance_fi` | Median 10-year value; share of paths at the FI number by his target date (null without a goal) |
| `fi_years` | `{p10, p50, p90}`: years until 1 in 10, half and 9 in 10 paths hold the FI number at his deposit; null past 40 years or without a goal |
| `fi_time[]` | Per `deposit_ladder` level: `deposit, years_p10, years_p50, years_p90, chance_by_target` |
| `lower` | The lower-return case: `risk_rank, worst_year_p10_pct, cvar95_1y_pct, max_drawdown_pct, drawdown_10y, p50_value_10y, chance_fi, fi_years, bands, fi_time` |
| `policy` | `hold` for as held, `rebalance` for the fixed mixes |
| `sleeves, new_money, variants` | As held only. `sleeves[]`: `id` (symbol, `rest`, `cash`, `new-money`), `weight, beta, resid_vol_pct, fee_pct, months`, and `holds` or `to`. `variants[]`: `id, name` plus the `lower` keys without `fi_time` |
| `backtest` | On real prices: `start, end, months, cagr_pct, vol_pct, sharpe, sortino, max_drawdown_pct, calmar, worst_year_pct, hit_rate` |
| `long_history` | Beta replayed since 1926 without leftover swings: `cagr_pct, max_drawdown_pct, worst_year_pct` |
| `model, fee_pct, proxy_note, notes` | Fit details (start-weighted across sleeves for as held), the yearly fee charged, and every substitution |

`convictions[]`: `symbol, status, weight_pct, band_min_pct, band_max_pct, beta, resid_vol_pct, months, policies`. Each policy: `id` (`hold`, `rebalance`, `trim`), `name, rule`, the `lower` keys without `fi_time`, and `bands[]` per `policy_years` with `weight_pct: {p10, p50, p90}`, the position's share of the book. `status: "not_ready"` with a `note` when the symbol has no sleeve of its own. A stock plan reads its symbol's entry here.

Metrics `bands.worst_year_p10`, `bands.p50_10y`, `bands.chance_fi` (scope `strategy`). For the agents, `bands.catalog(cfg)` returns `{id, name, risk_rank, fit, worst_year_p10_pct, p50_value_10y, chance_fi, sharpe, max_drawdown_pct, proxy_note}` per ready row, and raises `bands.NotReady` before the first build.

Limits: leftover swings are drawn month by month and holding by holding, so a fund's own long slumps and stocks that fall together are understated. Bond and international funds enter only through their link to the US market. Taxes and the margin debit are not modelled. A single stock's middle path falls over time when alpha is dropped and its swings are large; that is the model, not a forecast of the company.

## Discount-day scanner

Module `desk.engine.discounts`, job `discounts` weekdays 17:40 ET, after the close and the 17:20 engine run. The `backfill` job (every hour at 13 past) scans again whenever a fetch brought a new bar, so a name priced from Tiingo is scored on its newest close the same evening.

| Piece | Rule |
|---|---|
| Names | Held (latest holdings, cash left out), then the watchlist, then the quality list (`market.QUALITY`: broad ETFs and a dozen large quality names). The backfill registers the quality list itself and refetches it every day like the watchlist, whatever role a name already has (the library's funds are refetched daily too, after these, and are not scanned). A name keeps its first list |
| Prices | `price_bars` (adjusted), else `alpaca_bars`, extended with today's `prices_daily` close. A name needs 60 sessions |
| Measures | Day move; its z-score against the root-mean-square of the prior 252 daily moves; drop from the 252-session high; 1-year return |
| Valuation | `pe_annual` (price ÷ the latest 10-K diluted EPS) when that EPS is positive, else `price_vs_5y_avg`. `pctile_own` = share of the last 5 years' month-end values at or below today |
| Hit | A first close 10, 20 or 30% under the 52-week high (`crossed_10` …), or a day move of −1% or worse that is −2 z or worse (`big_down_day`). At most 10 a day, biggest discount first |
| Tables | `discount_signals` (one per `{as_of}-{symbol}`), `discount_cases` (first write wins), `discount_scans` (one per day) |

**`GET /api/engine/discounts`.** `{as_of, scanned, rule, rows, note}`. Rows from the last 10 days, newest first: `signal_id, symbol, name, as_of, list, reason, price, drop_from_high_pct, move_z, valuation {metric, value, pctile_own}, numbers {price, day_move_pct, drop_from_high_pct, move_z, high_52w, ret_1y_pct, valuation_value, valuation_pctile}, case` (null, or `{verdict, case, risks, confidence, horizon_days, numbers_cited, model, written_at, run_id}`).

For the research desk: `discounts.pending(cfg, limit)` returns the last 5 days' hits with no case, biggest discount first, and raises `discounts.NotReady` before the first scan. `discounts.record(cfg, signal_id, case)` checks a case (verdict buy/wait/avoid, case ≤ 400, risks ≤ 240, confidence 0–1, horizon_days ≥ 1, numbers_cited from the hit's `numbers`, model, written_at), raises `ValueError` on bad values and returns False when a case already exists.

## One as of

Module `desk.engine.asof`. Every page reads one day and one time from `GET /api/asof`.

| Piece | Rule |
|---|---|
| Book day | The newest day in `metric_values`. Holdings, metrics, the newest day pack and its debrief all sit on it |
| Evening run | After the close the daily job copies each quoted symbol's last regular-session quote (trade time up to a minute past the close; later prints ignored) into `closes_provisional(symbol, date, close, prev_close, quote_at, stamped_at)`, then rebuilds. So by 17:45 ET the book day is today |
| Provisional | A day is provisional while any of its prices come from `closes_provisional`, or while a held symbol that has a price source still carries its last close (`prices.waiting`: no close for the day yet, but an official close within the 7 days before). A symbol with no quote (mutual funds) carries its last close and is listed in `prices.carried`. A plan code with no market price anywhere is carried but never waited on, so it does not hold the day back; neither does a holding valued at the snapshot price |
| Final | `status: final` means every held symbol with a price source has its official close for the day. It says nothing about the review pack: `period_reviews.final` is the pack's freeze flag and stays false on the newest day until a later data day exists, because bank and broker activity for that day can still arrive |
| Late close | A fund price that lands after the day was booked (the booked close differs from the official one) makes `restate` due: the day and its review run again and the debrief is asked for |
| Restated | Mirror closes and Tiingo bars always win over a provisional close. `restate` reruns the day when they land and the provisional rows are dropped; rows older than 7 days are dropped anyway |
| Quotes | Held symbols, SPY and every live catalog mix symbol, so the yardsticks move on the provisional day too. One extra fetch right after the close settles the closing price |
| Catch-up | `restate` checks every 5 minutes, at any hour (`2-57/5 * * * *`). A book older than the last finished session moves on that check, from stored closing quotes or bars, so the book is on today within minutes of the close. It takes the daily pass's lock and looks again once it has it, so it never runs on top of a daily pass; as a heavy job it waits its turn in low-memory mode and during the overnight run. A try that failed waits an hour before the same closes are tried again |
| After a catch-up | The review runs in the same job, and the Debrief desk is asked for through the job request folder (`agents-run-debrief`); it writes only when the pack changed |
| Dates | Every date a page shows is the desk's day in Eastern time (`market.et_day`, `market.session_day`), never the UTC date. The Race to live `as_of` is capped at the last session; a mix that enters tomorrow reads today. A brief is stored under the data day it was built from, not the run's timestamp |

**`GET /api/asof`.** `{day, at, provisional, status (final, provisional, empty), words, previous_day, expected_day, behind (null or {sessions, reason}), prices {official, quoted, carried, waiting}, numbers {value, day_change, day_change_pct, cash_ready, cash_pending, cash_pending_days, margin_debit, margin_cost_month}, live, market {state, day}, review {day, computed_at}, debrief {day, written_at, stale}}`. `numbers` are the metric values at `day`. `live` is `{day, state, at, value, day_change, day_change_pct, words}` only while quotes belong to a later session than `day`; null means the book already covers it, so pages show `numbers`.

## Period reviews

Module `desk.engine.review`, job `review` weekdays 08:35, 17:35 and 17:45 ET. One pack of facts per day, week, month and year; the debrief desk writes the words from it.

| Piece | Rule |
|---|---|
| Periods | Run on trading days: `start` is the first and `end` the last trading day of the period. A weekend or holiday data day falls into the next period. The first run backfills every period the value series covers |
| Base | The last data day on or before the trading day ahead of `start`. If the desk's history starts inside the period, the pack covers what there is and says so (`coverage.full` false) |
| Closed | `end` has passed, or it is `end` and after 16:15 ET. The open period is "so far" |
| Final | Closed and a later data day exists. Final packs freeze; a closed pack may be restated once before that (mutual fund prices post late). Two exceptions, both from the back-cast: a pack that started at the edge of the history is redone when the history reaches further back, and a pack whose base day is back-cast is redone when its start value, end value or return moves. `review.run(..., rebuild=True)` recomputes all |
| Change | `change_pct` is time-weighted (the `twr_index` series). `net_flows` is every flow the return already nets out, derived per day as value − prior value × (1 + day return). `gain_usd` = change − flows |
| Versus | SPY, then each live catalog mix, on the same starting dollars with the same flows on the same days. A mix is rebalanced daily, cash earns nothing, Dip buy carries its cash state from the index path. A comparator is left out when under 80% of it has prices |
| Movers | Per holding: yesterday's shares × today's price change, summed over the period (splits handled). Top 5 up and down. A mover's `return_pct` is chained from the same daily holdings prices, so it always agrees in sign with its contribution. `other_usd` is the rest of the gain: dividends, interest, cash and same-day trades. A day's flow under 5 cents is rounding and counts as zero |
| Risk | Max drawdown and best and worst day on the return index; volatility annualised from daily returns (5 or more days). `band` (your risk band and the as-held fit) only on the latest pack. `convictions` is each conviction hold's weight against its band |
| Events | Discount days, scored filings and earnings dates for names held in the period |
| Provisional | A pack whose last day is provisional, or still waits on a fund's official close, carries `provisional {day, carried, note}`; the key is absent otherwise. It is rebuilt when the day is restated, and the debrief is written again |
| Tables | `period_reviews(kind, start, end, as_of, closed, final, version, digest, pack, computed_at)`, `period_debriefs(kind, end, pack_digest, body, written_at, model, run_id)`, `review_runs` |

**Pack.** `version, kind, start, end, as_of, label, quality, coverage {full, base, days, note}, value {start, end, change_usd, change_pct, net_flows, gain_usd}, vs [{id, name, kind, return_pct, excess_pts, value_end, diff_usd}], movers {up, down, other_usd, count}` (rows `{symbol, name, contribution_usd, contribution_pts, return_pct, weight_pct}`), `accounts [{account, start, end, change_usd, change_pct, net_flows}], income {dividends, interest, margin_interest}, flows [{date, account, amount, kind}], trades [{date, account, symbol, side, shares, price, amount}], trade_count, realized {short_term, long_term, total, sales}, risk {max_drawdown_pct, volatility_pct, best_day, worst_day, band, convictions}, decisions {made, matured}, paper [{id, name, kind, status, return_pct, value_end}], fi {fi_number, progress_start_pct, progress_end_pct, change_pts}, events [{date, type, symbol, detail}], numbers`. `numbers` is the flat list a debrief may cite (`change_usd`, `vs.spy.pts`, `contrib.<SYM>.usd`, `ret.<SYM>.pct`, `paper.<id>.pct`, `score.<id>.<horizon>.usd` …). `digest` is a hash of the pack.

**`GET /api/engine/reviews?kind=&end=`.** `{kind, start, end, as_of, closed, final, computed_at, digest, pack, debrief}`; leave `end` out for the latest. `pack` is null with a `note` when there is none. `debrief` is null or `{headline, what_happened, why, against_decisions, watch, next_steps [{text, symbol}], numbers_cited, model, written_at, pack_digest, stale, rewrite}`; `stale` means the pack changed after it was written. `rewrite` is null unless it is stale; then it is the Debrief desk's `{state (due, late, failed), due_at, words}` (`desk.agents.debrief.rewrite_for`, see docs/agents.md), so the page can stay quiet while a rewrite is simply due. It is also null when the desk cannot answer.

**`GET /api/engine/reviews/index`.** `{as_of, kinds {day, week, month, year}, note}`, newest first, rows `{start, end, as_of, label, closed, final, change_usd, change_pct, has_debrief}`.

For the debrief desk: `review.pending(cfg)` returns the latest period of each kind whose pack has no debrief or changed since it (`{kind, start, end, closed, digest, debrief_digest, pack}`), and raises `review.NotReady` before the first run. `review.record(cfg, kind, end, result)` checks a debrief (headline ≤ 120, what_happened and why ≤ 700, against_decisions ≤ 500, up to 4 watch lines ≤ 160, up to 3 next steps ≤ 200, numbers_cited from the pack's `numbers`, pack_digest equal to the current digest, model, written_at), raises `ValueError` on bad values and replaces any earlier debrief for that period.

## Plan facts

Module `desk.engine.planfacts`. The numbers a stock plan is written from, one row per holding, computed on request from the latest engine run (no table, no job).

| Piece | Rule |
|---|---|
| Rows | Every non-cash holding on the latest holdings day, summed across accounts. Ask for one symbol and it is returned even when not held (price facts only) |
| Prices | `price_bars` (adjusted), else `alpaca_bars`, extended with `prices_daily`; else the mirror's closes (mutual funds) |
| Cost | The lot export when every lot has a cost, else the snapshot's cost. `unrealized_usd` = value − cost |
| Lots | `acquired, shares, cost, cost_per_share, value, gain, term, long_term_on` (the first day a sale is long term), `days_to_long_term`, `quality` (`modelled` when rebuilt from history) |
| Range and trend | 52-week high and low (252 sessions), drop from the high, 50 and 200-session averages and the distance to each, 1-year return |
| Zones | A monthly swing is the 63-session daily volatility × √21 (capped at 45%). Add zone: one to two swings under the last close. Trim zone: one to two above. `zones.levels` lists the reference prices: last close, 52-week high and low, both averages, cost per share, and 10, 20 and 30% under the high |
| Valuation | As the discount scanner: `pe_annual` against its own 5 years when SEC EPS allows, else `price_vs_5y_avg` |
| Share of risk | Weight × covariance with the book ÷ the book's variance, on 126 sessions of daily returns at today's weights. Sums to 100 across priced holdings |
| Band | First that applies: the approved plan's `weight_band`, the conviction hold's band, the single-stock rule (stocks only), the risk band's single-stock cap (stocks only). `status` is `inside`, `over` or `under`; funds with no band are `inside` |
| Discount | `active` when the scanner flagged the name in the last 5 days |

**Row.** `symbol, name, kind, as_of, price_as_of, held, accounts, numbers, lots, wash_windows [{kind, date, clears, account, amount}], zones {method, sigma_month_pct, add {low, high}, trim {low, high}, levels}, discount {active, signal_id, reason, as_of}, next_earnings {date, hour, eps_estimate, days}, filing_signals, valuation {metric, value, pctile_own}, band {source, min_pct, max_pct, weight_pct, status, room_pct, risk_band}`. `numbers` is flat and numeric: `price, shares, value, weight_pct, cost_basis, cost_per_share, unrealized_usd, unrealized_pct, long_term_shares, short_term_shares, long_term_gain, short_term_gain, risk_share_pct, valuation_value, valuation_pctile, day_move_pct, high_52w, low_52w, drop_from_high_pct, above_low_pct, vol_annual_pct, sigma_month_pct, sma_50, sma_200, vs_sma_50_pct, vs_sma_200_pct, ret_1y_pct, add_low, add_high, trim_low, trim_high`; a key is left out when its input is missing.

**`GET /api/engine/planfacts[?symbol=]`.** `{as_of, rows, note}`.

For the plans desk: `planfacts.facts(cfg, symbol=None)` returns the rows and raises `planfacts.NotReady` before the first engine run. Every price a plan may name as a zone is in `zones` or `numbers`.

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
| `lab/data/lab.db` | Engine `lab-export` job (00:55 nightly), atomic replace | `bars` (price bars plus mirror closes), `symbols` (kind, role, first and last day), `macro`, `settings` (marginal rate), `factors` and `french` (phase 9b). SQLite in rollback-journal mode, never WAL, so it opens read-only on the lab's read-only mount |
| `lab/data/held.json` | Engine `lab-export`, beside `lab.db` | Today's holdings as weights only (`as_of`, `covered`, `weights`). Box only |
| `lab/data/plan.json` | Engine `lab-export`, beside `lab.db` | The plan's target weights (`weights`), removed when no plan is loaded. Box only |
| `lab/data/own.db` | Engine `lab-export`, beside `lab.db` | `bars` and `symbols` for his own single stocks: every stock that is not on the public stock list, the quality list or the small-cap list. `load` merges it when it is there. Box only |

**What a worker can read.** A worker is served `lab.db` and nothing else, because holdings and the plan never leave the box (project plan, 2026-11-11). A test opens the file a worker is served to check each row below.

| In `lab.db` | Rule |
|---|---|
| Mixes | No held mix and no plan mix, in any table or column |
| `symbols.role` | `universe` for held, watched, past and plan funds alike; `benchmark`, `small_cap` and `public` differ, and all three are public lists. Every fund in `data.PUBLIC_FUNDS` (benchmarks, library funds, IWM) is `benchmark` and every priced name on the public stock list is `public` and kind `stock`, whether he holds it or not |
| `symbols.kind` | A public fact. A plan name nothing public can classify is a fund |
| Single stocks | Only public lists: the public stock list, the scanner's quality list (in the file whether he holds one or not) and the small caps. Any other stock, which is one he holds, held, watches or plans, goes to `own.db` and is not in `lab.db` at all |
| What is left | The file still has bars for the funds the desk follows, so which mutual funds it carries can be guessed to be his. `settings.marginal_rate_pct` is the one personal figure a worker sees |

Nothing a worker runs needs `own.db`: a screen reads only role `public`, a hand-picked list takes funds only, and the as-held and plan-mix rows already stay on the box. The box still needs it for those two rows and for the paper replay.
| `lab/queue/*.json` | Strategy desk runner | Experiment and finalize requests |
| `lab/runs/ledger.db` | Lab only | `strategies` (status `lab`, `paper`, `research`, `failed`, `inconclusive`), `strategy_trials` (kinds `train`, `test`, `full`, `holdout`, `rule`; never pruned), `lab_results` (`experiment`, `finalize`, `rejected`, `rule` bodies), `queue_done`. Older ledgers migrate in place |
| `desk.db` | Engine `lab-export` job | `paper_portfolios`, `paper_positions`, `paper_trades` |

**Spec grammar** (also served as `grammar` by `GET /api/lab/strategies` and in every `desk_view`):

| Field | Accepted |
|---|---|
| `universe` | `{"type": "fund_list", "set": "sector_etfs" \| "core_etfs" \| "benchmarks"}`, `{"type": "fund_list", "symbols": [funds only]}`, a `rule` naming a set, or `{"type": "screen", "min_history_days", "min_price"}` for single stocks from the public stock list (coverage sentence; see "Stock screens run on the public stock list"), or `{"type": "small_caps", "min_price"}` (default 2) for point-in-time small caps, benchmark IWM. A hand-picked stock list is rejected |
| `signals` | Feature `ret`, `ret_skip`, `vol`, `ma_gap`, `ma_cross` (the 50-day average against the window's average; a 200-day window above zero is a golden cross), `range_52w`, `dd`, `insider.buyers`, `insider.buy_usd`, `earnings.surprise`, `earnings.days_since`; window `63d`, `6m`, `1y` or `{param}d`; transform `raw`, `rank`, `inverse_rank`, `zscore`, `inverse`. Score is the mean of the transformed signals |
| `entry` | `{"top_n": 3 \| "param:top_n", "min_signal": 0}` or "top 3 by rank". `min_signal` applies to the first signal's raw value; slots it leaves empty stay in cash |
| `exit` | `"rebalance"`, or `{"hold_rank": 5}` / "falls out of top 5" to keep a holding while it ranks in the top 5 |
| `rebalance`, `sizing` | Weekly, monthly or quarterly; `equal`, `inverse_vol` (63-day) or `rank`. `max_position_pct` caps a weight, the rest stays cash. `"vol_target": 0.15` in `sizing` scales every weight down by target over the portfolio's own 63-day volatility whenever that ran hotter; it never scales up |
| `filters` | `[{"metric_id": "ma_gap", "window": "200d", "min": 0}]`: a name is eligible only while each raw value sits inside `min` and `max`; slots left empty stay in cash. A filter with `"symbol": "SPY"` reads that one fund instead of each holding, so it switches the whole strategy to cash; the symbol must have bars in the lab |
| Fixed mixes | `"sizing": {"weights": {"SPY": 60, "AGG": 40}}` holds funds at fixed weights and needs no signal; `{"type": "fund_list", "set": "plan_mix"}` is the plan at its target weights; `"set": "held_mix"` is today's holdings at today's weights, single stocks included, read from `held.json` on the box, always with a hindsight caveat; a pass on it is research only, never paper. A spec that uses either mix is never offered to a worker (`spec.local_only`), and with a plan loaded neither is an experiment with no `benchmark` of its own, since it is judged against the plan; the box's own lab computes those. A fund with no history in the lab is dropped and the rest scaled up, with a caveat; under half the mix present is refused |
| Named French portfolios | `{"type": "french", "set": "size_deciles", "members": ["lo"]}` keeps the portfolios whose name starts that way and needs no signal |
| `params`, `grid` | `{"top_n": {"min": 1, "max": 4, "default": 3}}` or a list; grid values must sit inside. Over the trial budget (max 200), a seeded, deterministic subset runs |

**A run.** A window opens invested: the picks from the close before the window's first day are bought at that day's open, so no test year waits in cash for its first rebalance day (a window with no earlier day, or no pick yet, starts in cash). That first purchase is counted in costs and turnover but sits before the first measured return. The paper replay passes `enter=False` and still waits for its first rebalance day, as the paper executor does. Signals at the close, fills at the next open (`adjClose`-scaled), costs 5 bps for funds, 15 for stocks, 25 under $20M a day. FIFO lots, year-end tax on net realized gains at the exported marginal rate (else 24%) and 15% long-term, losses carried. Cash earns the 3-month bill. A symbol whose bars stop before the data ends is sold at its last price less 30%. The benchmark is `spec.benchmark`, else the plan mix, else the S&P 500, rebalanced monthly; the S&P 500 is always reported.

**A fund that had not started trading.** A mix never holds cash for a fund that did not exist yet.

| Case | Rule |
|---|---|
| Fixed weights (`sizing.weights`, the plan mix) | On each rebalance day the weights are scaled over the funds already trading, so the rest of the mix carries a newer fund's share until it lists |
| Where the test starts | The first day funds making up at least 90% of the mix were trading (`spec.MIN_LIVE`, `Spec.start`); the runner never starts a walk-forward before it. Too little history left before the holdout refuses the spec in plain words |
| A fund list picked by signal (`top_n`) | The number of slots is capped at the funds trading that day, so four funds with three listed is fully invested in three |
| Caveats | The result says the start day and which funds joined later |
| Not covered | A fund with a missing bar on a rebalance day still sits out that month |

**Walk-forward.** The two years before the newest bar are the holdout and never run before finalize. The range before it splits into folds of 3 years train and 1 year test (2 and 0.5 under 4 years; under 2.5 years is rejected). Each fold picks the variant with the best training Sharpe that meets `max_turnover` (read as turnover a year), then runs it on the test year; test years are stitched into the walk-forward record. Every variant also runs over the whole range for the overfitting tests.

**What the desk sees** (`desk_view`): folds, the walk-forward summary, the start-month distribution per horizon (walk-forward when long enough, else the full range flagged `in_sample`), deflated Sharpe (trials = every distinct full-range run in the family: ids sharing a family key `insider-`, `drift-` or `filings-`, plus any `parent_id` chain, across versions and nights; Sharpe variance is the larger of this run's variants and the whole family's; a family id registered without a `parent_id` gets the family's first id), PBO by combinatorial cross-validation over 10 blocks, the factor check, the analyses it asked for (`param_sensitivity`, `regime_split` bull/bear and high/low rates, `turnover_cost` at 1×, 2×, 4×, `factor_regression`), caveats, and rejection reasons. A changed spec under the same version, or any spec after finalize, is rejected.

**Finalize** runs the last fold's parameters on the holdout and on the days after the writing model's cutoff (`DESK_LAB_MODEL_CUTOFFS`, a JSON map of model to date, default 2026-06-30), then checks the bars: start-month 5th percentile above zero on the longest horizon, deflated Sharpe over 0.95, PBO under 0.2, holdout excess positive and at least half the walk-forward excess, and the spec's own `excess_vs_plan_pts`, `max_drawdown_pct`, `min_trades`. Any failed bar is `fail`; all computed bars passing is `pass`; anything missing is `inconclusive`. The factor bar is alpha t of 2 or more; it is `null`, and does not block, only when the factors are missing or overlap fewer than 252 days. A pass moves a fund, screen or small-cap strategy to `paper` and a French one to `research`. A spec with nothing to tune has one variant with empty parameters and is judged like any other; only a spec where no variant met the constraints in any fold is closed as `failed` without bars. A screen that passed on a public stock list under 90% priced is `research` too.

**Paper.** Each night the engine replays a paper strategy with its finalized parameters from the finalize day to the newest bar on fresh data, so it can never be tuned after the fact. Its status comes from the paper gate (above): a stored verdict at day 182 and every 91 days after, `eligible` only when the lead clears the noise band with 30 buys. `desk.engine.lab.eligible` lists the eligible ones for Scout, with the chance the lead is luck.

**API.** `GET /api/lab/strategies` (list with `hypothesis`, trial counts, paper state, feature catalog, grammar) and `GET /api/lab/strategies/{id}` (the desk view plus paper trades, and `spec`: the frozen title, hypothesis, predicted effect, universe, signals, entry, exit, rebalance, sizing, params, success criteria, horizons, `written_at` and `model`; null for a rejected version). The first paper verdict is at `paper.days` ≥ 182 calendar days; `paper.summary` is a JSON string and carries `benchmark` and `gate`. Workers: `DESK_LAB_WORKERS` (default 1) processes.

**Not in this cut.** Point-in-time fundamentals and insider signals from the SEC bulk data sets, and reconstructed index membership.

### As built (phase 9b)

**French data.** Engine job `french` (first of the engine's steps in the night's order, `"overnight": 100`, with 00:30 as its fallback time, so new files reach the same night's `lab-export`; skips files fetched in the last 25 days) downloads the daily zips into `desk.db`:

| Table | From | Holds |
|---|---|---|
| `factors_daily(series, date, value)` | 5 factors (2x3) and momentum, daily; 3 factors monthly | `mkt_rf`, `smb`, `hml`, `rmw`, `cma`, `rf`, `mom`, and monthly `mkt_rf_m`, `rf_m` (dated the 1st), in percent |
| `french_returns(set_name, name, date, ret)` | Value-weighted block only | `industry_12`, `industry_49`, and deciles by name: `size_deciles`, `momentum_deciles`, `value_deciles` (book-to-market), `profitability_deciles` (operating profitability), `investment_deciles` |

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
| `paydown` | `debit_pct` and `rate_pct`, each one fixed number: both sides start with a margin debit of that share of the starting value, already invested; the rule sends each deposit to the debit until it is gone | The same debit left alone, every deposit invested, interest added to the debit each month |

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
engine_views(name, as_of, body)   (latest scorecard, patterns, replay, fi and factors JSON)
data_health(as_of, check, status, detail)
preflight(ticket_id, metric_id, before, after, flag)
triggers(as_of, kind, scope_id, detail)
paper_portfolios, paper_positions, paper_trades   (Strategy lab; the trial ledger is lab/runs/ledger.db)
```

- `scope`: `portfolio`, `account`, `sleeve`, `holding`, `benchmark`, `shadow`, plus `pair`, `underlying`, `sector`, `scenario`, `macro`, `rule`, `tax`, `decision`, `group`, `desk`, `factor`.
- `quality`: `ok`, `stale`, `pro_forma`, `modelled`, `insufficient_history`.
- `unit`: `usd`, `pct`, `pts`, `ratio`, `days`, `date`, `count`, `flag` (1 yes, 0 no).

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

**Triggers.** After each core run the engine writes `triggers(as_of, kind, scope_id, detail)` for the agents' scheduler (`desk.engine.triggers.today(cfg)`); each fires at most once a day. Between 22:00 and 07:00 local time an alert goes out at low priority, so a day restated overnight never rings the phone. The first day a condition appears, it also sends a phone alert on `alerts` (no dollar amounts). Live quotes failing during market hours sends one `ops` alert a day.

| Kind | Fires when | Scope |
|---|---|---|
| `margin_debit` | `margin.debit` above zero | `portfolio` |
| `daily_move` | Portfolio 1D TWR past the risk dial (1 to 4% for risk level 1 to 5), or a holding past 2.5 times it | `portfolio` or ticker |
| `concentration` | A single stock, or all of them together, past `opportunity.satellite_cap_pct` | ticker or `satellite` |
| `rule_breach` | A `plan.rules` flag is 0; `detail` is `{breaks, what}` from `plan.rule_breaks` | rule id |
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
| `GET /api/engine/lots?symbol=&account=` | Current tax lots (each with `method` and `quality`), recent lot files, and imported Fidelity history files (`history`) |
| `GET /api/compare?ids=&window=` | Aligned, rebased series plus the comparison table; 400 on bad input |
| `GET /api/engine/lookthrough?fund=&limit=` | Look-through exposure, sectors, funds covered, one fund's holdings |
| `GET /api/asof` | The desk's one day and time (see [One as of](#one-as-of)) |
| `GET /api/live` | Latest quotes, live value, day change (market hours). `quote_day` is the session the quotes belong to; a fund with no quote that day counts no change |
| `GET /api/live/intraday` | Today's quote ticks `{SYM: [{t, price}]}` |
| `POST /api/preflight` | The Preflight answer for a hypothetical trade (nothing stored); 400 on a bad trade |
| `GET /api/engine/preflight?ticket_id=` | Stored before and after rows for a ticket |
| `GET /api/engine/wash` | Open wash-sale windows `{symbol, kind, date, clears, account, amount}` |
| `GET /api/lab/strategies`, `/api/lab/strategies/{id}` | Strategy list, status, feature catalog and grammar; one strategy's tear sheet, verdict and paper trades |
| `GET /api/lab/library` | The strategy library: one row per built-in experiment with its kind, out-of-sample verdict, benchmark, trial count and luck band |
| `GET /api/engine/scorecard?origin=` | Flight record: groups, desks, saves, off-plan gap, per-decision scores |
| `GET /api/engine/patterns` | Patterns: market, holdings, drawdown tables, seasonality, correlation shifts, behavior |
| `GET /api/engine/replay` | Rule replays: you, the index, and each rule's end value, by-symbol effect and weekly path |
| `GET /api/engine/fi` | FI Monte Carlo: dates, percentile lines, inputs, caveats |
| `GET /api/engine/factors` | Factor loadings per holding and weighted |
| `GET`, `POST /api/engine/watchlist`, `DELETE /api/engine/watchlist/{symbol}` | Watchlist rows; desk rows editable, `DESK_WATCHLIST` rows read-only |

**Display rules for design.** Show `as_of` on every KPI; show any non-`ok` quality as a small, friendly tag, not a red error; never annualize under a year; Monte Carlo as percentile lines or markers, not a filled band.

## Compute schedule

| When | Runs |
|---|---|
| Every 5 min, 9:30 to 16:00 ET weekdays | Quotes, live value, day change, intraday drawdown, margin call distance. A fund nothing prices is not asked for, and a symbol Finnhub will not quote keeps its last close (`not_quoted`); neither fails the run. It fails on a rate limit, a server error, or when every symbol asked for is refused |
| After each mirror (8:00, 17:00 ET) | Reconciliation, holdings, flows, returns, drift, rules, margin, tax (if lots are fresh), risk, correlations, scenarios, look-through exposure, signals, brief for the agents. Comparisons are computed on request |
| Nightly | Tiingo, EDGAR, FRED pulls (the scorecard and patterns refresh with each core run) |
| Nightly, 00:55 | `lab-export`: fresh `lab/data/lab.db`, then paper portfolios replay to the newest bar. Queued lab experiments run 01:00 to 06:00 ET under `job_lock("lab")` |
| Weekly, Sunday 02:10 | N-PORT look-through and sector profiles |
| Weekdays 19:30 ET | `universe`: Alpaca assets, SEC share counts, daily bars, then that day's universe |
| Nightly 03:35 ET | `filings`: yesterday's EDGAR index for universe names, then excerpts (before the scorer at 04:15) |
| Nightly 23:20 ET | `insider`: SEC insider quarters, live Form 4s, share frames, price history for cluster names, small-cap months (before `lab-export` at 00:55) |
| Nightly 23:50 ET | `earnings`: EPS facts and release times for 300 companies, then every surprise event |
| Weekdays 08:45 and 16:45 ET | `paper`: lanes and catalog mixes rebuild; at 08:45 orders for every strategy on paper; both runs reconcile fills and mark the sub-ledgers |
| Weekdays 17:40 ET | `discounts`: scan held names, the watchlist and the quality list for discount days |
| Every 5 minutes, any hour | `restate` ("Catch the book up"): exits at once unless official closes landed for a provisional day or the book is behind the last finished session; then the daily pass and the review run again and the debrief is asked for. Never twice on the same closes |
| Weekdays 08:35, 17:35 and 17:45 ET | `review`: day, week, month and year packs. 17:35 follows the engine run; 17:45 picks up that evening's discount days; the 17:46 debrief waits while `engine-daily` or `engine-review` is running, so it follows this run directly; 08:35 finalises yesterday once late fund prices are in |
| Daily 10:30 and 14:30 ET | `public`: the public stock list; fetches only when the stored list is over 6 days old or incomplete |
| Nightly 00:30 | `french` (a file is fetched only when its rows are missing or it is over 25 days old): daily and monthly factors and portfolios from the Ken French library. The Monte Carlo and factor exposure refresh with each core run |

### When a run skips

A statistics run that cannot do its work returns `ok: true`, a plain sentence in `skipped` and a stable `skipped_code` (`engine.skip(code)`, sentences in `engine.SKIPS`). The sentence is what he reads on the job; the code is for pages and tests, so wording can change without breaking them. A missing key raised as an error uses the same sentence.

| `skipped_code` | He reads | Runs that use it |
|---|---|---|
| `no_sec_contact` | The SEC contact is not set. Add it in Settings, Data, Keys. | `universe`, `earnings`, `filings`, `insider`, `public`, SEC research, fund look-through |
| `no_alpaca_keys` | The Alpaca paper keys are not set. Add them in Settings, Data, Keys. | `universe`, `paper`, insider price history |
| `no_fred_key` | The FRED key is not set. Add it in Settings, Data, Keys. | Macro series |
| `no_finnhub_key` | The Finnhub key is not set. Add it in Settings, Data, Keys. | Earnings dates, insider trades, sector profiles |
| `no_small_companies` | The list of small companies is not built yet. It builds itself on weekday evenings. | `filings` |

A test fails if a skip or a provider error in these files names a setting key. Quotes, the review and the catch-up keep their own skip sentences (the day thread's files).

## Strategy library

A fixed shelf of experiments the lab runs without any agent: `desk/engine/lab/shelf.py`. Each entry has an id, a kind, a family, a title, a one-line description, a benchmark label and either a strategy spec or a deposit rule.

| Kind | Entries | Examples |
|---|---|---|
| Old and tested | 31 | Buy and hold, 60/40, three-fund, permanent portfolio, all-weather style mix, risk parity, 200-day trend, 10-month trend across five asset classes, golden cross, volatility cap, dual momentum, asset-class momentum, 12-1 momentum (sectors, stocks, industries), sector rotation, equal-weight sectors and S&P 500, dividend growers, small value, value plus momentum, small-cap reversal, low volatility, and size, momentum, value, profitability and quality tilts from the French portfolios |
| Practical | 17 | The plan's mix, safe mix, aggressive tech tilt, core and satellite, theme funds at equal weight, today's holdings (as held, and with single stocks capped at 10%), dip-only, beaten-down sectors, deposits held back for a dip, margin dip-buy, margin debit paid first, lump sum spread over months, deposit steering, rebalance bands, tax-loss harvesting |
| Novel and creative | 14 | Trend-filtered dip-buy, sector momentum in uptrends only, sector momentum that stands down in rough markets, calm winners, 52-week-high breakout with a volatility cap, drawdown stop, buy after a 5% down week, canary rule, credit canary, tech tilt at a volatility target, discount-day entries (plain and in an uptrend only), insider cluster with a momentum filter, earnings drift where insiders also bought |

62 entries: 54 experiments and 8 deposit rules. The two as-held rows are hindsight, shown but never judged (see "Hindsight rows").

**What a row is measured against.** Every row carries `benchmark` (a short label) and `benchmark_words` (one plain sentence); the payload's `benchmarks` lists each `{name, words, rows}`, most used first.

| `benchmark` | `benchmark_words` | Rows |
|---|---|---|
| S&P 500 (SPY) | The S&P 500 index fund SPY, bought and held with dividends reinvested. | 43 |
| US stock market (French) | Every US stock weighted by size, from Ken French's research data. | 7 |
| Small caps (IWM) | The small-company index fund IWM, bought and held with dividends reinvested. | 3 |
| Your plan's mix | The funds in your plan at their target weights. With no plan loaded this is the S&P 500. | 1 |
| A deposit rule's own baseline (four labels) | The same money into the same funds without the rule | 8 |

**Left out, and why.**

| Idea | Why not, and what stands in |
|---|---|
| Deposits doubled in a dip | It puts in more money than the baseline, so the comparison is not like for like. "Hold back deposits for a dip" is the fair version |
| Quality and momentum together in single stocks | The lab has no point-in-time fundamentals for single stocks. The quality tilt runs on the French portfolios; the credit canary takes the slot |
| Small value and short-term reversal from French files | Those files are not among the sets the desk fetches. Small value is a fund row (VBR); reversal runs on the point-in-time small caps |
| Canary that moves into bonds | Filters send a strategy to cash, not to another fund. The row holds the S&P 500 only while emerging markets and US bonds are both up over six months |

| Step | When | What happens |
|---|---|---|
| Queue | End of `lab-export` (00:55), before the offer to a worker; `lab-offer` repeats it each minute of the lab hours, so a build that lands after 00:55 still queues that night | `shelf.queue_missing` writes a request for every entry with no result and none waiting. Each entry has a revision (`rev`, default `shelf.REV`); the request carries it as `library_rev` and the result stores it. A tested entry is queued again at once when its result is from an older revision, or when it is 30 days old. If a rerun leaves no new result, the next try waits 12 hours. A rerun keeps version 1, so it replaces the same trials and never adds to the trial count. Experiments sort before rules. An entry the lab refused is queued again once 12 hours have passed, or at once when the lab's code has changed since the refusal (each refusal records `lab_build`, a hash of the lab's source files). A second run the same night queues nothing |
| Run | Lab, with a worker first | Experiments are `lab.sims` jobs like any other; deposit rules run in the lab itself. The lab keeps waiting for an offered file while the worker has answered something in the last `DESK_LAB_WORKER_WAIT_MIN` minutes, then runs what is left |
| Count | Ledger | Every shelf strategy has `parent_id: "library"`, so they are one family and each variant counts toward the trial count. `insider-` and `drift-` ids also count in those gate families |
| Report | `GET /api/lab/library` | One row per entry, sorted by kind, verdict, then excess |

`lab-export` is a light job (54 MB), so low-memory mode never makes it wait for its turn. Shelf results never queue a Strategy desk review, and they are never finalized by the shelf, so the two-year holdout stays untouched and nothing goes to paper.

**New deposit rules.** `dip_reserve` (`hold_pct`, `dip_pct`): that share of each deposit waits in cash and is all invested when the mix is that far below its high. `spread` (`months`): the starting sum goes in over that many monthly parts; the baseline invests it on day one. Waiting cash earns the three-month Treasury rate.

**Verdicts** use out-of-sample numbers only (the stitched walk-forward test windows; start-month distributions for rules):

| Verdict | Experiment | Deposit rule |
|---|---|---|
| `held_up` | Ahead of the benchmark by at least the luck band, and overfitting probability under 0.2 | `helps`: 5th percentile above zero and the holdout not negative |
| `within_noise` | Ahead, but inside the band, or the best settings look fitted, or level with the benchmark to a tenth of a point | `no_clear_edge` |
| `fell_short` | Behind the benchmark | `hurts`: 95th percentile below zero |
| `inconclusive` | No out-of-sample record | No horizon with a start month |

The luck band is the gate's formula in points a year: `inv_cdf((1 - 0.10) ** (1 / k)) * tracking_error / sqrt(years)`, with `k` the library's trial count. The count is library-wide, never per family: every variant of every experiment row is one more chance to get lucky, so each row added raises the bar for all of them. `note` says so once two variants are on the ledger (`shelf.BAR_NOTE`, with the count). Hindsight rows and deposit rules are outside the count. Each experiment result now also stores `noise` (`gate.measure` on the walk-forward record).

**No plan loaded.** `lib-rebalance-bands-plan` carries `mix_without_plan` (the built-in safe mix). With no plan mix in the lab data the rule runs on it: funds with no prices, or under 8 years of them, are left out and the rest scaled up (at least half the weight must remain). The row's `line` starts "Run on the built-in safe mix" and `caveats` names what was left out. `lib-plan-mix` stays `not_run` with a plain reason, since the safe mix has its own row.

**Yardstick.** `lib-buy-hold-sp500` is judged against the plan's mix. With no plan mix in the lab data the simulator's benchmark falls back to the S&P 500, so the row would be judged against itself. `shelf.view` then marks it `yardstick: true`, gives it no verdict and no `excess_pts`, sorts it first in its group and counts it under `counts.yardstick`. `gap_pts` is what it shows against itself, which should be zero. That is the lab's self-check: the payload's `self_check` is `{gap_pts, level}`, and when a current yardstick row is 0.2 points a year or more away from level, `note` says every experiment row may lean by that much.

**Hindsight rows.** `lib-as-held` ("What you hold today") tests today's holdings at today's weights, set back to them every quarter, against the S&P 500. Cash and holdings nothing prices are left out; the caveats say what share that is. `lib-as-held-capped` is the same with `"cap_stocks_pct": 10` on the universe: any single stock above 10% is trimmed to 10% and the difference spread over the other holdings in proportion (funds are never capped; if only capped stocks are left the rest stays cash). Neither is ever judged.

| Field | Each hindsight row |
|---|---|
| `hindsight` | `true` |
| `verdict`, `noise` | `null`; counted under `counts.hindsight`, never under held up, within noise or fell short |
| `line` | "From Nov 2022 to Nov 2024, today's mix would have run 3.2 points a year ahead of S&P 500 (SPY). Hindsight, not a test: ..." |
| `out_of_sample` | Same keys as an experiment row |
| Trial count | Its own family (`library-hindsight`), so it never widens the luck band of the other rows |
| Order | First in the Practical group once tested |
| Rerun | Every 7 days, not 30, so it follows what is held; a caveat gives the holdings date |
| `note` | Adds one sentence saying the rows are hindsight while either is tested |
| Where it runs | On the box in the night lab pass only; `lab-offer` skips it and a worker refuses it |
| Not run | No held mix exported yet, or the holdings have not all traded long enough before the holdout (see "A fund that had not started trading") |

**Stock screens run on the public stock list.** A screen picks only from symbols with role `public`: the priced names of the list below. Nothing he holds, held, watches or plans is in it unless the rule put it there.

| Piece | Rule |
|---|---|
| Start | `spec.start` is the list's `tests_from` (the first session of 2012), so the list is never used on a date before it was knowable |
| Coverage | `lab-export` writes `settings.public_coverage`: `as_of`, `tests_from`, `listed`, `priced` (bars in the file), `loading` (priced at Tiingo, never asked for yet), `missing`, `stopped`, `pct`, `enough` (90% or more). An experiment result keeps a copy as `public_coverage` |
| Caveat | First on every screen: "Tested on the 200 largest US companies of mid-2011, a list that owes nothing to what you hold. 187 of them have prices. The 13 without were mostly bought or failed, so the result still leans to survivors by that much." |
| Still loading | Under 90% with names still loading, a screen is refused ("still loading its prices"), the row reads "The public stock list is still loading its prices. This runs once that finishes." and the library asks again. A result that ran over 90% with some still loading is run again after 20 hours |
| Thin list | Under 90% with nothing left to load: the caveat ends "That is under 90%, so this stays research only.", the row has `thin_coverage: true` and `research_only: true`, a row that would read held up is shown as within noise ("Ahead, but too little of the stock list has prices: ..."), and a finalize pass is `research`, never `paper` |
| Where prices end | Public names top up weekly, so `LabData.calendar_for("screen")` stops at the oldest last bar among the public names within 10 sessions of the list's usual last bar (the median, which is the latest weekly top-up while most of the list still trades). Screen tests, holdouts and paper replays end there. If the top-ups stall, screens end earlier; no name is sold for it |
| Stopped trading | Any holding, in any universe, is gone once its last bar is more than 10 sessions (`data.GONE_SESSIONS`) behind the end of its calendar. Before, one missing day counted |
| What a gone name pays | A public name leaves at its last price, since most large companies leave by being bought. If that price is under half its one-year high it leaves at 30% less (`sim.COLLAPSED`). Every other name still leaves at 30% less (`sim.DELIST_HAIRCUT`); the small-cap stress test still counts each as a total loss |
| Said on the row | Second caveat on every screen (`spec.PUBLIC_EXITS`): "A company that stopped trading leaves at its last price, as in a buyout. It is counted at 30% less only when that price was under half its one-year high." |
| Known limit | A screen strategy that reaches paper sees prices up to a week old, because the list tops up weekly. Daily top-ups once a screen is on paper are not built |
| Library | `shelf.SCREEN_REV` is 5, so the six screen rows run again. A result stored before the switch has no `public_coverage`; it keeps `leans_on_hindsight: true` and the old words until its rerun lands |

**Public stock list.** `public.py`, job `public` ("Public stock list"), `GET /api/engine/public-stocks`. The job builds the list and says which names Tiingo can price; the price backfill fetches them.

| Step | Rule |
|---|---|
| The list | The 200 US companies with the largest public float in their annual report, measured nearest June 30, 2011 and never dated after 2011. SEC frames `dei/EntityPublicFloat` for the six quarters from late 2010 to the end of 2011, so every fiscal year end and a float tagged with the wrong date are covered; one figure per company |
| Why it is fair | Size in mid-2011 was public then, and tests start January 2012. A company had to file that annual report, so one that vanished before early 2012 is missed |
| Sanity check | The float is typed by hand on the cover page and 2011 filings are full of scale mistakes (thousands typed as dollars). A figure counts only if a second figure agrees: the same company's float a year or more apart within ten times, or float divided by shares outstanding between $1 and $2,000. It must also be no more than 15 times total assets and no more than $450B (Exxon, the largest, was about $400B). `public.doubt` |
| Stand-in | When the figure nearest mid-2011 fails, the company's next nearest figure is tried, so a giant with one typo keeps its place on the year-before float |
| Left out | Companies whose raw figure would have made the list but failed the check: `left_out` (first 15, with the raw size and why), `left_out_count`, and `left_out_names` on the route. Stored beside the list with state `misfiled`; nothing else reads them |
| Funds and trusts | A filer whose ticker Tiingo lists only as a fund (ETF or mutual fund) over the first session of 2012, such as a gold trust, is not a company. It is left out, named in `funds` and in `left_out_names`, and the next largest company takes its place (the 20 next largest are kept in reserve), so the list still has 200. A ticker a fund took over later does not count |
| Share classes | `public.SHARE_CLASS`: a ticker whose history sits under another class of the same company is read through that class. Google's GOOG dates from the 2014 split, so it is priced as GOOGL |
| Built by | Each stored list is marked with `public.RULE` in `api_calls`. A list without the current mark is built again on the next run, whatever its age |
| Ticker | Today's SEC ticker list first. If none of those is priced, the 2011 filing: the trading symbol on its cover page (`R1.htm`), then the prefix of its data file |
| Priced | Tiingo's public ticker file lists the ticker as a US-dollar stock with history that covers the first session of 2012. `state` is `priced`, `late` (history starts later, often a reused ticker), `missing` (not at Tiingo), `no_ticker` or `unasked` (the SEC stopped answering; tried again next run). A name already priced keeps its ticker when a later run's ask goes unanswered |
| Stopped trading | A priced name whose Tiingo history ended more than 10 days before the newest date in the file |
| Check by eye | Priced from the filing and still trading: the company may have a new SEC number, or the ticker may have been reused |
| Enough | 90% priced. Under that, stock screens stay research only |
| Tiingo room | `tiingo.left` is this month's new-name allowance left, `new_names` what the list would use, `size` 200 or 150 when fewer than 220 are left |
| Cost | Eighteen SEC frames (ten for floats, four each for shares outstanding and total assets), one Tiingo file (no key, no quota), and up to two small SEC requests per company not on today's list. Kept 6 days; runs at 10:30 and 14:30 ET and exits at once while the list is fresh |

The job's `detail` and the route's `detail` are the same sentence, for example "Of the 200 largest US companies of mid-2011, 191 have a ticker and Tiingo prices 183 of them from January 2012 (91.5%). The largest are Exxon Mobil Corp, Apple Inc and International Business Machines Corp. 41 companies were left out because the size they reported looks mistyped. 1 fund or trust was left out because it is not a company." `top` is the first 25 names in order, for a check by eye.

**Outdated rows.** A tested row whose result is from an older revision keeps its numbers, has `outdated: true` and is counted in `counts.outdated`; `note` then says those rows are being run again. Bump `shelf.REV` (or one entry's `rev`) when a change to the lab alters results. `shelf.MIX_REV` marks the five mixes whose test held cash for a fund not yet trading (US plus international, risk parity, plan mix, safe mix, tech tilt); `shelf.SCREEN_REV` marks the six stock screens (see "Stock screens run on the public stock list").

**Rule rows.** A deposit rule is compared with its baseline for every start month. `share_better` and `share_worse` count the start months that ended ahead and behind; the rest ended the same, which happens when the rule never had cause to act. The row's line says ahead, behind and no different, and never counts a tie as worse. A result stored before `share_worse` existed states only what its numbers support. When the 5th, 50th and 95th percentile all round to 0.0 points the row reads "No difference" and is `within_noise` whatever the stored verdict.

**Known funds.** The lab data labels a symbol a fund only when the desk has seen it held or in a plan. `LISTED_FUNDS` in `lab/data.py` names the ETFs the built-in mixes use, so `load` treats them as funds whatever the label. `market.LIBRARY_FUNDS` names the 20 funds the wider library needs (Treasuries, gold, commodities, foreign and emerging stocks, real estate, high-yield bonds, factor and theme funds). A test keeps both lists in step with every symbol a library spec or market-wide filter names.

| Library funds | Rule |
|---|---|
| Price backfill | `backfill.DAILY` is the quality list plus the library funds. `sync_roles` registers them; a fund with no bars is asked for at once (after held, benchmark, plan and watched names, before any other name never fetched), then every day. Once it has history it sorts after the quality names, so the scanner's names are refreshed first when the hourly cap bites |
| Why daily | The simulator sells a holding whose bars stop more than 10 sessions early at its last price less 30%, so a library fund left to the 90-day rotation would poison its rows |
| In `lab.db` | `data.PUBLIC_FUNDS` (benchmarks, library funds, IWM) export as kind `fund` and role `benchmark` whatever he holds, so a held benchmark fund no longer reads `universe` |
| Short histories | UFO starts in 2019, so the two theme rows test from then; a fixed mix starts once 90% of it is trading |

**Row** (`rows[]`): `id`, `title`, `kind`, `family`, `description`, `benchmark`, `type` (`experiment` or `rule`), `status` (`tested`, `waiting`, `not_run`), `verdict`, `line` (one sentence with the numbers), `reason` (why it has not run, as a plain sentence from `shelf.plain`; it never quotes request syntax), `tested_at`, `out_of_sample` (`start`, `end`, `ann_return_pct`, `excess_pts`, `sharpe`, `mdd_pct`), `noise` (`trials`, `band_pts`, `luck`), `rule` (`horizon_years`, `starts`, `p5_pts`, `p50_pts`, `p95_pts`, `share_better`, `share_worse`), `deflated_sharpe`, `pbo`, `variants`, `research_only`, `caveats`, `detail`, `yardstick`, `gap_pts`, `outdated`, `benchmark_words`. The payload also has `as_of`, `trials`, `note`, `counts`, `kinds` and `benchmarks`. `shelf.ready(cfg)` gives the morning alert its line.

## Memory budget

The NAS containers are small (cron 640 MB, lab 1,536 MB, API 256 MB), so no job may hold a whole table in Python. Measured 2026-11-11 on a synthetic database of 191k price bars, 85k insider rows, 2.2M Alpaca bars, the full French sets and three years of mirror:

| Job | Peak MB | Seconds | How it stays small |
|---|---|---|---|
| `holdings`, `core`, `daily`, `review` | 91, 137, 137, 89 | 1, 19, 20, 1 | Already small |
| `lab-export` | 54 (was 695) | 10 | Bars go from `desk.db` to `lab.db` as a stream; the first source for a bar wins (Tiingo, then the mirror, then Alpaca) |
| `insider`: history load, 300 names | 134 (was 1,055) | 9 plus downloads | Batches of 25 names |
| `insider`: one bulk quarter | 72 (was 273) | 2 | The TSVs are read a row at a time |
| Lab, 3 workers, 12-variant screen | 132 (was 1,611) | 5 (was 24) | See below |
| Lab, 3 workers, French 49 industries since 1963 | 184 (was 3,120) | 12 (was 387) | See below |
| API, every read endpoint | 94 | | |

**Lab data.** `load` keeps each series as packed arrays of doubles with one shared set of date strings; a day is found through one shared calendar and a small per-series offset table (`DayIndex`), about 40 bytes a bar instead of 290. A French set is read as a stream. Workers are forked from the process that already holds the data, so they share it and never reload it; where fork is not available the variants run one after another. Results are identical to the old loader's, down to every stored trial.

**Lab simulations as a job.** A simulation is a pure function of the lab data file and its inputs, so it is keyed, cached and safe to run twice. Module `desk.engine.lab.simcache`.

| Piece | What it is |
|---|---|
| Snapshot | SHA-256 of `lab/data/lab.db` |
| Row key | SHA-256 of the lab code's own hash, the snapshot, the spec hash, params, start, end and cost multiplier |
| Row | `{key, params, start, end, cost_mult, summary, days, rets, bench}` |
| Cache | `lab/runs/simcache.db`, table `sim_cache`; emptied when the snapshot changes. Every experiment reads it first and stores what it computes, so a rerun after a stop recomputes nothing and writes no second copy of a trial |
| Worker side | `python -m desk.engine.lab --sims REQUEST.json --data lab.db`, or `runner.sims(path, request)`: runs the experiment's simulations against a throwaway ledger and prints `{kind: "lab.sims", key, snapshot, request, status, rows}`. No ledger, no network, no keys |
| NAS side | `simcache.stage(cfg, result)` drops the result in `lab/queue/` as `sims-*.json.gz`. The lab reads it before the queue: wrong snapshot is `stale`; a row whose key, lengths or window do not match is `rejected`; two rows are recomputed and must match exactly or the file is a `mismatch`. Only then are rows stored. Whatever is missing the lab computes itself |

On the synthetic database the heaviest experiment (French industries, 781 simulations) is 17 MB gzipped; with it staged the lab computes nothing and finishes in 8 s against 12.

**With a worker (Horizon).** `desk/engine/kinds.py` registers the job kind `lab.sims` with Infrastructure's worker protocol (`docs/architecture.md`).

| Step | Where | What happens |
|---|---|---|
| Offer | NAS: end of `lab-export` (00:55), then `lab-offer` each minute from 01:00 to 05:59 | If a worker is online, every queued experiment the lab has not run becomes a `lab.sims` job keyed by `simcache.job_key`, with the current `lab.db` as its copy. `lab/queue/offers.sims` records each file's key and first offer time, and when a worker was last seen. A file is offered once per `lab.db`; later passes keep its time. No worker online: nothing is offered and nothing waits |
| Run | Worker | `runner.sims` on its downloaded copy. An answer over 3 million simulated days is cut short and marked `partial`; the lab computes the rest |
| Accept | NAS, `worker-apply` | `simcache.stage_file` copies the gzip into `lab/queue/` unread, so it costs no memory in the scheduler. It runs within seconds of the worker's post |
| Use | Lab | An offered file, and everything queued after it, waits up to `DESK_LAB_WORKER_WAIT_MIN` (10) minutes from its offer, or from the worker's latest answer if that is later, for the answer; `waiting_for_worker` in the run's output names them. An experiment queued in the last 3 minutes also waits if a worker was seen in the last 6, so the offer can reach it first. When the answer arrives it is checked as above and used, good or bad. When it does not, the lab runs the queue itself. A wait still open at 06:00 is finished before the lab stops for the day |

**Rules for new jobs.** Iterate cursors, do not `fetchall` a bar table. Write downloads in batches inside the loop that fetches them. A second run of a job must be a no-op, not a double write.

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

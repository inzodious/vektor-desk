# Changelog

Notable changes to Vektor Desk. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html): each roadmap phase is a minor version, and fixes between phases are patches. Planned work is in [ROADMAP.md](ROADMAP.md).

## Unreleased

## 1.1.0 - 2026-11-10

### Added

- Results: the engine writes a review pack for each day, week, month and year (change, against the S&P 500 and each mix, movers, money in, trades, risk, decisions, paper race), and the Results page shows it with the desk's debrief and next steps ([#148], [#159])
- Value and holdings history from before the desk's first snapshot, rebuilt from the Fidelity history, so Month and Year results are real; the first evening run fetches missing prices itself ([#161], [#163])
- Stock plans: one versioned plan per holding with a thesis, band, add and trim rules and dated steps, drafted by the Plan desk and approved by you; planned harvests hold new buys through the wash-sale window ([#152], [#157])
- Plan facts per holding: lots with long-term dates, wash windows, 52-week range, add and trim zones, valuation, discount state, share of risk and band status ([#156])
- Plan → Stock plans gives every holding a plan card with forms to write a plan, add a step, approve a draft and mark steps done; the same block is on the Symbol sheet, and coming plan steps show on the Bridge and in the daily Brief ([#165], [#157])
- The Bridge shows today's run stage by stage (accounts, numbers, review, desks, paper), with what ran and what is still due ([#151])
- Replay: your own trades replayed under a size cap, an exit rule, no margin and a year-and-a-day hold, shown as "you versus the capped you" on Lab → Patterns → Replay ([#162])
- An FI goal can be set in the desk profile, and the FI forecast falls back to it ([#152], [#155])
- Settings → Box gains Deploy now ([#154])
- An outside review of the app at 1.0.9, with a rework gameplan ([#153])

### Changed

- The paper gate is a stored verdict at day 182 and every 91 days after, judged against a noise band with a minimum of 30 buys; each leaderboard row shows the chance its lead is luck, is ranked inside its own benchmark and is greyed under 60 days; deflated Sharpe counts trials across a whole strategy family. `/api/engine/lab/leaderboard` rows drop `days_to_eligible`, `eligible_on` and `waiting_on` and gain a per-row benchmark, `gate`, `score`, `luck`, `young` and `checkpoint_on` ([#160])
- Mixes leads with time to FI by monthly deposit, with a lower-returns switch; "As held" is modelled and papered as a drifting hold; every mix carries its fund fees; conviction positions get a hold, rebalance or trim view ([#164])
- Safe mix and dip-buy are built in and no longer depend on an Escape Vektor plan; market history loads on a new box without waiting for the monthly job ([#155])
- The Debrief desk writes week, month and year when they close and never refuses a quiet period ([#150])

### Fixed

- Backups pass again: the live quotes table no longer trips a false integrity error on the box's SQLite version ([#155])
- A failed backup no longer leaves a deploy half-applied, the alert says why it failed, and the eval debug log is no longer exported ([#154])
- The insider job survives malformed symbols and skips a refused batch instead of failing ([#155])
- A buy on margin, or one that has not settled, shows as margin debt instead of an invented deposit ([#158])
- A mover's return on a review comes from the same prices as its dollar contribution ([#155])

## 1.0.9 - 2026-11-10

### Added

- Conviction holds (ASTS) get their own band, are exempt from the single-stock band, and Preflight blocks buys past the band or on margin; a weekly trim alert fires only above the band ([#142], [#143])
- Conviction holds and the desk profile can be edited from the app, with no SSH ([#142], [#144])
- Debrief desk writes a short review of each day, week, month and year (what happened, why, what to watch, up to 3 next steps) with a phone alert; it starts once the period results land ([#147])
- The desk says when the day's results review didn't run, in `deploy.sh check`, in status and by phone alert ([#146])

## 1.0.8 - 2026-11-08

### Added

- Risk check: eight questions plus your FI horizon, savings rate and emergency fund set a risk band from 1 to 5, versioned, and the band replaces `risk_level` everywhere ([#125], [#132], [#137])
- Strategy catalog: safe mix, as held, aggressive tech tilt and dip-buy race side by side, each in its own Alpaca paper sleeve with ETF proxies ([#127])
- Lab → Mixes shows each mix's range of outcomes over 1 to 40 years, a bad year, its chance of reaching FI and how it fits your risk band ([#127], [#139])
- The leaderboard shows Sharpe, Sortino, max drawdown, Calmar and hit rate for each strategy, plus its backtest ([#133], [#139])
- Discount days: a scanner flags held, watchlist and quality names that fell hard, the research desk writes a buy, wait or avoid case for each, and the Bridge shows them ([#129], [#133], [#140])
- Settings → Box runs redeploy, status, check, backup, restore drill, logs and box script updates from buttons, and applies a changed compose file unless the change widens container access ([#126], [#128], [#134], [#135], [#138])
- Settings → Keys saves keys to the box without a terminal; values are sealed to the host, never shown back, and live Alpaca keys are refused ([#136], [#138])
- Broker exports upload straight into the inbox from Settings ([#130], [#134])
- A first-run checklist runs box setup from buttons, and the Symbol sheet shows the latest filing read ([#131], [#127])

### Changed

- Desks measure against your risk band and the strategy catalog, never one fixed plan ([#129])
- The strategy desk waits for the small-cap history before insider and drift nights, and registers filings lane variants (forward paper only) ([#122], [#123])

## 1.0.7 - 2026-11-08

### Added

- The lab can backtest insider-buying clusters in point-in-time small caps, built from SEC insider data since 2016 plus live Form 4s ([#118])
- The lab can backtest post-earnings drift in point-in-time small caps, using SEC first-filed EPS and 8-K release times ([#120])
- The leaderboard shows what each strategy's paper account did, and lists every filing-lane variant ([#117])

### Changed

- Small-cap lab verdicts count names without prices and stress-test delistings as total losses, so a strategy can't pass on survivors alone ([#119])

## 1.0.6 - 2026-11-08

### Added

- The engine paper-trades every lab strategy and the filings lane on the Alpaca paper account, each strategy in its own $1,000 sleeve with its own ledger; orders net into one day order per symbol, only on a paper account, and `DESK_PAPER_EXECUTE=0` stops them ([#115])
- The Strategy lab opens with a Race to live leaderboard of paper strategies against IWM, with the filings lane as one row ([#114], [#115])
- Settings › Desks switches each desk on or off and lifts the first-run guard, so no more editing desk.yaml ([#113], [#114])
- Strategy desk proposes one new variant a night, rotating through insider clusters, post-earnings drift and the filings lane ([#113])
- Alpaca free daily bars, a nightly small-cap universe ($50M–$2B with a liquidity floor) and an EDGAR new-filings feed for the filings lane ([#108])

### Fixed

- A snapshot that carries older closes is dated by those closes, so later trades roll forward on top: shares no longer revert, fake withdrawals are gone and margin debt stays ([#112])
- The FI forecast uses net deposits (money in minus money out) ([#112])
- 401(k) fund prices are spread between snapshots, so 1D and 1W returns have no snapshot-day jumps ([#112])
- History and flows checks warn only when something is actually wrong ([#112])

## 1.0.5 - 2026-11-08

### Added

- Settings has a Jobs panel with Run now for every scheduled job, and the health banner's Refresh data runs the job that fixes the failing check, so nothing needs SSH ([#102], [#107])
- The engine imports Fidelity's activity-and-orders history JSON: broker rows win over Escape Vektor's activity, tax lots and realized gains are rebuilt (FIFO for stocks and ETFs, average cost for mutual funds) with wash-sale disallowance, and margin interest is tracked ([#104])
- Filings desk scores up to 40 new small-cap SEC filings a night for the forward paper lane; advisory only, off by default ([#105])
- Alpaca paper keys can be set with `setup-truenas.sh set`, and `deploy.sh check` verifies the paper account; any non-paper Alpaca URL is refused ([#103])
- `setup-truenas.sh set KEY` changes one setting and redeploys, and `deploy.sh redeploy` re-reads env files ([#97])

### Changed

- Plan reads deposits from your activity, lists the rhythm it found and the money that came in, and shows irregular deposits as landed, never late ([#98], [#100])
- The FI forecast uses your average monthly deposits from the last 12 months of activity ([#99])
- Deposits, fills and unmatched trades read the imported broker history first ([#106])

## 1.0.4 - 2026-11-08

### Added

- `deploy.sh status` says when the installed compose is older than the checkout ([#92])

### Changed

- Deposits default to auto: the desk reads deposits from activity at each sync, predicts dates only for a clear pattern, and treats irregular cash as money-in that never reads as late or missed; `profile deposits-auto` switches an existing desk.yaml ([#95])

### Fixed

- Synced buys and sells without quantities roll forward correctly, so trades no longer show as losses, fake deposits or margin buys ([#94])
- Recomputed days drop triggers that no longer hold, stale broker snapshots are called out, and every missing key warns with one fix ([#94])
- Agent runs no longer fail on the Claude CLI rejecting the output schema ([#93])
- Transfers with EFT/ACH wording count as deposits or withdrawals in returns ([#90])
- The eval container takes sessions started from Claude projects and exports its redacted debug log ([#91])

## 1.0.3 - 2026-11-07

### Added

- `python -m desk.decisions.profile init --deposits` prints a deposits block to paste into an existing desk.yaml ([#88])

### Fixed

- Snapshot changes Escape Vektor didn't log (deposits, contributions, margin buys) count as money in or out, not return, and plan funds valued from snapshots no longer fire daily-move alerts ([#87])
- Deposit detection finds monthly brokerage transfers among one-off deposits, duplicate imports and transfer-coded rows, and the profile command runs without a warning ([#88])
- The eval container accepts its workspace trust and Remote Control prompts on its own ([#86])
- The TrueNAS app card's icon and Web UI button show without a manual refresh ([#85])

## 1.0.2 - 2026-11-07

### Changed

- The desk uses Escape Vektor's logo for its app icon, browser tab, phone home-screen icon and header mark ([#83])

## 1.0.1 - 2026-11-07

### Added

- Vektor Desk has its own logo: TrueNAS app icon, browser tab icon, phone home-screen icon and header mark ([#81])
- TrueNAS Apps shows the desk's icon and a Web UI button to the home-network address; `deploy.sh card` puts them back after YAML edits ([#80])

## 1.0.0 - 2026-11-07

Production-ready on the TrueNAS box with real data. Every roadmap phase is complete, every page passed a 480-shot sweep at three widths in both themes, and a backup restored cleanly.

### Added

- `python -m desk.decisions.profile init` drafts `desk.yaml` from the mirror (deposit cadence and amounts, accounts for wash-sale checks, plan sleeves and guardrails) and never overwrites; `/api/decisions/profile/status` shows which settings are still defaults ([#70])
- Settings shows the desk profile (version, what's still default, desks on, and a starter command when there is no desk.yaml) ([#76])
- Every page shows an engine health banner while checks fail or warn ([#75])
- The desk also answers at home at https://desk-lan.escape-vektor.com on a NAS LAN alias, with no router forward ([#79])
- Eval container lets a Claude Remote Control session QA the box read-only, with redacted service logs in data/run/logs ([#72])
- `python -m desk.engine daily --dry-run` and `python -m desk.agents dry-run <desk>` write nothing ([#71], [#73])

### Changed

- Agents refuse to run on failing engine health, start with only the Plan keeper and Tax desk, and hold their caps and queue under real cron timing ([#73])
- The plan keeper gets 10 runs a week, so trigger runs fit under the cap ([#74])

### Fixed

- Engine prices held symbols from Tiingo when Escape Vektor's closes lag, values snapshot days at the broker's price, classifies funds without Escape Vektor profiles, and gives every health problem a fix line ([#71])
- Departures board letters no longer render mirrored, long fund codes fit, and contrast passes across charts, tax badges and Preflight lamps ([#75])
- Deploys no longer refuse to run while the desk is idle ([#78])

## 0.11.0 - 2026-11-07

Foundation is done: the desk is live on the TrueNAS box over Tailscale, reading Escape Vektor's data through the read-only mirror. Every roadmap phase is now complete; 1.0 hardening is what's left.

### Added

- `deploy.sh restore-test` restore drill; Firestore errors now say why ([#67])

### Fixed

- The setup doc puts the reader account in the right project ([#67]) and says to open the desk in any browser with Tailscale connected ([#68])

## 0.10.0 - 2026-11-07

Scout and FI scenarios are done, so every planned phase is built. What remains for 1.0 is hardening on the box.

### Added

- Plan gains an FI path card (Monte Carlo fan, on-time odds, FI date range), and Lab Risk gains a factor exposure view with portfolio and per-holding loadings ([#65])

### Fixed

- The lab service no longer waits on a health check it can't pass ([#63])
- The setup doc warns against removing the locally built images when deleting the app ([#64])

## 0.9.0 - 2026-11-07

Flight record and Patterns are done: every decision is scored against following the plan, and each desk has a record you can judge it by.

### Added

- Flight record and Patterns pages; Journal rows show their latest score; plainer holdout copy on strategy pages ([#61])

### Fixed

- The setup script no longer stops when the checkout folder already exists, and it says where it stopped when something fails ([#60])

## 0.8.0 - 2026-11-07

The Strategy lab is done: strategies are specced, tested on history without seeing the future, and paper-traded for six months before any of them can inform a proposal.

### Added

- Strategy lab pages: stage rail, strategy tear sheets with verdict lamps and paper trading, and rule tests against never selling ([#58])
- Strategy detail carries the frozen spec, and list rows carry the hypothesis ([#57])

## 0.7.0 - 2026-11-07

Lab Compare and risk is done, which completes Tier 2 (phases 6 to 8). The engine is now complete through phase 11; the Strategy lab, Flight record and FI views come next.

### Added

- Lab Compare, Risk and Saved boards pages, with diverging bar, heatmap and scatter charts ([#55])
- FI Monte Carlo: 10,000 paths over US market history since 1926 using your Escape Vektor FI goal, plan mix, fees and deposits, with the FI date at the 10th, 50th and 90th percentile, the chance of reaching it on time and the return you'd need; factor exposure per holding for market, size, value, profitability, investment and momentum ([#54])

## 0.6.0 - 2026-11-07

Research is done, and phone alerts are complete with trigger hits. The Strategy lab and Flight record engines landed alongside; their views come next.

### Added

- Research views (dossiers, sources, watchlist, calendar), the Console popup, symbol search and dossiers in the symbol sheet ([#52])
- Research dossiers carry a verdict and today's value on the valuation strip ([#48])
- Strategy lab: spec parsing, a point-in-time simulator with costs, taxes and delistings, walk-forward with a locked two-year holdout, trial ledger, deflated Sharpe and PBO, nightly paper portfolios eligible after 182 days, and `/api/lab/strategies` ([#45])
- The lab runs on the box as its own no-network service, with overnight sweeps from 1 to 6 ET ([#47])
- Ken French industry, size and momentum portfolios back to 1963, a six-factor alpha check on every strategy, and backtests of your own rules (rebalance bands, deposit steering, harvest thresholds, margin on dips) over every start month; watchlist API ([#49])
- The Strategy desk works with the real lab, tests your plan rules and reads factor checks and French results plainly ([#48], [#50])
- Flight record engine: every decision scored at 30, 90 and 365 days against the plan, desk records, calibration, saves and the cost of off-plan trades; Patterns with base rates, drawdown recovery history and your own buying habits ([#51])

## 0.5.0 - 2026-11-07

Tier 1 is code complete: Bridge, Plan, Decisions with Preflight, and the Plan keeper and tax desk with their brief, crew tiles and tax calendar. It runs on demo data until the one-time box setup finishes phase 1. The Lab's compare and risk engine landed alongside.

### Added

- Today's brief on the Bridge; crew tiles with switches, kill switch, weekly usage and run log in Settings; tax calendar with wash-sale windows on the Plan page ([#44])
- Lab compare and risk engine: VaR/CVaR, beta, correlations, Sharpe/Sortino, capture, active share, scenario shocks, N-PORT look-through and sectors, plan adherence, after-tax account returns, and `/api/compare` ([#43])

## 0.4.0 - 2026-11-07

Decisions and Preflight are done: every proposal now shows its Preflight lights, an override needs a reason, and the Journal keeps score. The research data feeds for phase 6 landed alongside.

### Added

- Decisions page with the proposal queue, Preflight annunciator, override box and order ticket; Journal with the stamped ledger, discipline streak and unmatched trades; top three proposals on the Bridge ([#41])
- Nightly research data from SEC EDGAR, FRED and Finnhub (filings, company facts, earnings, insider trades, rates and VIX), with holding signals, macro metrics, an earnings trigger, and `/api/engine/research` and `/api/engine/macro` ([#40])

## 0.3.0 - 2026-11-07

Engine core and Plan are done. Preflight, desk brief slices and triggers from phases 4 and 5 landed alongside, so the Plan keeper and tax desk now run on real engine numbers.

### Added

- Bridge gets a 7-tile KPI row with drawers, value versus the plan and S&P 500 shadows, cockpit gauges and drift bullets; new Plan page with rules, funds and a modelled deposit split ([#37])
- Preflight for every trade idea (six lamps with before and after, margin cost in dollars, lot picks and short/long-term gain, wash-sale checks across accounts), plus realized and unrealized gains, harvestable losses and a wash-sale calendar (`POST /api/preflight`, `/api/engine/preflight`, `/api/engine/wash`) ([#35])
- Engine brief slices for each agent desk, daily triggers (margin debit, big moves, concentration, rule breaches, lot exports, landed deposits) with phone alerts the first day they appear, marginal tax rate from Escape Vektor's tax estimate, and harvest value ([#36])
- Rule breaches and landed deposits wake the Plan keeper, and the agents read the real engine brief ([#38])

## 0.2.0 - 2026-11-07

Bridge and Symbol sheet are live on demo data, the engine core behind phase 3 is in, and phone alerts are wired through every package.

### Added

- Bridge with the departures board, Symbol sheet, KPI tiles with drill drawers, a value chart with table view, and a market clock that follows the live feed ([#33])
- Engine core: flows, TWR and XIRR, plan and S&P 500 shadow portfolios, drift and rule checks, margin cost and call distance, concentration, drawdown and costs, with data health and `/api/engine/metrics`, `/series`, `/health`, `/prices` and `/api/live/intraday` ([#30])
- Phone alerts through a self-hosted ntfy server on the desk node: `desk.notify.publish()` for every package, alerts, research and ops topics, daily stale-mirror and token-renewal checks, and deploy and backup failure alerts ([#26])
- Decisions: phone alerts for new desk proposals, late deposits, trades without a decision record and wash-sale windows clearing, with an `alerts.min_priority` dial ([#27])
- Agents: phone alerts when a Console answer or research dossier is ready and when a desk run fails ([#28])
- One-time setup checklist ([docs/setup.md](docs/setup.md)) and `scripts/check.sh`, which runs every local check a PR needs; auto-deploy alerts the phone when a deploy needs a hand step ([#29])
- Compose check runs off the box ([#32])

## 0.1.0 - 2026-11-07

Foundation is code complete and runs on synthetic demo data; the box itself waits on the one-time setup. Early pieces of later phases landed alongside it.

### Added

- Infrastructure: compose stack for TrueNAS (Tailscale sidecar, Caddy with Porkbun DNS-01), read-only Firestore mirror with change history, scheduler, backups, deploy and setup scripts ([#5])
- Package seams: routers from `desk/*/api.py`, schemas from `desk/*/schema.py` applied to `desk.db` at startup, jobs from `desk/*/jobs.py` under run locks, and shared test fixtures ([#9])
- Synthetic demo data: `desk/demo.py` builds a two-year synthetic `mirror.db` for tests and demo mode (`DESK_DEMO=1`) ([#14])
- The image builds the web app from `ui/` and the API serves it with client-side route fallback ([#17])
- UI shell with pill nav, phone dock, market clock, light and graphite themes, and a Settings page showing mirror freshness and the Claude token ([#21])
- Engine: daily holdings rebuilt from the mirror's change history, with `/api/engine/holdings` and `/api/engine/value` ([#11])
- Engine: Fidelity lot and realized gain/loss export import from `inbox/fidelity/`, with `/api/engine/lots` ([#16])
- Engine: live quotes and `/api/live` (live value, day change, stale flag), market clock with NYSE holidays, and a capped Tiingo daily-history backfill ([#19])
- Decisions: desk profile from `desk.yaml` and versioned plan rules, every rule change logged as a decision record ([#12])
- Decisions: decision records with Preflight results, overrides and reasons; queue, order tickets, journal, unmatched-trade logging and coverage summary; Python API for the agents ([#20])
- Decisions: deposit schedule with landed, late and expected paydays, and a tax calendar of year-end dates, deposits, wash-sale clear dates and your own events ([#22])
- Agents runner: `claude -p` adapter on the subscription, fake adapter, run log, Settings switches, weekly caps and `/api/agents/status` ([#10])
- Plan keeper and tax desk on the engine brief, with a number check and proposals written to decision records; brief and run log endpoints ([#15])
- Research desk with dossiers, Skeptic counter-cases, risk desk, Console questions (run now or tonight), and engine triggers that wake the right desk ([#18])
- Strategy desk writing experiment requests for the lab, lab reviews, and Scout drawing on lab-eligible strategies ([#23])
- Cross-package integration tests: every package router mounted, every read endpoint answering on demo data, jobs discovered under run locks, and the plan keeper writing real decision records on demo data ([#24], [#25])

## 0.0.0 - 2026-11-07

Planning: concept, architecture, statistics, agents and design plans, roadmap and project plan ([#1], [#2], [#3], [#4], [#6]).

[#1]: https://github.com/inzodious/vektor-desk/pull/1
[#2]: https://github.com/inzodious/vektor-desk/pull/2
[#3]: https://github.com/inzodious/vektor-desk/pull/3
[#4]: https://github.com/inzodious/vektor-desk/pull/4
[#5]: https://github.com/inzodious/vektor-desk/pull/5
[#6]: https://github.com/inzodious/vektor-desk/pull/6
[#9]: https://github.com/inzodious/vektor-desk/pull/9
[#10]: https://github.com/inzodious/vektor-desk/pull/10
[#11]: https://github.com/inzodious/vektor-desk/pull/11
[#12]: https://github.com/inzodious/vektor-desk/pull/12
[#14]: https://github.com/inzodious/vektor-desk/pull/14
[#15]: https://github.com/inzodious/vektor-desk/pull/15
[#16]: https://github.com/inzodious/vektor-desk/pull/16
[#17]: https://github.com/inzodious/vektor-desk/pull/17
[#18]: https://github.com/inzodious/vektor-desk/pull/18
[#19]: https://github.com/inzodious/vektor-desk/pull/19
[#20]: https://github.com/inzodious/vektor-desk/pull/20
[#21]: https://github.com/inzodious/vektor-desk/pull/21
[#22]: https://github.com/inzodious/vektor-desk/pull/22
[#23]: https://github.com/inzodious/vektor-desk/pull/23
[#24]: https://github.com/inzodious/vektor-desk/pull/24
[#25]: https://github.com/inzodious/vektor-desk/pull/25
[#26]: https://github.com/inzodious/vektor-desk/pull/26
[#27]: https://github.com/inzodious/vektor-desk/pull/27
[#28]: https://github.com/inzodious/vektor-desk/pull/28
[#29]: https://github.com/inzodious/vektor-desk/pull/29
[#30]: https://github.com/inzodious/vektor-desk/pull/30
[#32]: https://github.com/inzodious/vektor-desk/pull/32
[#33]: https://github.com/inzodious/vektor-desk/pull/33
[#35]: https://github.com/inzodious/vektor-desk/pull/35
[#36]: https://github.com/inzodious/vektor-desk/pull/36
[#37]: https://github.com/inzodious/vektor-desk/pull/37
[#38]: https://github.com/inzodious/vektor-desk/pull/38
[#40]: https://github.com/inzodious/vektor-desk/pull/40
[#41]: https://github.com/inzodious/vektor-desk/pull/41
[#43]: https://github.com/inzodious/vektor-desk/pull/43
[#44]: https://github.com/inzodious/vektor-desk/pull/44
[#45]: https://github.com/inzodious/vektor-desk/pull/45
[#47]: https://github.com/inzodious/vektor-desk/pull/47
[#48]: https://github.com/inzodious/vektor-desk/pull/48
[#49]: https://github.com/inzodious/vektor-desk/pull/49
[#50]: https://github.com/inzodious/vektor-desk/pull/50
[#51]: https://github.com/inzodious/vektor-desk/pull/51
[#52]: https://github.com/inzodious/vektor-desk/pull/52
[#54]: https://github.com/inzodious/vektor-desk/pull/54
[#55]: https://github.com/inzodious/vektor-desk/pull/55
[#57]: https://github.com/inzodious/vektor-desk/pull/57
[#58]: https://github.com/inzodious/vektor-desk/pull/58
[#60]: https://github.com/inzodious/vektor-desk/pull/60
[#61]: https://github.com/inzodious/vektor-desk/pull/61
[#63]: https://github.com/inzodious/vektor-desk/pull/63
[#64]: https://github.com/inzodious/vektor-desk/pull/64
[#65]: https://github.com/inzodious/vektor-desk/pull/65
[#67]: https://github.com/inzodious/vektor-desk/pull/67
[#68]: https://github.com/inzodious/vektor-desk/pull/68
[#70]: https://github.com/inzodious/vektor-desk/pull/70
[#71]: https://github.com/inzodious/vektor-desk/pull/71
[#72]: https://github.com/inzodious/vektor-desk/pull/72
[#73]: https://github.com/inzodious/vektor-desk/pull/73
[#74]: https://github.com/inzodious/vektor-desk/pull/74
[#75]: https://github.com/inzodious/vektor-desk/pull/75
[#76]: https://github.com/inzodious/vektor-desk/pull/76
[#78]: https://github.com/inzodious/vektor-desk/pull/78
[#79]: https://github.com/inzodious/vektor-desk/pull/79
[#80]: https://github.com/inzodious/vektor-desk/pull/80
[#81]: https://github.com/inzodious/vektor-desk/pull/81
[#83]: https://github.com/inzodious/vektor-desk/pull/83
[#85]: https://github.com/inzodious/vektor-desk/pull/85
[#86]: https://github.com/inzodious/vektor-desk/pull/86
[#87]: https://github.com/inzodious/vektor-desk/pull/87
[#88]: https://github.com/inzodious/vektor-desk/pull/88
[#90]: https://github.com/inzodious/vektor-desk/pull/90
[#91]: https://github.com/inzodious/vektor-desk/pull/91
[#92]: https://github.com/inzodious/vektor-desk/pull/92
[#93]: https://github.com/inzodious/vektor-desk/pull/93
[#94]: https://github.com/inzodious/vektor-desk/pull/94
[#95]: https://github.com/inzodious/vektor-desk/pull/95
[#97]: https://github.com/inzodious/vektor-desk/pull/97
[#98]: https://github.com/inzodious/vektor-desk/pull/98
[#99]: https://github.com/inzodious/vektor-desk/pull/99
[#100]: https://github.com/inzodious/vektor-desk/pull/100
[#102]: https://github.com/inzodious/vektor-desk/pull/102
[#103]: https://github.com/inzodious/vektor-desk/pull/103
[#104]: https://github.com/inzodious/vektor-desk/pull/104
[#105]: https://github.com/inzodious/vektor-desk/pull/105
[#106]: https://github.com/inzodious/vektor-desk/pull/106
[#107]: https://github.com/inzodious/vektor-desk/pull/107
[#108]: https://github.com/inzodious/vektor-desk/pull/108
[#112]: https://github.com/inzodious/vektor-desk/pull/112
[#113]: https://github.com/inzodious/vektor-desk/pull/113
[#114]: https://github.com/inzodious/vektor-desk/pull/114
[#115]: https://github.com/inzodious/vektor-desk/pull/115
[#117]: https://github.com/inzodious/vektor-desk/pull/117
[#118]: https://github.com/inzodious/vektor-desk/pull/118
[#119]: https://github.com/inzodious/vektor-desk/pull/119
[#120]: https://github.com/inzodious/vektor-desk/pull/120
[#122]: https://github.com/inzodious/vektor-desk/pull/122
[#123]: https://github.com/inzodious/vektor-desk/pull/123
[#125]: https://github.com/inzodious/vektor-desk/pull/125
[#126]: https://github.com/inzodious/vektor-desk/pull/126
[#127]: https://github.com/inzodious/vektor-desk/pull/127
[#128]: https://github.com/inzodious/vektor-desk/pull/128
[#129]: https://github.com/inzodious/vektor-desk/pull/129
[#130]: https://github.com/inzodious/vektor-desk/pull/130
[#131]: https://github.com/inzodious/vektor-desk/pull/131
[#132]: https://github.com/inzodious/vektor-desk/pull/132
[#133]: https://github.com/inzodious/vektor-desk/pull/133
[#134]: https://github.com/inzodious/vektor-desk/pull/134
[#135]: https://github.com/inzodious/vektor-desk/pull/135
[#136]: https://github.com/inzodious/vektor-desk/pull/136
[#137]: https://github.com/inzodious/vektor-desk/pull/137
[#138]: https://github.com/inzodious/vektor-desk/pull/138
[#139]: https://github.com/inzodious/vektor-desk/pull/139
[#140]: https://github.com/inzodious/vektor-desk/pull/140
[#142]: https://github.com/inzodious/vektor-desk/pull/142
[#143]: https://github.com/inzodious/vektor-desk/pull/143
[#144]: https://github.com/inzodious/vektor-desk/pull/144
[#146]: https://github.com/inzodious/vektor-desk/pull/146
[#147]: https://github.com/inzodious/vektor-desk/pull/147
[#148]: https://github.com/inzodious/vektor-desk/pull/148
[#150]: https://github.com/inzodious/vektor-desk/pull/150
[#151]: https://github.com/inzodious/vektor-desk/pull/151
[#152]: https://github.com/inzodious/vektor-desk/pull/152
[#153]: https://github.com/inzodious/vektor-desk/pull/153
[#154]: https://github.com/inzodious/vektor-desk/pull/154
[#155]: https://github.com/inzodious/vektor-desk/pull/155
[#156]: https://github.com/inzodious/vektor-desk/pull/156
[#157]: https://github.com/inzodious/vektor-desk/pull/157
[#158]: https://github.com/inzodious/vektor-desk/pull/158
[#159]: https://github.com/inzodious/vektor-desk/pull/159
[#160]: https://github.com/inzodious/vektor-desk/pull/160
[#161]: https://github.com/inzodious/vektor-desk/pull/161
[#162]: https://github.com/inzodious/vektor-desk/pull/162
[#163]: https://github.com/inzodious/vektor-desk/pull/163
[#164]: https://github.com/inzodious/vektor-desk/pull/164
[#165]: https://github.com/inzodious/vektor-desk/pull/165

# Changelog

Notable changes to Vektor Desk. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html): each roadmap phase is a minor version, and fixes between phases are patches. Planned work is in [ROADMAP.md](ROADMAP.md).

## Unreleased

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

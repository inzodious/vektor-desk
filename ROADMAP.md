# Roadmap

Each phase is one pull request (or one short series) and one minor version: phase 3 ships as 0.3.0. Status: ✅ done, 🚧 in progress, ⏭️ next, 📋 planned. Areas and tiers come from [docs/concept.md](docs/concept.md).

Planning merged November 7, 2026. Building now; several workstreams build their pieces of a phase in parallel.

## Phases

| # | Phase | Tier | Status | Depends on |
|---|---|---|---|---|
| 0 | Planning docs | | ✅ | |
| 1 | Foundation | 1 | 🚧 (code done, box setup pending) | 0 |
| 2 | Bridge and Symbol sheet | 1 | ✅ | 1 |
| 3 | Engine core and Plan | 1 | ✅ | 2 |
| 4 | Decisions and Preflight | 1 | ✅ | 3 |
| 5 | Plan keeper and tax desk | 1 | ✅ | 4 |
| 6 | Research | 2 | 🚧 | 4 |
| 7 | Lab: Compare and risk | 2 | 🚧 | 3 |
| 8 | Phone alerts | 2 | 📋 | 5 |
| 9 | Strategy lab | 3 | 📋 | 3, 6 |
| 10 | Flight record and Patterns | 3 | 📋 | 30 days of decision records |
| 11 | Scout and FI scenarios | 3 | 📋 | 10 |
| 1.0 | Hardening | | 📋 | 11 |

Phases 6 and 7 can run in parallel with 5 once their dependencies land, and phase 9 can run beside 7, 8 and 10. Start the Strategy lab as early as its dependencies allow: six months of forward paper trading is its graduation bar. The agent runner and its fake adapter are built alongside phases 3 and 4, so phase 5 only wires them to real engine outputs.

**Who builds what inside a phase.** Preflight's checks are deterministic engine code (Statistics); Design renders them; agents call them. The decision record's fields come from the concept; agents write proposals into it.

## December target

Concept's success measure is that December's loss-sale plan comes from the desk. That needs Tier 1 (phases 1 to 5) merged and running by **December 6**. It is a target, not a gate: year-end tax moves do not wait on the desk, and the Nov 17–21 quiet window takes a week out of the schedule.

## Phase detail

### 0. Planning docs ✅

- [x] README, ROADMAP, project plan, repo conventions (Lead, [#3])
- [x] Concept: purpose, areas, loops, tiers (Concept, [#1])
- [x] Architecture: stack, network, mirror, storage, secrets, alerts (Infrastructure, [#5])
- [x] Statistics: metric catalogue, methods, engine output contract (Statistics, [#4])
- [x] Agents: desks, schedules, tools, guardrails, usage budget, proposal record (AI agents, [#2])
- [x] Design: look, navigation, page and board mockups (Dashboards and design, [#6])

Done when all six are merged and agree with each other.

### 1. Foundation 🚧

- [x] Compose stack on TrueNAS: Tailscale sidecar, Caddy, api (serves the built UI), cron (scheduler, engine and agents) ([#5])
- [ ] `desk.escape-vektor.com` resolves on the tailnet with a valid certificate (built in [#5]; needs Joshua's one-time setup steps in `docs/architecture.md`)
- [x] Read-only mirror of every `lockIn/{uid}` collection into SQLite, incremental by change time with a weekly full pass, with change history ([#5])
- [x] `holdings_daily` built from the mirror history from day one (Statistics) ([#11])
- [x] Claude Code CLI in the cron service (Hemline's pattern), token in a root-only env file, smoke run with `deploy.sh check` (no `--bare`) ([#5]); desks get the brief on stdin and no file, shell or MCP tools, web tools only for Research and Scout ([#10])
- [x] Backups of the desk database ([#5])
- [x] App shell in the Escape Vektor look: tokens in `ui/src/styles`, pill nav and phone dock, light and graphite dark ([#21])
- [x] Settings: data freshness and token card (`/api/status` in [#5]; page by Design) ([#21])
- [x] Local lint, test and build scripts; synthetic fixtures ([#14], [#17])

Done when a phone on Tailscale opens the desk and sees the mirror's last run. **Code complete (0.1.0); waiting on Joshua's one-time setup** in `docs/architecture.md`, which also gives the first real `claude -p` smoke run.

### 2. Bridge and Symbol sheet ✅

- [x] Live price feed during market hours, last close outside them (live quotes table, `/api/live`) ([#19])
- [x] Bridge: departures-board holdings strip, KPI tiles, market clock states ([#33])
- [x] Symbol sheet from any symbol chip: price, position across accounts, cost basis, lots ([#33])
- [x] Line and spark charts (hand-rolled SVG, no chart library) ([#33])
- [x] Fidelity lot export parser and lots table (Dec 6 risk) ([#16])

### 3. Engine core and Plan ✅

- [x] Engine (Python): flow classifier, reconciliation and `data_health`, value and flows, TWR and XIRR ([#30])
- [x] Shadow portfolios: plan mix and S&P 500 ([#30])
- [x] Drift and rules, margin (interest in dollars, price drop to a call), costs, basic concentration and drawdown ([#30])
- [x] Output contract v1 ([#30])
- [x] Background backfill for the Strategy lab starts here: Tiingo prices at about 400 new symbols a month under the free cap shared with Escape Vektor (ETFs first, then large caps including delisted ones), SEC bulk financial statement and insider data in one import ([#19])
- [x] Bridge KPI row complete, drift bullets, gauges ([#37])
- [x] Plan page: target mix and bands, drift, rules (versioned), deposit routing ([#12], [#22], [#30], [#37])

### 4. Decisions and Preflight ✅

- [x] Decision records for every action and deliberate pass; logging starts here so scoring has history later ([#20])
- [x] Preflight lights (engine, `preflight(holdings, trade)`): concentration, drift, funding and margin interest, wash sales across all accounts, lots and realized gain or loss, rule breaks ([#35])
- [x] Tax lots, wash-sale calendar, realized gain and loss ([#16], [#35])
- [x] Preflight annunciator (`POST /api/preflight`) and override box with a one-line reason ([#35], [#41])
- [x] Order tickets, marked placed, confirmed by the mirror ([#20])
- [x] Queue with proposal cards; Journal as a stamped ledger ([#20], [#41])

### 5. Plan keeper and tax desk ✅

- [x] Agent proposal record, written into the queue ([#15], [#20])
- [x] Engine: per-desk brief slices, triggers table, marginal tax rate ([#36])
- [x] Plan keeper: daily brief, payday split, rule breach flags ([#15], [#36], [#38])
- [x] Tax desk: harvest candidates, lot picks, wash-sale windows, tax calendar ([#15], [#22], [#35], [#36])
- [x] Brief card; crew tiles with agent status, run log and usage per run ([#10], [#15], [#44])
- [x] Tax calendar view ([#44])

Tier 1 code complete: 0.5.0. It runs on demo data until the box setup in [docs/setup.md](docs/setup.md) finishes phase 1.

### 6. Research 🚧

- [ ] Dossiers per symbol and theme, with sources and "what would change the call"
- [x] Research desk, on request (overnight by default) and on a weekly rotation, with a skeptic run checking each dossier ([#18])
- [ ] Dossier and sources views; Console to request research and talk to the desks (backend [#18]; views to come)
- [ ] Watchlist and engine triggers into the queue: big daily move, band crossed, margin debit appears, earnings date, new lot export (triggers [#36], [#38], [#40]; watchlist to come)
- [ ] Source library: SEC EDGAR filings, insider trades, 13F, earnings dates, FRED series (data [#40]; 13F and views to come)
- [x] Engine: EDGAR, FRED and Finnhub fetchers and holding signals ([#40])

### 7. Lab: Compare and risk 🚧

- [ ] Compare two to five items over a period, with fund overlap (N-PORT look-through) (engine [#43]; views to come)
- [ ] Risk and statistics: concentration, exposure, scenario shocks, margin stress; heatmap and scatter views (engine [#43]; views to come)
- [ ] Saved boards shell (`/api/compare`) (endpoint [#43]; shell to come)
- [x] Risk desk weekly report ([#18])

### 8. Phone alerts 📋

- [ ] Self-hosted ntfy on the box, relaying through ntfy.sh for phone delivery: rule breach, trigger hit, wash-sale window, stale mirror, research ready (server, stale mirror, proposals, wash-sale and research alerts [#26], [#27], [#28]; trigger-hit alerts to come)

### 9. Strategy lab 📋

Research hypotheses become strategies, tested on history without seeing the future, then paper-traded forward before any of them can inform a proposal.

- [ ] Feature library and strategy spec validation
- [ ] Walk-forward runner over 3, 5 and 10 year windows, point-in-time data only; ETF and Ken French universes first
- [ ] Trial ledger: every strategy tried is recorded, so overfitting tests count them all
- [ ] Deflated Sharpe and overfitting tests
- [x] Strategy desk: turns research desk hypotheses into specs, reads results ([#23])
- [ ] Forward paper portfolios; a strategy is eligible only after six months of forward results
- [ ] Rule backtests for the plan's own rules
- [ ] Strategy lab views (Design mocks them once the spec settles)

### 10. Flight record and Patterns 📋

- [ ] Every decision scored at 30, 90 and 365 days against following the plan (next-close baseline, bootstrap intervals, Brier score)
- [ ] Summaries by origin, type, and overrides versus clean Preflights
- [ ] Patterns: market and his own behavior
- [ ] Saved boards complete

### 11. Scout and FI scenarios 📋

- [x] Scout desk: monthly ideas within the desk profile, each argued against first ([#23])
- [ ] FI path card and scenarios (Monte Carlo percentiles)
- [ ] Factor exposure

### 1.0 Hardening 📋

- [ ] Restore from backup tested
- [ ] Every page checked at 1920, 1440 and 390 in light and dark
- [ ] Six months of Flight record reviewed; desks that do not beat following the plan are switched off

## Key dates

| Date | What |
|---|---|
| 2026-11-07 | Repo created, planning starts |
| Nov 17–21 | Quiet window, no merges expected |
| Dec 6 | Tier 1 target |
| Dec 12–16 | Quiet window, no merges expected |

## Backlog

- Options and crypto, if he starts holding them

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
[#26]: https://github.com/inzodious/vektor-desk/pull/26
[#27]: https://github.com/inzodious/vektor-desk/pull/27
[#28]: https://github.com/inzodious/vektor-desk/pull/28
[#30]: https://github.com/inzodious/vektor-desk/pull/30
[#33]: https://github.com/inzodious/vektor-desk/pull/33
[#35]: https://github.com/inzodious/vektor-desk/pull/35
[#36]: https://github.com/inzodious/vektor-desk/pull/36
[#37]: https://github.com/inzodious/vektor-desk/pull/37
[#38]: https://github.com/inzodious/vektor-desk/pull/38
[#40]: https://github.com/inzodious/vektor-desk/pull/40
[#41]: https://github.com/inzodious/vektor-desk/pull/41
[#43]: https://github.com/inzodious/vektor-desk/pull/43
[#44]: https://github.com/inzodious/vektor-desk/pull/44

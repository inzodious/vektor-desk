# Roadmap

Each phase is one pull request (or one short series) and one minor version: phase 3 ships as 0.3.0. Status: ✅ done, 🚧 in progress, ⏭️ next, 📋 planned. Areas and tiers come from [docs/concept.md](docs/concept.md).

Draft, November 7, 2026. Phase contents firm up as the planning docs land.

## Phases

| # | Phase | Tier | Status | Depends on |
|---|---|---|---|---|
| 0 | Planning docs | | 🚧 | |
| 1 | Foundation | 1 | 📋 | 0 |
| 2 | Bridge and Symbol sheet | 1 | 📋 | 1 |
| 3 | Engine core and Plan | 1 | 📋 | 2 |
| 4 | Decisions and Preflight | 1 | 📋 | 3 |
| 5 | Plan keeper and tax desk | 1 | 📋 | 4 |
| 6 | Research | 2 | 📋 | 4 |
| 7 | Lab: Compare and risk | 2 | 📋 | 3 |
| 8 | Phone alerts | 2 | 📋 | 5 |
| 9 | Flight record and Patterns | 3 | 📋 | 30 days of decision records |
| 10 | Scout and FI scenarios | 3 | 📋 | 9 |
| 1.0 | Hardening | | 📋 | 10 |

Phases 6 and 7 can run in parallel with 5 once their dependencies land. The agent runner and its fake adapter are built alongside phases 3 and 4, so phase 5 only wires them to real engine outputs.

**Who builds what inside a phase.** Preflight's checks are deterministic engine code (Statistics); Design renders them; agents call them. The decision record's fields come from the concept; agents write proposals into it.

## December target

Concept's success measure is that December's loss-sale plan comes from the desk. That needs Tier 1 (phases 1 to 5) merged and running by **December 6**. It is a target, not a gate: year-end tax moves do not wait on the desk, and the Nov 17–21 quiet window takes a week out of the schedule.

## Phase detail

### 0. Planning docs 🚧

- [ ] README, ROADMAP, project plan, repo conventions (Lead)
- [ ] Concept: purpose, areas, loops, tiers (Concept)
- [ ] Architecture: stack, network, mirror, storage, secrets, alerts (Infrastructure)
- [ ] Statistics: metric catalogue, methods, engine output contract (Statistics)
- [ ] Agents: desks, schedules, tools, guardrails, usage budget, proposal record (AI agents)
- [ ] Design: look, navigation, page and board mockups (Dashboards and design)

Done when all six are merged and agree with each other.

### 1. Foundation 📋

- [ ] Compose stack on TrueNAS: api, worker, web, Caddy, Tailscale sidecar
- [ ] `desk.escape-vektor.com` resolves on the tailnet with a valid certificate
- [ ] Read-only mirror of Escape Vektor's Firestore (positions, plans, activity, prices) into SQLite on a schedule
- [ ] Claude Code CLI in the scheduler service (Hemline's pattern), token as a Compose secret, one `claude -p` smoke run (no `--bare`); desks get the brief on stdin and no file, shell or MCP tools, web tools only for Research and Scout
- [ ] App shell in the Escape Vektor look: pill nav and phone dock, light and graphite dark
- [ ] Settings: data freshness, token renewal date
- [ ] Local lint, test and build scripts; synthetic fixtures

Done when a phone on Tailscale opens the desk and sees the mirror's last run.

### 2. Bridge and Symbol sheet 📋

- [ ] Live price feed during market hours, last close outside them
- [ ] Bridge: holdings strip and first KPIs
- [ ] Symbol sheet from any symbol chip: price, position across accounts, cost basis, lots
- [ ] Fidelity lot export import

### 3. Engine core and Plan 📋

- [ ] Engine computes the Tier 1 metrics in `docs/statistics.md` and publishes the output contract
- [ ] Bridge KPI row complete
- [ ] Plan: target mix and bands, drift, rules (versioned), deposit routing

### 4. Decisions and Preflight 📋

- [ ] Decision records for every action and deliberate pass; logging starts here so scoring has history later
- [ ] Preflight lights: concentration, drift, funding and margin interest, wash sales across all accounts, lots and realized gain or loss, rule breaks
- [ ] Overrides with a one-line reason
- [ ] Order tickets, marked placed, confirmed by the mirror
- [ ] Decision journal and queue

### 5. Plan keeper and tax desk 📋

- [ ] Agent proposal record, written into the queue
- [ ] Plan keeper: daily brief, payday split, rule breach flags
- [ ] Tax desk: harvest candidates, lot picks, wash-sale windows, tax calendar
- [ ] Settings: agent status, run log, usage per run

Tier 1 complete: 0.5.0.

### 6. Research 📋

- [ ] Dossiers per symbol and theme, with sources and "what would change the call"
- [ ] Research desk, on request (overnight by default) and on a weekly rotation, with a skeptic run checking each dossier
- [ ] Console: request research and talk to the desks
- [ ] Watchlist and engine triggers into the queue: big daily move, band crossed, margin debit appears, earnings date, new lot export
- [ ] Source library: SEC EDGAR filings, insider trades, 13F, earnings dates, FRED series

### 7. Lab: Compare and risk 📋

- [ ] Compare two to five items over a period, with fund overlap
- [ ] Risk and statistics: concentration, exposure, scenario shocks, margin stress
- [ ] Risk desk weekly report

### 8. Phone alerts 📋

- [ ] Self-hosted push (choice in `docs/architecture.md`): rule breach, trigger hit, wash-sale window, stale mirror, research ready

### 9. Flight record and Patterns 📋

- [ ] Every decision scored at 30, 90 and 365 days against following the plan
- [ ] Summaries by origin, type, and overrides versus clean Preflights
- [ ] Patterns: market and his own behavior
- [ ] Saved boards

### 10. Scout and FI scenarios 📋

- [ ] Scout desk: monthly ideas within the desk profile, each argued against first
- [ ] FI projection scenarios

### 1.0 Hardening 📋

- [ ] Backups of the desk database
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

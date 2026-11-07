# Roadmap

Each phase is one pull request (or one short series) and one minor version: phase 3 ships as 0.3.0. Status: ✅ done, 🚧 in progress, ⏭️ next, 📋 planned.

Draft, November 7, 2026. Phase order and contents firm up as the planning docs land; each workstream's dependency notes are folded in here.

## Phases

| # | Phase | Status | Depends on |
|---|---|---|---|
| 0 | Planning docs | 🚧 | |
| 1 | Foundation | 📋 | 0 |
| 2 | Track | 📋 | 1 |
| 3 | Stats and KPIs | 📋 | 2 |
| 4 | Compare and Boards | 📋 | 3 |
| 5 | Plan | 📋 | 3 |
| 6 | Decide | 📋 | 4, 5 |
| 7 | Research | 📋 | 1 |
| 8 | Risk desk and Scout | 📋 | 6, 7 |
| 1.0 | Hardening | 📋 | 8 |

## Phase detail

### 0. Planning docs 🚧

- [ ] README, ROADMAP, project plan, repo conventions (Lead)
- [ ] Concept: purpose, core loops, non-goals (Concept)
- [ ] Architecture: stack, network, mirror, storage, secrets (Infrastructure)
- [ ] Statistics: metric catalogue, methods, engine output contract (Statistics)
- [ ] Agents: desks, schedules, tools, guardrails, usage budget (AI agents)
- [ ] Design: look, navigation, page and dashboard mockups (Dashboards and design)

Done when all six are merged and agree with each other.

### 1. Foundation 📋

- [ ] Compose stack on TrueNAS: api, worker, web, Caddy, Tailscale sidecar
- [ ] `desk.escape-vektor.com` resolves on the tailnet with a valid certificate
- [ ] Read-only mirror of Escape Vektor's Firestore into SQLite, on a schedule
- [ ] Claude CLI runner with a smoke run and token expiry on the status page
- [ ] App shell in the Escape Vektor look: navigation, light and graphite dark, status page
- [ ] Local test, lint and build scripts; synthetic fixtures

Done when a phone on Tailscale opens the desk and sees the mirror's last run and row counts.

### 2. Track 📋

- [ ] Positions by account and holding, cost basis, day and total change
- [ ] Price history backfill and live quotes during market hours
- [ ] Tax lot import from the brokerage's lot export
- [ ] Click drill-down: portfolio, account, holding, lot

### 3. Stats and KPIs 📋

- [ ] Engine computes the metric catalogue from `docs/statistics.md`
- [ ] Output contract tables and JSON published for agents and boards
- [ ] KPI strip

### 4. Compare and Boards 📋

- [ ] Benchmarks, holding against holding, plan against actual, follow-the-plan counterfactual
- [ ] Dashboards from `docs/design.md`

### 5. Plan 📋

- [ ] Target mix, drift, deposit routing
- [ ] What-if scenarios
- [ ] Tax calendar: harvest windows, wash-sale windows, year-end dates

### 6. Decide 📋

- [ ] Proposal queue: approve, dismiss, snooze; order tickets
- [ ] Decision journal
- [ ] Plan keeper and tax desk agents
- [ ] Scorecard: every proposal scored at 30 and 90 days against following the plan

### 7. Research 📋

- [ ] Research desk agent, on request and on a weekly rotation
- [ ] Library of deep dives with sources and "what would change the call"
- [ ] SEC EDGAR and FRED feeds

### 8. Risk desk and Scout 📋

- [ ] Weekly risk report: concentration, margin, drawdown and correlation scenarios
- [ ] Monthly scout ideas within the configured risk and industry settings, each argued against before it is shown

### 1.0 Hardening 📋

- [ ] Backups of the desk database
- [ ] Every page checked at 1920, 1440 and 390 in light and dark
- [ ] Six months of scorecard data reviewed; desks that do not beat following the plan are switched off

## Key dates

| Date | What |
|---|---|
| 2026-11-07 | Repo created, planning starts |
| Nov 17–21 | Quiet window, no merges expected |
| Dec 12–16 | Quiet window, no merges expected |

## Backlog

Ideas that are not in a phase yet go here.

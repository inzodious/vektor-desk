# Vektor Desk

A private investing desk for one person, self-hosted on TrueNAS at `desk.escape-vektor.com` and reachable only over Tailscale. It reads Escape Vektor's data, runs the statistics, tracks the portfolio live, and runs Claude Code agents on the Claude subscription that research, plan and propose decisions. It never places trades.

Escape Vektor is the everyday money app. Vektor Desk is the investing cockpit: one focus, more depth.

## Modules

| Module | What it does |
|---|---|
| **Track** | Live positions, prices and day moves, drill-down from portfolio to account to holding to lot in a click |
| **Stats** | Returns, risk, drawdowns, correlation, attribution, scenarios |
| **KPIs** | The few numbers that say whether the plan is working |
| **Compare** | Portfolio against benchmarks, holding against holding, plan against actual, "what if I had followed the plan" |
| **Plan** | Target mix, deposit routing, what-if, tax calendar |
| **Decide** | Proposal queue from the agents, approve or dismiss, order tickets, decision journal, scorecard |
| **Research** | Deep dives with sources, theses, bear cases, a searchable library |
| **Boards** | Dashboards built from the pieces above |

## Docs

| Doc | Owner | What it covers |
|---|---|---|
| [ROADMAP.md](ROADMAP.md) | Lead | Phases, status, dates |
| [docs/project-plan.md](docs/project-plan.md) | Lead | Goal, 1.0 bar, workstreams, how they coordinate, decisions, risks |
| [docs/concept.md](docs/concept.md) | Concept | What the desk is for, the core loops, what it is not |
| [docs/architecture.md](docs/architecture.md) | Infrastructure | TrueNAS stack, network, data mirror, storage, secrets |
| [docs/statistics.md](docs/statistics.md) | Statistics | Metrics, methods, and the engine's output contract |
| [docs/agents.md](docs/agents.md) | AI agents | Desks, schedules, prompts, guardrails, usage budget |
| [docs/design.md](docs/design.md) | Dashboards and design | Look, navigation, pages, dashboards; mockups in `mockups/` |

Docs land through their own pull requests; a link above may 404 until its PR merges.

## Ground rules

- Advisory only. Nothing in this repo or on the box holds broker credentials or can place a trade.
- One-way data. The desk reads Escape Vektor's Firestore with a read-only account and never writes back.
- No personal figures, account numbers or statements in the repo. Real data lives on the TrueNAS box only.
- Free services only beyond what is already paid for.

Background and the hosting decision: [Escape Vektor docs/invest-desk.md](https://github.com/inzodious/fin-dashboard/blob/main/docs/invest-desk.md).

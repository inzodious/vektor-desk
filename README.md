# Vektor Desk

A private investing desk for one person, self-hosted on TrueNAS at `desk.escape-vektor.com` and reachable only over Tailscale. It checks every investing decision against the plan before it happens, records why, and scores it afterwards against simply following the plan. Statistics, live tracking, research and Claude Code agents feed that loop. It never places trades.

Escape Vektor is the everyday money app. Vektor Desk is the investing cockpit: one focus, more depth.

## Areas

| Area | Question it answers |
|---|---|
| **Bridge** | What changed, and does anything need me? KPIs, daily brief, decision queue, live holdings |
| **Research** | What do I know about this? Dossiers, watchlist, source library |
| **Decisions** | What am I doing and why? Preflight, order tickets, decision journal, Flight record |
| **Plan** | What is the rulebook? Target mix, deposits, rules, tax calendar, FI path |
| **Lab** | What does the evidence say? Compare, patterns, risk and statistics, saved boards |
| **Settings** | How is the desk configured? Desk profile, agents, data freshness |

Live tracking is one click from anywhere: every symbol opens the Symbol sheet with its live price, position, lots, plan target and open decisions. The full picture is in [docs/concept.md](docs/concept.md).

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

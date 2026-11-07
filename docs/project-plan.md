# Project plan

## Goal

A decision instrument for one investor: every buy, sell, rebalance or deliberate pass is checked against the plan before it happens, recorded with its reasoning, and scored afterwards against simply following the plan. Statistics, live tracking, research and agents feed that loop.

## What 1.0 means

The concept's success measures are the bar:

1. Every trade at Fidelity matches a decision record (at least 95 percent after three months).
2. No rule break goes through without a logged override.
3. The daily check takes under three minutes on a phone.
4. December's loss-sale plan comes from the desk (Tier 1 by December 6; see `ROADMAP.md`).
5. After six months the Flight record says which desks beat following the plan, and the rest are switched off.

Plus the usual bar: numbers match the brokerage on a spot check, and every page works at 1920, 1440 and 390 wide in light and dark.

## Workstreams

Each workstream is its own project thread and owns its files. Nobody edits another workstream's files; changes go to the owner by message.

| Workstream | Owns | Delivers first |
|---|---|---|
| Lead (roadmap and plan) | `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `CLAUDE.md`, `.github/`, `docs/project-plan.md` | This plan and the roadmap |
| Concept | `docs/concept.md` | Purpose, areas, loops, tiers (PR #1) |
| Infrastructure | `docs/architecture.md`, `deploy/`, the mirror, scheduler, backup and status code in `desk/`, and the shared Python scaffold (`pyproject.toml`, `desk/config.py`, `desk/db.py`, `tests/conftest.py`) | Stack, network, mirror, secrets (PR #5) |
| Statistics | `docs/statistics.md`, later the engine (Python) and Preflight | Metric catalogue and the engine's output contract (PR #4) |
| AI agents | `docs/agents.md`, later the agent runner and prompts | Desks, schedules, guardrails, usage budget, proposal contract (PR #2) |
| Dashboards and design | `docs/design.md`, `mockups/`, later the web app's look | Look, navigation, 12 clickable mockups (PR #6) |

## How the workstreams fit together

```
Concept ──► every other doc (what we are building and why)
Infrastructure ──► mirror tables ──► Statistics engine ──► output contract
                                                         ├──► AI agents read it, write proposals
                                                         └──► Dashboards render it
```

- **The output contract is the seam.** Statistics publishes metric ids, SQLite tables and the JSON shape. Agents and Dashboards build against it, not against each other's internals. Changes to it go through the Statistics thread.
- **The mirror schema is the second seam.** Infrastructure publishes the mirrored table names and columns; Statistics builds on them.
- **The decision record is the third.** Concept defines its fields; AI agents write proposals into it; Statistics scores it; Dashboards design Decisions and Bridge around it.
- **Phase and dependency notes go to Lead**, who folds them into `ROADMAP.md`.

## Working rules

- One phase is one pull request into `main`. Planning docs are one PR per workstream.
- Branch from the latest `main`; re-merge `main` before asking for review. A thread pushes only its own branch.
- No CI minutes: every PR is validated locally (lint, tests, build, and Playwright screenshots at 1920, 1440 and 390 in light and dark for anything visual), and the PR says what ran.
- Joshua merges. When several PRs are ready, Lead posts one merge order.
- Docs are short, plain and scannable: tables over paragraphs, no walls of text.
- Synthetic fixtures only. Real data never leaves the TrueNAS box.

## Decisions so far

| Date | Decision |
|---|---|
| 2026-11-07 | Self-host on TrueNAS as a Docker Compose app; Escape Vektor stays on Netlify and DNS stays at Porkbun |
| 2026-11-07 | Private: Tailscale only, `desk.escape-vektor.com` points at the Tailscale sidecar's address; certificate through Porkbun's DNS API |
| 2026-11-07 | Read-only Firestore mirror into SQLite; the desk never writes to Escape Vektor |
| 2026-11-07 | Agents run the Claude Code CLI (`claude -p`) on a `claude setup-token` token; no paid API, no Agent SDK with subscription login |
| 2026-11-07 | Advisory only: no broker credentials, no trade execution |
| 2026-11-07 | Free services only beyond what is already paid for |
| 2026-11-07 | Design borrows Escape Vektor's look with a single investing focus |
| 2026-11-07 | Engine is Python; Preflight is engine code that agents call and Design renders |
| 2026-11-07 | The Claude CLI runs in the cron service (Hemline's pattern); desks get no file, shell or MCP tools |
| 2026-11-07 | Web app is Vite and React with Escape Vektor's tokens; charts are hand-rolled SVG, no chart library |
| 2026-11-07 | Four services: Tailscale sidecar, Caddy, api (serves the built UI), cron; phone alerts through self-hosted ntfy |

## Risks

| Risk | Mitigation |
|---|---|
| Agent runs eat the subscription limits shared with development (every desk runs on Opus) | Frequency is the lever: overnight schedules, `--max-turns` caps, a usage budget per desk in `docs/agents.md` |
| Subscription terms for scripted use change | All model calls go through one runner, so switching to the API or a local model is a one-file change |
| Agents sound confident and are wrong | Engine computes every number; proposals cite sources; the scorecard decides which desks stay on |
| Prompt injection from web pages during research | Tight tool allow-lists, no shell, proposals checked by a second run that sees only the numbers |
| Brokerage feed gives positions without tax lots | Lot export import in Track; tax desk refuses to pick lots without it |
| Scope: five areas plus agents is a lot | Tier 1 ships first and is useful alone; Tiers 2 and 3 follow |
| Tier 1 misses December 6 | Year-end tax moves do not wait on the desk; whatever has landed (lot import, wash-sale check) is used as a cross-check |

## Open questions

None open. New questions go to the owning workstream; Lead records the answer here.

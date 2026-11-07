# Project plan

## Goal

A private investing cockpit that tells one investor, every day, whether the plan is on track and what the next sensible move is, backed by real statistics and sourced research, and honest about when doing nothing is the best move.

## What 1.0 means

1.0 is done when the desk runs for a full month without hand-holding:

1. The mirror and live prices stay current without manual fixes.
2. Track, Stats, KPIs, Compare and Plan show numbers that match the brokerage on a spot check.
3. The plan keeper and tax desk post proposals on schedule, each with sources, the rule it serves and an order ticket.
4. Every proposal is scored, and the scorecard shows whether each desk beats following the plan.
5. Every page works at 1920, 1440 and 390 wide, in light and dark.

## Workstreams

Each workstream is its own project thread and owns its files. Nobody edits another workstream's files; changes go to the owner by message.

| Workstream | Owns | Delivers first |
|---|---|---|
| Lead (roadmap and plan) | `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `CLAUDE.md`, `.github/`, `docs/project-plan.md` | This plan and the roadmap |
| Concept | `docs/concept.md` | Purpose, core loops, non-goals |
| Infrastructure | `docs/architecture.md`, deploy files (`compose.yaml`, `Caddyfile`, Dockerfiles, `.env.example`) | Stack, network, mirror, secrets |
| Statistics | `docs/statistics.md`, later the engine | Metric catalogue and the engine's output contract |
| AI agents | `docs/agents.md`, later the agent runner and prompts | Desks, schedules, guardrails, usage budget |
| Dashboards and design | `docs/design.md`, `mockups/`, later the web app's look | Look, navigation, page and board mockups |

## How the workstreams fit together

```
Concept ──► every other doc (what we are building and why)
Infrastructure ──► mirror tables ──► Statistics engine ──► output contract
                                                         ├──► AI agents read it, write proposals
                                                         └──► Dashboards render it
```

- **The output contract is the seam.** Statistics publishes metric ids, SQLite tables and the JSON shape. Agents and Dashboards build against it, not against each other's internals. Changes to it go through the Statistics thread.
- **The mirror schema is the second seam.** Infrastructure publishes the mirrored table names and columns; Statistics builds on them.
- **Proposals are the third.** AI agents define the proposal record (what, why, sources, confidence, rule, order ticket, settings snapshot); Dashboards design the Decide page around it.
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

## Risks

| Risk | Mitigation |
|---|---|
| Agent runs eat the subscription limits shared with development | Overnight schedules, `--max-turns` caps, a usage budget per desk in `docs/agents.md` |
| Subscription terms for scripted use change | All model calls go through one runner, so switching to the API or a local model is a one-file change |
| Agents sound confident and are wrong | Engine computes every number; proposals cite sources; the scorecard decides which desks stay on |
| Prompt injection from web pages during research | Tight tool allow-lists, no shell, proposals checked by a second run that sees only the numbers |
| Brokerage feed gives positions without tax lots | Lot export import in Track; tax desk refuses to pick lots without it |
| Scope: eight modules is a lot | Phases ship usable slices; Track, Stats and Plan come before agents |
| Year-end tax moves arrive before the desk is ready | Do not let the desk gate December decisions; the tax calendar is a phase 5 item |

## Open questions

- TrueNAS Scale version and spare capacity on the box (Infrastructure)
- Web app stack: confirm Vite and React to reuse Escape Vektor's components, or something else (Dashboards and design, Infrastructure)
- Engine language: Python for the statistics, or JavaScript to share code with Escape Vektor (Statistics)

# Agents

How Vektor Desk uses Claude: which agents ("desks") exist, how they run on the Claude subscription, what they may touch, how their advice is checked, and how they earn the right to stay switched on.

Status: plan, November 7, 2026. Nothing built. Base decisions are in fin-dashboard `docs/invest-desk.md`; this page supersedes its agent section.

## Principles

1. **Advisory only.** Agents write proposals. Joshua approves, dismisses or snoozes, then places any trade at the broker himself. Nothing in the stack holds broker credentials or can place an order.
2. **The engine computes, agents reason.** Every number an agent uses comes from the Python engine (see `docs/statistics.md`). An agent that cites a number the engine did not produce gets its proposal rejected.
3. **Rules live in code, not prompts.** Margin, concentration and wash-sale limits are checked by Preflight, deterministic engine code (owned by `docs/statistics.md`) that runs on every proposal after the agent answers. A prompt can be talked out of a rule; a function cannot.
4. **"Follow the plan" is the opponent.** Every proposal is scored against putting the same dollars into the plan mix on the same day. A desk that cannot beat that gets turned off.
5. **The most valuable agent is the one that says no.** Most good advice on this account is "don't", with the cost in dollars.

## How a run works

```
scheduler ─▶ brief builder ─▶ claude -p (one desk) ─▶ Preflight ──────▶ decision records ─▶ decision queue (UI)
              (engine, SQLite)   structured JSON out    numbers, rules,      │
                                                        sources, expiry      └─▶ scorecard at 30, 90, 365 days
```

1. The scheduler picks a desk whose time or trigger has come and checks the usage budget.
2. The brief builder assembles one prompt: `brief` (this desk's slice of engine metrics, each `{metric_id, scope_id, window, value, unit, as_of, quality}`, per `docs/statistics.md`), `profile` (the active dials and their version), and `history` (the desk's last 20 proposals with Joshua's decisions and reasons).
3. The adapter pipes that prompt to `claude -p` on stdin and asks for output that matches `desk/agents/schemas/proposal.json`.
4. The runner validates the JSON, re-checks every cited number against the brief, and calls Preflight (`preflight(holdings, trade) -> lights`, written to the preflight table), which applies the hard rules and adds the tax impact. The runner then stores the result as a decision record (`docs/concept.md`). Nothing the agent says reaches the UI without passing through this step.

### The adapter

All model calls go through one function, so a later move to the API or a local model (Ollama already runs on the box) is a one-file change:

```python
run_agent(desk: str, prompt: str) -> AgentResult
```

The Claude Code CLI implementation follows the pattern Joshua's Hemline app already runs on the same TrueNAS box, so there is one proven way to call Claude there:

```bash
cd "$(mktemp -d)"
desk_prompt | claude -p \
  --system-prompt-file /app/desk/agents/prompts/plan-keeper.md \
  --model sonnet --effort medium \
  --tools "" \
  --setting-sources "" --strict-mcp-config \
  --permission-mode dontAsk --permission-prompts none \
  --max-turns 12 \
  --no-session-persistence \
  --output-format json --json-schema "$(cat /app/desk/agents/schemas/proposal.json)"
```

Research and Scout swap `--tools ""` for `--tools "WebSearch,WebFetch"` and add `--allowedTools "WebSearch,WebFetch"`.

Notes, checked against the Claude Code docs on November 7, 2026:

- **Auth.** `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, only in the cron service's environment (root-only env file), with `HOME=/data/home`. CLI pinned (2.1.308 at time of writing) with `DISABLE_AUTOUPDATER=1`, so a CLI update never changes behaviour overnight.
- **No `--bare`.** It is the docs' recommendation for scripts, but bare mode does not read `CLAUDE_CODE_OAUTH_TOKEN`. Isolation instead comes from an empty temp directory, `--setting-sources ""` and `--strict-mcp-config`, so no CLAUDE.md, memory, hooks or MCP servers load.
- **No file tools at all.** The brief arrives on stdin, so four desks run with `--tools ""` and the two web desks get web tools only. No desk can read the disk, run a shell or write a file; work comes back as `structured_output`.
- **Replace, don't append, the system prompt.** `--system-prompt-file` drops Claude Code's coding-assistant prompt, which these desks don't need, and keeps every run's instructions in one versioned file.
- **`dontAsk` plus `--permission-prompts none`** denies anything outside the allow-list and carries on, rather than hanging on a prompt nobody will answer.
- **Caps.** `--max-turns` per desk, and a 20-minute wall clock. A stuck run gets SIGINT first (SIGTERM drops the turn).
- **`--model` takes aliases** (`sonnet`, `opus`), so model upgrades need no code change.
- **Reading the result.** Parse stdout as JSON; the answer is `structured_output`, and its absence is a failed run. Usage is logged from input, cache and output token counts. `is_error`, or a result matching usage limit, rate limit, 429 or overloaded, raises `UsageLimitError` and defers the run (see [Usage budget](#usage-budget)). Only dropped connections retry, at 5, 15, 30 and 60 seconds.
- **One desk at a time.** A single lock serialises desk runs, so a busy night never fans out into parallel usage.

## Desks

Joshua's parameters (risk level, industry focus, general opportunity, tax opportunities, growth) are **dials**, not separate agents. More agents means more usage and more overlapping noise; five desks reading shared dials covers every parameter.

| Desk | Runs (ET) | Reads | Writes | Model, effort, tools |
|---|---|---|---|---|
| **Plan keeper** | Daily 17:30, after the 17:00 mirror | Drift vs plan mix, cash, pending deposits, margin debit, rule status | Where the next deposit goes; rule-breach alerts; the 3 to 5 line daily Brief on Bridge | sonnet, medium; read tools |
| **Tax desk** | Sunday 02:00; daily 02:00 in December; when a new lot export lands | Lots, unrealized gains and losses, wash-sale windows across all accounts, marginal rate from Escape Vektor's tax estimate | Harvest candidates, lot picks for Specific Shares, year-end deadline list | sonnet, high; read tools |
| **Risk desk** | Saturday 02:00; also when the engine flags a trigger (below) | Concentration, correlation, drawdown scenarios, margin debit and interest cost | Weekly risk report; trim or "hold off" proposals | sonnet, high; read tools |
| **Research desk** | Wednesday 01:00 (one holding a week, in rotation); on request; day after a holding reports earnings | Holding fundamentals from the brief, plus the web and SEC EDGAR | Dossier per holding, written and refreshed: thesis, bear case, valuation range, what would change the call, dated sources | opus, high; read tools, WebSearch, WebFetch |
| **Scout** | First Sunday of the month, 03:00 | Industry focus, growth tilt, satellite room left | Up to N ideas inside the satellite cap, each with its bear case | opus, high; read tools, WebSearch, WebFetch |
| **Skeptic** | Right after any buy or sell proposal from Research or Scout | The proposal and the engine numbers only, no web | A counter-case and a pass/flag verdict, shown beside the proposal | sonnet, high; read tools |

**Engine triggers** come from the engine's triggers table and fire a desk at most once a day: a margin debit appears; a position moves more than the risk dial's daily threshold; a single holding passes its concentration band; a holding reports earnings; a new lot export arrives. Live tracking itself is engine work and needs no agent.

**Console.** The Console (Escape Vektor's Ask terminal look) is where Joshua talks to the desks. A question or research request is queued to the right desk and runs in the next overnight window unless he presses "Run now". It answers with a memo or dossier update plus any proposals. Settings shows each desk's last and next run, turns used, and an on/off toggle.

### Dials

Real settings live in `desk.yaml` on the TrueNAS box, outside the repo. The repo carries `desk.example.yaml` with made-up values. Every change is stored as a new profile version in SQLite, and every proposal records the version it was made under.

| Dial | Example settings | Read by |
|---|---|---|
| `risk_level` (1 to 5) | Max single-holding %, daily move trigger, drawdown tolerance; margin is always "never" for buys | Plan keeper, Risk, Scout, Skeptic |
| `industry_focus` | Sectors or themes with weights, plus exclusions | Research, Scout |
| `opportunity` | Satellite cap %, ideas per month, minimum confidence to show | Scout, Skeptic |
| `tax` | Harvest threshold in dollars, default lot method, year-end window, accounts that share wash-sale rules | Tax desk |
| `growth` | Horizon in years, growth vs dividend tilt, link to the plan's FI target | Plan keeper, Research, Scout |
| `usage` | Weekly run budget, overnight window, per-desk caps | Scheduler |

## Proposal contract

Every desk returns the same shape (`agents/schemas/proposal.json`). The UI and the scorecard depend on it; the statistics and design threads build against it.

| Field | Meaning |
|---|---|
| `kind` | `buy`, `sell`, `trim`, `rebalance`, `harvest`, `deposit_route`, `hold_off`, `alert`, `memo` |
| `symbol`, `account`, `amount_usd` or `shares` | What and where |
| `funding` | `cash`, `deposit`, `sale_proceeds` or `margin` |
| `thesis` | Two or three sentences, plain language |
| `bear_case` | The best argument against, required for buy and sell |
| `rule_served` | Which plan rule or dial this advances |
| `invalidation` | What would prove it wrong, checked by the engine where it can be (a price, a date, a reported number) |
| `horizon` | When to judge it: 30 days, 90 days, or a date |
| `numbers_used` | List of `{field, value}`, where `field` is the brief key `metric_id:scope_id:window` (for example `plan.drift:FXAIX:now`) and `value` must match the brief |
| `sources` | URLs with titles; buy and sell need at least two, one primary (filing, company release, FRED) |
| `confidence` | Probability from 0 to 1 that it beats the plan baseline at 90 days |
| `expires` | Default five trading days; an expired ticket cannot be approved |
| `order_ticket` | Action, symbol, quantity, order type, limit, account, lot method, ready to copy into the broker |

Decisions Joshua makes are stored against the proposal: `approved`, `dismissed`, `snoozed`, or `override` (he traded against a block), each with an optional one-line reason.

## Guardrails

**Preflight checks the agents rely on.** Preflight is engine code owned by `docs/statistics.md` and rendered by `docs/design.md`; the runner calls it and never re-implements it. Desk-written fields are above; Preflight adds the result, tax impact, profile version and status. The agents side needs at least these checks:

| Check | Effect |
|---|---|
| Margin-funded buy | Status `blocked`, with the monthly interest in dollars at the current margin rate. Never shown as a recommendation |
| New single stock outside the satellite cap | `blocked` |
| Holding would pass its concentration band | `blocked` for buys, flagged for anything else |
| Wash-sale window open on that symbol in any account | `blocked` for harvests and buys that would trigger it, with the date it clears |
| A cited number does not match the brief (runner check, before Preflight) | Proposal rejected and logged against the desk |
| Missing sources or bear case on a buy or sell | Proposal rejected |

A blocked proposal still appears, labelled with its cost, because the decision is Joshua's. If he trades anyway it is logged as an `override` and scored like any other proposal. The tone stays friendly; a block reads "this costs about $X a month in interest", not a red warning wall.

**Containment:**

- Desks have no file, shell or MCP tools, so they cannot reach the Firestore service-account key, `mirror.db`, `desk.db`, market-data keys or Porkbun keys even though the cron service can. Only the runner, which is plain Python, reads data and writes decision records.
- No MCP servers before Phase 10. A read-only `desk-data` MCP server (SELECT on whitelisted views) is optional there.
- Web pages are untrusted data. An injected instruction can at worst bias a memo's text, because the agent has nothing to act with. The Skeptic never sees web text, the runner drops any URL not listed in `sources`, and the UI renders agent text as plain text.
- Agents never edit their own prompts, dials or history. Prompt changes are pull requests in this repo.
- Kill switch: `agents.enabled: false` in `desk.yaml`, or the per-desk toggle in the UI, stops all scheduling at once.

## Usage budget

Agent runs share the subscription's 5-hour and weekly limits with Joshua's interactive Claude Code and the cloud threads that build both apps.

- **Overnight by default.** Scheduled runs sit between 01:00 and 06:00 ET, except the plan keeper's short daily run.
- **Priority when the budget is tight:** plan keeper, then tax desk (first in December), risk desk, research desk, scout. The scheduler skips lower-priority runs rather than squeezing them in.
- **Metered.** Each run logs turns, tokens and wall time. The status page shows usage per desk per week. Start with a small weekly budget and set the real one after two weeks of logs.
- **Rate limits.** If a run fails on a usage or rate limit, it is marked `deferred` and retried once in the next window. No retry loops.
- **Token health.** The `setup-token` token lasts a year. The status page shows the date it was created and warns 30 days before it expires. An authentication failure pauses every desk and shows a banner instead of failing silently each night.

## Scorecard

Logged from the first proposal in Phase 5, reported from Phase 10. The method (returns, significance, calibration) is owned by `docs/statistics.md`; this section defines what the agents side must record.

- **Baseline:** the same dollars into the plan mix, priced at the next trading day's close for both sides (method in `docs/statistics.md`).
- **Scored at 30, 90 and 365 days:** every proposal, whether approved or not, so a dismissed idea that would have worked still counts.
- **Per desk:** excess dollars vs baseline, hit rate, calibration of `confidence` (Brier score), approval rate, usage per proposal.
- **Saves:** blocks and `hold_off` proposals are scored by what they avoided, such as margin interest not paid or a wash sale not triggered. Harvests are scored as realized loss times the marginal rate from Escape Vektor's tax estimate.
- **Overrides** are scored the same way, so the scorecard also shows how Joshua's own calls do against the plan.
- **Keep or switch off:** after six months, a desk that has not beaten the baseline (or, for the plan keeper and tax desk, saved more than it cost in attention) is turned off. With a few dozen proposals the numbers are a sanity check, not proof; the decision is Joshua's.

## Learning loop

Agents do not have memory of their own. Each run's `history.json` carries the desk's last 20 proposals, what Joshua decided, his reasons, and the latest scorecard line for that desk. If he keeps dismissing a kind of idea, the next run sees that. Anything more lasting goes into the desk's prompt by pull request.

## Testing

- **Fake adapter** that returns canned JSON, so the runner, Preflight and UI can be built and tested without using the subscription.
- **Unit tests** for the adapter, brief builder and scheduler, on synthetic briefs only. Preflight's own tests live with the engine.
- **Scenario set:** about ten synthetic briefs that each tempt a desk to fail, for example a margin-funded buy, a harvest inside a wash-sale window, an over-concentrated add, and a web page with an injected instruction. Run by hand after any prompt change, because each run costs usage.

## Repo layout

```
desk/agents/
  prompts/        one system prompt per desk
  schemas/        proposal.json, brief.json
  desks.yaml      triggers, model, effort, tools, turn caps, priority
  adapter.py      run_agent(), Claude Code CLI implementation and the fake
  briefs.py       builds each desk's prompt from engine output
  scheduler.py    windows, priority, budget, deferrals, the run lock
  score.py        calls the engine's scoring for each decision record
deploy/crontab    one line per scheduled desk (infra's cron service, America/New_York)
desk.example.yaml
```

## Phases

Numbering follows `ROADMAP.md`.

| Phase | Agent work | Needs first |
|---|---|---|
| **1. Foundation** | One `claude -p` smoke test from the cron service | Image with the pinned CLI, cron service, token env file (infra, `docs/architecture.md`) |
| **3. Engine core and Plan** | Fake adapter and brief builder against synthetic engine output, so agent work can start alongside the engine | Engine outputs for drift, cash and pending deposits, margin debit and rate, tax lots, wash-sale windows, marginal rate (statistics) |
| **4. Decisions and Preflight** | Proposal schema agreed with the decision records table | Decision records, queue, overrides, tickets, Preflight (statistics and design) |
| **5. Plan keeper and tax desk** | Adapter, prompts, scheduler and run lock, crontab lines, plan keeper, tax desk, scorecard logging from the first proposal | Phase 4; the lot import |
| **6. Research** | Research desk, Skeptic, Console requests, engine triggers, dossiers | Market-data and EDGAR fetchers; dossier and source views (design) |
| **7. Lab risk** | Risk desk | Correlation and drawdown scenarios (statistics) |
| **10. Scout** | Scout; keep-or-switch-off review once six months of scores exist; optional read-only MCP server | Scorecard method and reports (statistics) |

## Before you start

- [ ] Run `claude setup-token` on your PC and keep the token for the TrueNAS secret, never in the repo or chat.
- [ ] Note the date you created it, for the status page.
- [ ] Pick the first weekly usage budget once two weeks of runs are logged.

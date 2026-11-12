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
2. The brief builder assembles one prompt: `brief` (this desk's slice of engine metrics, each `{metric_id, scope, scope_id, window, value, unit, as_of, quality}`, per `docs/statistics.md`; portfolio-level `scope_id` is `all`), `profile` (the active dials and their version), and `history` (the desk's last 20 proposals with Joshua's decisions and reasons).
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
  --model opus --effort high \
  --tools "" \
  --setting-sources "" --strict-mcp-config \
  --permission-mode dontAsk --permission-prompts none \
  --max-turns 12 \
  --no-session-persistence \
  --output-format json --json-schema "$(cat /app/desk/agents/schemas/proposal.json)"
```

Research, Scout and Strategy swap `--tools ""` for `--tools "WebSearch,WebFetch"` and add `--allowedTools "WebSearch,WebFetch"`.

Notes, checked against the Claude Code docs on November 7, 2026:

- **Auth.** `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, only in the cron service's environment (root-only env file), with `HOME=/data/home`. CLI pinned (2.1.308 at time of writing) with `DISABLE_AUTOUPDATER=1`, so a CLI update never changes behaviour overnight.
- **No `--bare`.** It is the docs' recommendation for scripts, but bare mode does not read `CLAUDE_CODE_OAUTH_TOKEN`. Isolation instead comes from an empty temp directory, `--setting-sources ""` and `--strict-mcp-config`, so no CLAUDE.md, memory, hooks or MCP servers load.
- **No file tools at all.** The brief arrives on stdin, so four desks run with `--tools ""` and the three web desks get web tools only. No desk can read the disk, run a shell or write a file; work comes back as `structured_output`.
- **Replace, don't append, the system prompt.** `--system-prompt-file` drops Claude Code's coding-assistant prompt, which these desks don't need, and keeps every run's instructions in one versioned file.
- **`dontAsk` plus `--permission-prompts none`** denies anything outside the allow-list and carries on, rather than hanging on a prompt nobody will answer.
- **Caps.** `--max-turns` per desk, and a 20-minute wall clock. A stuck run gets SIGINT first (SIGTERM drops the turn).
- **`--model opus`** is an alias, so it follows the current Opus (Opus 5.5 today) and model upgrades need no code change.
- **Reading the result.** Parse stdout as JSON; the answer is `structured_output`, and its absence is a failed run. Usage is logged from input, cache and output token counts. `is_error`, or a result matching usage limit, rate limit, 429 or overloaded, raises `UsageLimitError` and defers the run (see [Usage budget](#usage-budget)). Only dropped connections retry, at 5, 15, 30 and 60 seconds.
- **One desk at a time.** A single lock serialises desk runs, so a busy night never fans out into parallel usage.

## Desks

Joshua's parameters (risk level, industry focus, general opportunity, tax opportunities, growth) are **dials**, not separate agents. More agents means more usage and more overlapping noise; six standing desks reading shared dials cover every parameter, plus a Strategy desk that feeds the lab.

| Desk | Runs (ET) | Reads | Writes | Effort, tools |
|---|---|---|---|---|
| **Plan keeper** | Daily 17:30, after the 17:00 mirror | Drift vs plan mix, cash, pending deposits, margin debit, rule status | Where the next deposit goes; rule-breach alerts; the 3 to 5 line daily Brief on Bridge | high; no tools |
| **Tax desk** | Sunday 02:00; daily 02:00 in December; when a new lot export lands | Lots, unrealized gains and losses, wash-sale windows across all accounts, marginal rate from Escape Vektor's tax estimate | Harvest candidates, lot picks for Specific Shares, year-end deadline list | high; no tools |
| **Risk desk** | Saturday 02:00; also when the engine flags a trigger (below) | Concentration, correlation, drawdown scenarios, margin debit and interest cost | Weekly risk report; trim or "hold off" proposals | high; no tools |
| **Research desk** | Nightly portfolio pass at 00:05 (every holding the first night, then each holding weekly or when it has a reason; see [Portfolio pass](#portfolio-pass)); on request; day after a holding reports earnings | One holding's plan facts, his plan for it, the last analysis and his risk band, plus the web and SEC EDGAR | One analysis per holding (or any symbol asked for in the Console): what it is, thesis, what changed, valuation range and note, risks, bear case, fit with his plan and risk, a verdict (add, hold, trim, watch), what would change it, dated sources | high for the pass, xhigh on request; WebSearch, WebFetch |
| **Scout** | First Sunday of the month, 03:00 | Industry focus, growth tilt, satellite room left | Up to N ideas inside the satellite cap, each with its bear case | xhigh; WebSearch, WebFetch |
| **Skeptic** | Right after any buy or sell proposal from Research or Scout | The proposal and the engine numbers only, no web | A counter-case and a pass/flag verdict, shown beside the proposal | high; no tools |
| **Strategy desk** | Nightly 05:45, one variant in a rotating family (below); on request from the Console; when a lab result lands; 12 runs a week | Research dossiers, the lab's feature list, past lab results | Strategy specs for the lab, then a memo on each result (see [Strategy lab](#strategy-lab)) | xhigh; WebSearch, WebFetch |
| **Filings desk** | Daily 04:15, one call per new filing, up to 40 a night | One small-cap SEC filing from the statistics queue: form, 8-K items, excerpt (first 12,000 characters) | A score per filing in the signal table (see [Filings desk](#filings-desk)); never a proposal or a trade | high; no tools |
| **Discount cases** | Weekdays 18:15, after the close, up to 3 a day | One discount-day scanner hit (held, watchlist or quality list), his risk band, conviction bands and planned actions, plus the web | A buy / wait / avoid case per hit, through `desk.engine.discounts.record`; never a proposal or a trade | xhigh; WebSearch, WebFetch |
| **Debrief desk** | Weekdays 17:50 (day; week, month and year when they close); Friday 18:30 catches up anything missed; hourly 01:40 to 06:40 Tuesday to Saturday, a model call only when the day was restated after its debrief | One period pack from the 17:35 review job, his risk band, conviction bands and stock plans | What happened, why, what worked against past decisions, what to watch, up to 3 next steps, through `desk.engine.review.record` (see [Debrief desk](#debrief-desk)); never a proposal or a trade | high; no tools |
| **Plan desk** | Weekdays 18:40 (holdings with a reason: no plan yet, a discount day, a band crossing, earnings, a review date); Saturday 03:00 (every holding); from the Console | One holding's plan facts, its current plan, the research dossier, his risk band and conviction bands | A draft stock plan through `desk.decisions.plans.save_draft`, or nothing when the current plan still fits (see [Plan desk](#plan-desk)); never approves, never a trade | high; no tools |

**Model.** Every desk runs `opus` (Opus 5.5 today), at `high` effort for routine desks and `xhigh` for Research, Scout and Strategy, per Joshua on November 7, 2026. Effort per desk is set in `desk/agents/desks.py`.

**Usage impact.** Opus at high and extra-high effort draws down the 5-hour and weekly limits much faster than a smaller model would, and these runs share those limits with his interactive Claude Code and the cloud build threads. The plan keeps the model and controls frequency instead:

- The plan keeper skips its daily run when nothing in its brief changed since the last one (no drift change past a threshold, no new cash, no trigger).
- One desk at a time behind the run lock; overnight window; per-desk turn caps.
- Strategy runs are capped per week, and each lab result costs one interpretation run, not a loop.
- When the weekly budget is spent, lower-priority desks wait for the next week rather than switching model. If limits bite in practice, the first lever is fewer research and strategy runs, then `high` instead of `xhigh`.

**Engine triggers** come from the engine's triggers table and fire a desk at most once a day: a margin debit appears; a position moves more than the risk dial's daily threshold; a single holding passes its concentration band; a holding reports earnings; a new lot export arrives; a plan rule stops holding; a scheduled deposit lands. Live tracking itself is engine work and needs no agent.

Trigger kinds and where they go: `margin_debit`, `daily_move` and `concentration` run the Risk desk right away; `lot_export` runs the Tax desk right away; `rule_breach` runs the Plan keeper right away; `deposit_landed` queues the Plan keeper tonight; `earnings` queues the Research desk for that symbol tonight. Stale quotes stay ops alerts only. `python -m desk.agents triggers` turns them into requests at 17:45, each once.

**Requests.** Console questions and triggers are rows in `agent_requests`. "Run now" rows are picked up within a minute (`queue --now-only`); the rest run in the overnight passes at 01:30 through 05:30, so one busy pass doesn't strand a night's queue. Each pass claims a request atomically, so two passes never run the same one. A request that finds another desk running goes back in line without losing its place. A request that hits the usage limit moves to tonight once, then fails rather than looping. A scheduled run waits up to 45 minutes for the run lock, then queues one retry; so does one that hits the usage limit.

**Console.** The Console (Escape Vektor's Ask terminal look) is where Joshua talks to the desks. A question or research request is queued to the right desk and runs in the next overnight window unless he presses "Run now". It answers with a memo or dossier update plus any proposals. Settings shows each desk's last and next run, turns used, and an on/off toggle.

**Phone alerts** (`desk/agents/alerts.py`, through `desk.notify.publish`; dollar amounts stripped, never blocks a run):

| Event | Topic | Priority | Opens | Repeats |
|---|---|---|---|---|
| Console or trigger request answered | research | default | `/research` (`/strategies` for the Strategy desk, `/portfolio/stocks?symbol=SYM` for the Plan desk) | once per request |
| Stock plan drafts saved | research | default | `/portfolio/stocks` | once per day |
| Period debrief written | research | low for a day, else default | `/results/<kind>?end=<end>` | once per period |
| Nightly portfolio pass | none of its own | | | its last line feeds the 06:45 morning alert |
| Desk run failed or timed out | ops | default | `/settings/crew` | once per desk, status and day |
| Request dropped after busy or usage limit twice | ops | default | `/settings/crew` | once per desk, status and day |

A first usage-limit hit stays quiet because it retries that night. A Console research run sends only the answer, not a second dossier alert.

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

## Strategy lab

The lab tests trading strategies over 3, 5 and 10 year windows as paper trading, without real money. The engine owns the simulation (`docs/statistics.md`, "Backtests and honest limits"); the Strategy desk writes the hypotheses and reads the results.

**The model cannot forget the future.** Opus was trained on market history up to its training cutoff. Asked to "pretend it's 2016 and ignore what came after", it still knows which companies won, and any strategy it designs will lean on that knowledge without meaning to. So:

1. **The agent never runs the simulation.** It writes a strategy as rules (a spec), and the engine replays them point-in-time on stored prices and filings, using only data published by each date. The model's hindsight can shape which rules it writes, but it cannot leak into the trades.
2. **The honest tests are the ones after the cutoff.** Every lab result reports the window after the model's training cutoff separately, and a strategy only counts as working if it holds there too.
3. **Forward paper trading is the final test.** A strategy that passes the lab runs as a paper portfolio on live data for at least six months before it can generate real proposals. That period is free of any hindsight, the model's or ours.
4. **Every variant counts.** Specs record their parent, so the lab knows how many versions of an idea were tried and can discount the winner for it.
5. **Criteria are set before the test.** The spec states what "works" means (excess return vs the plan mix, maximum drawdown, minimum trades, how many windows it must hold in). Criteria cannot change after a result.

**Stages:** `draft` → `lab` → `paper` (forward, six months minimum) → `eligible`. An eligible strategy can back Scout proposals inside the satellite cap, and they go through Preflight and the scorecard like any other proposal. A strategy that fails its paper period goes back to `draft` or is retired.

**Strategy spec.** The Strategy desk returns a `strategy` output (`desk/agents/schemas/strategy.json`) instead of a proposal. The canonical field list is in `docs/statistics.md`, "Strategy lab"; that doc wins where the two differ. Costs and tax rates are set by the lab.

| Field | Meaning |
|---|---|
| `id`, `version`, `parent_id` | Identity and lineage; every version is a new trial in the lab's ledger |
| `title`, `hypothesis` | Plain-language idea and why the market might be missing it |
| `predicted_effect` | What should happen and by how much, stated before any run |
| `universe` | A fund set (`sector_etfs`, `core_etfs`, `benchmarks`), a fixed fund list or a stock screen, per the lab grammar; never a pick of today's winners |
| `signals` | From the engine's feature library only, no free-form code |
| `entry`, `exit`, `sizing`, `rebalance` | Rules over those signals |
| `constraints` | Long only, no margin, maximum position %, maximum turnover |
| `benchmark`, `account` | Optional; default plan mix and the taxable account |
| `params` | Each tunable value with its allowed search range |
| `success_criteria`, `horizons` | Pre-registered bars; any of 3, 5, 10 years |
| `written_at`, `desk`, `model`, `effort` | Provenance |

**Nightly variants.** `python -m desk.agents run strategy` picks one family a night, rotating among those the lab can express today, and asks for one new idea in it. It skips with `not_ready` (no model call) when none can be expressed.

| Family | Lab needs | Universe | Benchmark |
|---|---|---|---|
| Insider buying clusters | `insider.` features (`insider.buyers`, `insider.buy_usd`) and the small-cap history loaded | `small_caps` | IWM |
| Post-earnings drift | `earnings.` features (`earnings.surprise`, `earnings.days_since`) and the small-cap history loaded | `small_caps` | IWM |
| Filings signal | a running lane in `lab.strategies`; the desk answers `action: "lane"` and the runner calls `desk.engine.lane.register_variant` (at most 12, forward paper only, no backtest) | lane | IWM |

The prompt carries the family's earlier specs (`lab.strategies`, ids start with the family key) and asks for a different hypothesis, not a parameter sweep. A nightly experiment gets at most 24 grid points and a trial budget of 24; a wider grid is not queued. Console requests keep the normal budget. `dry-run strategy --trigger schedule` shows tonight's prompt.

**The loop.** Desks have no file tools, so the Strategy desk returns an experiment in its structured output (spec, param grid inside `params`, date range, seed, trial budget, default 200 per spec, and optional analysis requests). The runner writes it to `/data/lab/queue/`, and `desk.lab` runs it with no network. The next Strategy run gets the results in its prompt as `lab_result`, and every run gets the lab's spec `grammar` so fewer specs bounce. A question about one of Joshua's own rules (rebalance band, deposit steering, harvest, margin) becomes a `rule` request instead of a spec, tested against the plan with deposits. `python -m desk.agents lab-reviews` queues one Strategy request per new lab result (experiment, finalize, rule or rejected). `model` in the queue file is the model the CLI actually served, so the lab can look up its training cutoff.

**No peeking.** The lab freezes and hashes each spec version on registration. While tuning, the desk sees only walk-forward fold summaries and the analyses it asked for, never simulated days mid-run. Holdout and post-cutoff results open only through one `finalize` request per spec version, and finalizing closes that version: any change after it is a new version, a new trial in the lab's ledger, and counted against the idea. A strategy that clears the backtest bars and six months of forward paper trading may then be cited only by Scout proposals inside the satellite cap, through Preflight.

The final tear sheet reports each horizon, the post-cutoff window, trials tried, caveats such as survivorship, and a verdict. The Strategy desk then writes a short memo on what the result does and does not show.

Expect most strategies to fail. That is the lab working: a cheap "no" in simulation beats an expensive one in the account.

## Measured against his risk band

There is no single target plan. Every proposal desk (Plan keeper, Tax, Risk, Research, Scout) gets an `advisor` block and the Discount cases desk gets the same:

| Piece | Source | In the prompt |
|---|---|---|
| Risk band | `desk.decisions.risk.current(cfg)` (Concept C1) | `advisor.risk_band`; numbers as brief keys `risk.<field>:all:now` (band, equity range, speculative max, single-stock max, worst-year loss) |
| Strategy catalog | `desk.engine.bands.catalog(cfg)` (Statistics S1, S2) | `advisor.catalog` (id, name, fit, proxy); numbers as `catalog.<field>:<id>:now` |
| Conviction holds | `desk.decisions.risk.convictions(cfg)` (C2) | `advisor.convictions` |
| Plan steps live today | `desk.decisions.plans.steps_today(cfg)` (Concept P1) | `advisor.planned_actions`, ready sentences. The Plan keeper names each in the daily Brief, and a change in them counts as a brief change |
| No-buy windows | `desk.decisions.plans.no_buy(cfg)` | `advisor.no_buy` by symbol. A buy or deposit route for a listed symbol is rejected before it reaches the queue, and the Plan desk writes no add step |

Each piece is optional: a missing one is listed in `advisor.missing` and the desk carries on. With no risk band yet, desks stay conservative and mention the questionnaire once. The v3 mix is one catalog entry, and v3 items he hasn't re-confirmed are suggestions only. A risk band change counts as a brief change, so the Plan keeper runs that day.

## Debrief desk

Writes the words on the Results page (`docs/statistics.md` owns the period packs). Advisory only.

| Piece | Detail |
|---|---|
| Queue | `desk.engine.review.pending(cfg)`: the latest pack per kind (day, week, month, year) whose digest differs from its last debrief; `NotReady` until the first review run |
| Which periods | Day every weekday. Week, month and year once the review job marks them closed. The day a week closes, the open month and year are rewritten "so far". The first ever run writes every open period "so far" |
| Write | `desk.engine.review.record(cfg, kind, end, result)`, one debrief per (kind, end), rewritten when the pack restates; a refused debrief is noted on the run |
| Debrief | `schemas/debrief.json`: `headline` ≤ 120, `what_happened` ≤ 700, `why` ≤ 700, `against_decisions` ≤ 500 (never empty; a stock sentence when there were no decisions), `watch` ≤ 4, `next_steps` ≤ 3 `{text, symbol}`, `numbers_cited` (keys of the pack's `numbers`; others dropped), plus `pack_digest`, `model`, `written_at`, `run_id` |
| No call | Pack missing, or digest unchanged since the last debrief: no model call and no run row |
| Alert | Phone alert on the research topic with the headline, opening that period on Results |
| Stops | Usage limit, run lock busy, weekly cap (16), or switch off |
| On switch | On by default behind `agents.enabled`; Settings → Crew turns it off. The first-run guard does not hold it, since it only writes text |

`python -m desk.agents run debrief [--kinds day,week,month,year] [--so-far]` writes now; `dry-run debrief` shows the first pack's prompt.

## Portfolio pass

One current analysis per holding, written overnight and shown in Research. It runs under the Research desk's name and switch, writes no proposals, and adds nothing to the queue.

| Point | Detail |
|---|---|
| Job | `agents-run-research` (`python -m desk.agents run research`, or `python -m desk.agents portfolio` by hand), `overnight: 200` in the night's order, fallback 00:05 with resume lines at 02:05 and 04:05 |
| Which holdings | Never analysed, then a new discount signal, a new filing signal, earnings today or tomorrow, then older than 7 days. Biggest weight first within each. An analysis under 18 hours old is skipped, so starting twice in a night is safe |
| One at a time | Each holding is one call behind the shared `agents` lock: Opus, `high`, web search, 30 turns. No new call starts between 06:00 and 08:00, so a slow night never runs into the morning jobs |
| Prompt | `holding` (plan facts without lots), `current_plan`, `previous_analysis`, `no_buy`, `advisor`, `risk_numbers`, `reasons` |
| Checks | Needs a verdict, the six text sections and one dated source, or it is refused. An `add` becomes `hold` when the holding is over its band or inside a no-buy window |
| Failures | A failed holding is tried once more that night, then left for the next. Three failures in a row or a usage limit stop the pass. Each try is kept in `agent_holding_tries`, and the page says why in plain words |
| Last line | `{"ready": "All 14 holdings analysed"}` or `{"skipped": "..."}` for the morning alert |
| App | `GET /api/agents/holdings`: counts, `fresh_at`, one `line`, and a row per holding with `status` (`today`, `older`, `running`, `waiting`, `failed`, `none`), `status_line`, `verdict`, `verdict_line`. One holding: `GET /api/agents/dossiers/{symbol}` |
| By hand | `python -m desk.agents portfolio --symbol SYM --trigger console`; `python -m desk.agents dry-run research --trigger schedule` prints the queue and the first prompt |

## Plan desk

Drafts and refreshes one stock plan per holding (`docs/concept.md` owns the plan record, `docs/statistics.md` the plan facts). He edits and approves; the desk only ever writes drafts.

| Piece | Detail |
|---|---|
| Reads | `desk.engine.planfacts.facts(cfg)` (one row per holding), `desk.decisions.plans.list_plans(cfg)`, the latest dossier, the advisor view, `desk.engine.triggers.today(cfg)` |
| Weekdays 18:40 | Only holdings with a reason: `new` (no plan or no thesis), `discount` (plan facts `discount.active`), `band` (plan facts `band` or the plan's `band_status` outside), `earnings` and `concentration` engine triggers, `review_due`. Each reason fires once |
| Saturday 03:00 | Every holding (`weekly`); `run plans --all` does the same any day |
| Answer | `schemas/plans.json`: `action` draft or keep, a one-line `summary`, `numbers_cited` (keys of the holding's `numbers`), and the `plan` on a draft. Keep writes nothing |
| Checks | Role and thesis required. Add and trim zone levels must match a number in the holding's `zones` or `numbers` within 0.5%, else they are nulled. `next_review` must be after today, else a week out. Add steps that mention margin are dropped. No add steps inside a no-buy window |
| Write | `save_draft(cfg, symbol, plan, run_id=, model=, summary=)`. A refused draft is noted on the run. His own unapproved draft is never touched, and no call is made for that holding |
| Pinned steps | A Console request to the Plan desk whose text is JSON `{"steps": [...]}` (the plan record's step fields) pins those steps to the symbol. They ride in every draft, even when the desk would keep the plan, until he drops the step from the plan or 60 days after its window |
| Console | Any other text sent to the Plan desk with a symbol is his note for that plan and runs the desk for that holding |
| Volume | `usage.plans_per_run` in `desk.yaml`, default 12, at most 30; the rest wait for the next run. Weekly cap is twice that plus 10 |
| Alert | One phone alert per run that saved drafts, opening Portfolio → Stock plans |
| Stops | Usage limit, run lock busy, weekly cap, switch off, or 2 failures in a row. A failed call keeps its reason for the next run |
| On switch | On by default behind `agents.enabled`; the first-run guard does not hold it |

`python -m desk.agents run plans [--symbol SYM] [--all] [--limit N]` writes now; `dry-run plans` lists the holdings it would write and shows the first prompt.

## Discount cases

| Piece | Detail |
|---|---|
| Queue | `desk.engine.discounts.pending(cfg, limit)`, biggest discount first; `[]` when no hits, `NotReady` until S4 ships |
| Write | `desk.engine.discounts.record(cfg, signal_id, case)`, first write wins; a refused case is noted on the run |
| Case | `schemas/discounts.json`: `verdict` buy / wait / avoid, `case` ≤ 400, `risks` ≤ 240, `confidence` 0..1, `horizon_days` 5..365, `numbers_cited` (keys of the hit's `numbers`; others dropped), plus `model`, `written_at`, `run_id` |
| Volume | `usage.discount_cases_per_day` in `desk.yaml`, default 3, at most 10; weekly cap is seven days' worth |
| Stops | Usage limit, run lock busy, weekly cap, switch off, or 2 failures in a row |
| On switch | Off unless switched on in Settings or `agents.desks.discounts: true`; the first-run guard holds it |

`python -m desk.agents run discounts [--limit N]` writes now; `dry-run discounts` shows the first hit's prompt.

## Filings desk

Scores new small-cap SEC filings for the lab's forward paper test (`docs/statistics.md` owns the queue, the signal table and the strategy). Advisory only: it writes a score, never a proposal, order or ticket.

| Piece | Detail |
|---|---|
| Queue | `desk.engine.filings.pending(cfg, limit)`, most material first; `[]` before the first fetch, `NotReady` until the table exists |
| Write | `desk.engine.filings.record(cfg, accession, result)`, first write wins; a refused score is noted on the run and the night goes on |
| Output | `schemas/filings.json`: `direction` −2..2, `confidence` 0..1, `event_type`, `horizon_days` 1..120, `rationale` ≤ 280, `numbers_cited` |
| Recorded with it | `model` (the id the CLI served), `scored_at` (UTC), `run_id` |
| Number check | Each `numbers_cited` entry must appear verbatim in the excerpt sent; the rest are dropped |
| Hindsight | The prompt forbids anything the model remembers about the company after the filing; scores are judged forward only |
| Model | Opus at high effort, one call per filing, up to 4 turns, no tools; never downgraded |
| Volume | `usage.filings_per_night` in `desk.yaml`, default 40, at most 200; weekly cap is seven nights' worth |
| Stops | Usage limit, run lock busy for 5 minutes, weekly cap, Settings switch, or 3 failures in a row; what's left waits for the next night |
| On switch | Off unless `agents.desks.filings: true`; the first-run guard also holds it |

Commands: `python -m desk.agents run filings [--limit N]` scores now; `python -m desk.agents dry-run filings --system --schema` shows the first filing's prompt without a call.

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
| `numbers_used` | List of `{field, value}`, where `field` is the brief key `metric_id:scope_id:window` (for example `plan.drift:FXAIX:now` or `cash.ready:all:now`) and `value` must match the brief |
| `sources` | URLs with titles; buy and sell need at least two, one primary (filing, company release, FRED) |
| `confidence` | Probability from 0 to 1 that it beats the plan baseline at 90 days |
| `expires` | Default five trading days; an expired ticket cannot be approved |
| `order_ticket` | Action, symbol, quantity, order type, limit, account, lot method, ready to copy into the broker |

Decisions Joshua makes are stored against the proposal: `approved`, `dismissed`, `snoozed`, or `override` (he traded against a block), each with an optional one-line reason.

## Wording and the queue

| Rule | Where |
|---|---|
| Prose is rounded before it is saved: percentages, points and ratios to one or two decimals, dollars over $1,000 to whole dollars. `numbers_used` and `numbers_cited` are never touched | `wording.tidy`, applied to proposal titles and text, the Brief summary, debrief text and plan summaries |
| One cash figure, no machinery talk ("the rule's own count reads 0", "no margin rate is set"), nothing raised twice | `prompts/common.md` Writing, `debrief.md`, `plans.md` |
| Every proposal a desk files carries `subject` and `as_of` | `wording.stamp`: `subject` is stable and has no numbers (`next-deposit`, `margin`, `buy:SYM`, `sell:SYM`, `rebalance:SYM`, `hold_off:SYM`, `rule:<slug>`); `as_of` is the engine day of the brief |
| What the record does with them | `desk.decisions` replaces an open proposal from the same desk on the same subject, expires stale ones, and logs `alert` and `memo` as notes instead of queue items (see `docs/concept.md`) |

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
- No MCP servers before Phase 11. A read-only `desk-data` MCP server (SELECT on whitelisted views) is optional there.
- Web pages are untrusted data. An injected instruction can at worst bias a memo's text, because the agent has nothing to act with. The Skeptic never sees web text, the runner drops any URL not listed in `sources`, and the UI renders agent text as plain text.
- Agents never edit their own prompts, dials or history. Prompt changes are pull requests in this repo.
- Kill switch: the all-desks switch in Settings (`PUT /api/agents/*/enabled {"enabled": false}`) stops every desk at once. `agents.enabled: false` in `desk.yaml` does the same while Settings has no switch of its own set.

## Usage budget

Agent runs share the subscription's 5-hour and weekly limits with Joshua's interactive Claude Code and the cloud threads that build both apps.

- **Overnight by default.** Scheduled runs sit between 01:00 and 06:00 ET, except the plan keeper's short daily run.
- **Priority when the budget is tight:** plan keeper, then tax desk (first in December), risk desk, research desk, scout, strategy desk, filings desk. The filings desk's volume is the main usage lever: lower `usage.filings_per_night` first. The scheduler skips lower-priority runs rather than squeezing them in.
- **Metered.** Each run logs turns, tokens and wall time. The status page shows usage per desk per week. Start with a small weekly budget and set the real one after two weeks of logs.
- **Weekly caps** count scheduled, trigger, retry and lab runs. Console questions are his own asks and bypass the cap; Skeptic runs ride on the run that asked for them.
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
  desks.py        model, effort, tools, turn and weekly caps, priority, schedules
  adapter.py      ClaudeCli (claude -p) and FakeAdapter behind one run() call
  runner.py       switches, weekly cap, the "agents" run lock, run log
  store.py        agent_runs and agent_settings in desk.db
  status.py       crew tiles: last and next run, weekly usage
  api.py          /api/agents/status, /api/agents/{desk}/enabled
  jobs.py         JOBS for the scheduler, one per live desk schedule
  schema.py       the package's tables
  filings.py      the filings desk's nightly loop: queue, score, number check, record
  discounts.py    discount cases after the close: queue, case, number check, record
  debrief.py      period debriefs after the review job: pack, debrief, number check, record
  plans.py        stock plan drafts: queue by reason, draft or keep, level check, pinned steps, save
  portfolio.py    nightly portfolio pass: one analysis per holding, tries, status for the app
  wording.py      rounds prose he reads; gives each proposal its subject and as-of day
  advisor.py      risk band, catalog, convictions and planned actions for every brief
  switches.py     Settings over desk.yaml over defaults
  prompts/        one system prompt per desk (Phase 5 on)
  schemas/        proposal.json, strategy.json, skeptic.json, filings.json, discounts.json, debrief.json, plans.json
  briefs.py       builds each desk's prompt from engine brief slices (Phase 5 on)
tests/agents/     fake adapter and a stand-in claude binary only; never the real CLI
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
| **9. Strategy lab** | Strategy desk, strategy specs, tear-sheet memos | The lab, rule backtests and enough stored price and filing history for 10-year windows (statistics); Phases 3 and 6 |
| **10. Flight record and Patterns** | Scorecard reports per desk | Scorecard method (statistics); 30 days of decision records |
| **11. Scout** | Scout; keep-or-switch-off review once six months of scores exist; optional read-only MCP server | Eligible lab strategies for Scout to cite (Phase 9) |

## Going live

| Safety | What it does | How to use it |
|---|---|---|
| Switches | Settings (`PUT /api/agents/{desk}/enabled`, `*` for all) overrides `desk.yaml`; `DELETE` the same path to follow `desk.yaml` again. Status shows each desk's `source` (`app`, `desk.yaml` or `default`); every desk defaults to on | Settings, Desks panel |
| Health gate | A desk logs `unhealthy` and stays quiet while any engine health check is `fail`, or the engine's last run finished over 36 hours ago. Warnings don't block. | Fix the failing check; the next run goes ahead |
| Dry run | `python -m desk.agents dry-run <desk>` builds the real brief and prompt from live data and prints them with the health checks and any skip reason. It calls no model and writes nothing. | Add `--symbol`, `--question`, `--system` or `--schema` as needed |
| First-run guard | On until the Plan keeper and the Tax desk have each finished an ok run, then it lifts itself and every desk that is on starts on its schedule (the Debrief and Plan desks are never held; they only write text and drafts). Status shows the other desks as guarded until then, and `guard.why` says which run is missing. | Nothing to do. `python -m desk.agents guard off` (or `PUT /api/agents/guard`) lifts it early |
| Recovery | A run or request left `running` by a stopped process is closed or queued again at the next `run` or `queue`, but only while no desk holds the run lock. A request interrupted twice fails. | Automatic |

## Before you start

- [ ] Run `claude setup-token` on your PC and keep the token for the TrueNAS secret, never in the repo or chat.
- [ ] Note the date you created it, for the status page.
- [ ] Pick the first weekly usage budget once two weeks of runs are logged.

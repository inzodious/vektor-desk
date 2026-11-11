# Vektor Desk UI

Vite + React. Hand-rolled SVG charts, no chart library. Tokens are copied from Escape Vektor into `src/styles/tokens.css`; spec in [docs/design.md](../docs/design.md), reference in [mockups/](../mockups/).

| Command | What it does |
|---|---|
| `npm run dev` | Dev server, `/api` proxied to `DESK_API` (default `http://127.0.0.1:8000`) |
| `npm run dev:fixtures` | Dev server on the synthetic JSON in `src/fixtures/` |
| `npm run lint` | ESLint, zero warnings |
| `npm test` | Vitest unit tests |
| `npm run build` | Builds `dist/`, served by the API |
| `npm run test:e2e` | Playwright on a fixtures preview, desktop 1440 and phone 390 |
| `npm run fixtures` | Rebuilds the fixtures from a demo API (`DESK_DEMO=1`) with seeded intraday moves |
| `python scripts/demo_seed.py` | Seeds synthetic proposals, agent runs, a brief, research rows (filings, earnings, insiders, FRED), a watched symbol, dossiers, Console questions and a year of decided calls for the flight record into a demo data dir (run with `DESK_DEMO=1 DESK_DATA_DIR=…` before `npm run fixtures`) |
| `python scripts/demo_lab.py` | Writes a synthetic lab market, queues three strategies, a finalize and three rule tests, runs the lab and steps one paper portfolio (same env, after `demo_seed.py`) |
| `python scripts/demo_replay.py` | Runs the replay engine on a seeded synthetic market and trade story and writes `src/fixtures/engine.replay*.json` (run from the repo root; no data dir needed) |
| `npm run screens -- <dir>` | Screens at 1920, 1440, 390 in light and dark (needs a preview on 4318, fixtures on 4319) |

## Fixtures

`src/fixtures/<path>.json` answers `/api/<path>`, with `/` as `.`. Every value is synthetic, taken from the demo desk.

| Lookup order | Example |
|---|---|
| `?scenario=name` on the page URL | `live.stale.json` |
| `?ids=` (non-alphanumerics become `_`) | `compare.FXAIX_FTEC_VXUS.json` |
| `?symbol=` | `engine.lots.FTEC.json` |
| `?scope_id=` | `engine.series.plan_shadow.json` |
| any symbol | `engine.prices.any.json` |
| the bare path | `engine.metrics.json` |

For real shapes, run the API in demo mode (`DESK_DEMO=1`) and use `npm run dev`.

## Pages

Menu: Bridge, Results, Portfolio, Strategies, Decisions, Research, with Settings behind the gear. `/plan/*` and `/lab/*` redirect to the new routes.

| Route | State |
|---|---|
| `/` Bridge | Live value, 4 KPIs with drawers, today's run, what changed (brief and movers) and steps due (queue and plan steps). Holdings board, mix and instruments, discount days and the shadow chart open in drawers |
| `/results/:kind` | Day, week, month and year review with the debrief; `?end=` for older periods |
| `/portfolio` Holdings | Six KPIs, departures board, drift bullets, rules with desk.yaml version, funds, modelled deposit split with drift after, FI path |
| `/portfolio/stocks` | One plan card per holding with forms; `?symbol=` scrolls to a card |
| `/portfolio/risk` | Drop from the high, six risk KPIs with drawers, return against risk, correlation heatmap, drawdowns, scenario shocks, look-through and sectors, month-by-month heatmap |
| `/portfolio/tax` | Realized and unrealized gains by term, tax calendar with wash windows |
| `/strategies` Race | Leaderboard, stage rail (draft, lab, paper, eligible), strategies with paper progress |
| `/strategies/mixes` | Time to FI by monthly deposit, each mix's range of outcomes, hold or trim for conviction positions |
| `/strategies/habits` | Replay card, rule tests, market context tiles with base rates, each holding against its own past, seasonality, correlation shifts, your own buying habits |
| `/strategies/habits/replay` | You versus the capped you: your own trades replayed under one rule at a time (`?rule=`) |
| `/strategies/:id` | Strategy: verdict lamps, holdout, paper portfolio and trades, walk-forward tiles, analyses, factor check. Rule test: setup, against never selling, every setting, horizons |
| `/decisions` | Queue of proposal cards, detail with Preflight annunciator, override box, order ticket, sources and history; To place list |
| `/decisions/journal` | Stamped ledger, 20 entries a page, filters for origin, status, kind and symbol in the URL; discipline streak, overrides against clean, unmatched trades with Log it |
| `/decisions/flight` | Total against the safe mix, a card per desk, calibration, groups at 30, 90 or 365 days, saves, off-mix gap, every decided call |
| `/research` | Dossier list, watchlist and market backdrop; open dossier (`?s=` picks one) |
| `/research/sources`, `/watchlist`, `/calendar` | Every cited source by kind; watchlist with add and remove; earnings, filings, insider trades, Treasury yields |
| `/research/compare` | Two to five slots (ticker, portfolio, account, shadow) in `?ids=`, window combo `?w=`; growth of 100, fund overlap, six small multiples, side-by-side table |
| `/research/boards` | Saved Compare, Risk and My habits views with their slicers, kept in this browser |
| `/settings` Desk | Desk profile and editor, Start here (Risk check, First run), version, build and theme |
| `/settings/crew` | Crew tiles with switches, kill switch, weekly usage and run log |
| `/settings/data` | Data freshness with the mirror tables drawer, inbox upload (`#inbox`), keys (`#keys`) |
| `/settings/box` | Scheduled jobs (`#jobs`), box buttons, Claude token (`#token`) |
| `/settings/risk`, `/settings/first-run` | Risk check with conviction holds; first-run checklist |
| Console, symbol search | Robot button or `?open=console`; `/` or the search button finds a symbol and opens its sheet |

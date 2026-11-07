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
| `python scripts/demo_seed.py` | Seeds synthetic proposals, agent runs, a brief, research rows (filings, earnings, insiders, FRED), a watched symbol, dossiers and Console questions into a demo data dir (run with `DESK_DEMO=1 DESK_DATA_DIR=…` before `npm run fixtures`) |
| `npm run screens -- <dir>` | Screens at 1920, 1440, 390 in light and dark (needs a preview on 4318, fixtures on 4319) |

## Fixtures

`src/fixtures/<path>.json` answers `/api/<path>`, with `/` as `.`. Every value is synthetic, taken from the demo desk.

| Lookup order | Example |
|---|---|
| `?scenario=name` on the page URL | `live.stale.json` |
| `?symbol=` | `engine.lots.FTEC.json` |
| `?scope_id=` | `engine.series.plan_shadow.json` |
| any symbol | `engine.prices.any.json` |
| the bare path | `engine.metrics.json` |

For real shapes, run the API in demo mode (`DESK_DEMO=1`) and use `npm run dev`.

## Pages

| Route | Phase | State |
|---|---|---|
| `/settings` | 1, 5 | Freshness, token and running jobs from `/api/status`; crew tiles with switches, kill switch, weekly usage and run log from `/api/agents` |
| `/` Bridge | 2 to 5 | Live value, 7 KPIs with drawers, departures board, value versus the plan and S&P shadows, gauges, drift bullets, today's brief and the top three proposals |
| `/plan` | 3, 5 | Plan KPIs, drift bullets, rules with desk.yaml version, funds, modelled deposit split with drift after, tax calendar with wash windows |
| `/decisions` | 4 | Queue of proposal cards, detail with Preflight annunciator, override box, order ticket, sources and history; To place list |
| `/decisions/journal` | 4 | Stamped ledger, discipline streak, overrides against clean, unmatched trades with Log it |
| `/research` | 6 | Dossier list, watchlist and market backdrop; open dossier with verdict, valuation range, thesis and bear case, price against the core fund, triggers, key numbers, filings and sources (`?s=` picks one) |
| `/research/sources`, `/watchlist`, `/calendar` | 6 | Every cited source by kind; watchlist with add and remove; upcoming earnings, recent filings and insider trades, Treasury yields |
| Console, symbol search | 6 | Robot button or `?open=console`: history, suggested questions, Tonight and Run now. `/` or the search button finds a symbol and opens its sheet, now with the dossier |
| `/lab` Compare | 7 | Two to five slots (ticker, portfolio, account, shadow) in `?ids=`, window combo `?w=`; growth of 100, fund overlap, six small multiples, side-by-side table |
| `/lab/risk` | 7 | Drop from the high, six risk KPIs with drawers, return against risk, correlation heatmap, drawdowns, scenario shocks, look-through and sectors, month-by-month heatmap |
| `/lab/boards` | 7 | Saved Compare and Risk views with their slicers, kept in this browser |
| `/decisions/flight`, `/lab/patterns` | 10 | Hero and a "lands in phase" card |

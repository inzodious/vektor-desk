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
| `python scripts/demo_decisions.py` | Seeds synthetic proposals into a demo data dir (run with `DESK_DEMO=1 DESK_DATA_DIR=…` before `npm run fixtures`) |
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
| `/settings` | 1 | Live from `/api/status` and `/api/health` |
| `/` Bridge | 2, 3 | Live value, 7 KPIs with drawers, departures board, value versus the plan and S&P shadows, gauges, drift bullets |
| `/plan` | 3 | Plan KPIs, drift bullets, rules with desk.yaml version, funds, modelled deposit split with drift after |
| `/decisions` | 4 | Queue of proposal cards, detail with Preflight annunciator, override box, order ticket, sources and history; To place list |
| `/decisions/journal` | 4 | Stamped ledger, discipline streak, overrides against clean, unmatched trades with Log it |
| `/decisions/flight`, `/research`, `/lab` | 6 to 11 | Hero and a "lands in phase" card |

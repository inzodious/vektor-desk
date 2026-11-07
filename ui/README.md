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
| `npm run screens -- <dir>` | Screens at 1920, 1440, 390 in light and dark (needs a preview on 4318, fixtures on 4319) |

## Fixtures

`src/fixtures/<path>.json` answers `/api/<path>`, with `/` as `.`. Add `?scenario=name` to the page URL to load `<path>.<name>.json`. Every value is synthetic.

For real shapes, run the API in demo mode (`DESK_DEMO=1`) and use `npm run dev`.

## Pages

| Route | Phase | State |
|---|---|---|
| `/settings` | 1 | Live from `/api/status` and `/api/health` |
| `/`, `/research`, `/decisions`, `/plan`, `/lab` | 2 to 11 | Hero and a "lands in phase" card |

# Architecture and infrastructure

How Vektor Desk runs on the TrueNAS box, how data reaches it, how it is reached, and the one-time setup. Everything here is free: Tailscale's personal plan, Porkbun's API, Let's Encrypt, and the Firebase free quota.

Status: November 7, 2026. Built and tested in a container; not yet installed on the NAS.

## The shape of it

```
Escape Vektor (Netlify) ── Firestore lockIn/{uid}/{table}/{id} = {json, at}
                                   │  read-only service account (Cloud Datastore Viewer)
                                   ▼
TrueNAS SCALE 24.10 ─ custom app "vektor-desk" (deploy/compose.yaml)
  ├─ tailscale  its own tailnet node "desk" (tag:desk); the only way in
  ├─ caddy      https://desk.escape-vektor.com on that node's address; certificate through Porkbun's DNS API
  ├─ api        FastAPI on :8000, compose network only; serves the UI once it lands
  ├─ cron       python -m desk.scheduler running deploy/crontab: mirror, engine, agents (claude -p)
  ├─ ntfy       phone alerts at https://desk.escape-vektor.com:8443, through the same caddy
  └─ lab        strategy sweeps, no network at all (commented out until desk.lab lands)
```

The NAS publishes no port for the desk. The TrueNAS UI keeps 443 on the LAN; Caddy listens inside the tailscale container's network namespace, so `desk.escape-vektor.com` answers only on the tailnet.

## Reaching it

- **Tailscale.** The `tailscale` service joins your tailnet as its own node, `desk`, separate from the existing `starlite` node. Your PC and phone reach it like any other tailnet device. It runs in kernel mode with `/dev/net/tun`, the same way your existing Tailscale app does.
- **DNS.** A Porkbun A record, `desk` → the node's `100.x.y.z` address. It resolves publicly but leads nowhere off the tailnet, and your home IP is never published.
- **Certificate.** Caddy is built with `caddy-dns/porkbun` and proves the domain with a DNS TXT record (Let's Encrypt DNS-01), so it needs no open port and works before the A record exists. Certificates renew on their own.
- **Second fence.** Caddy drops any request whose source is not a tailnet address (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`).
- **If the name doesn't resolve at home.** Some routers and DNS filters drop public answers that point at private ranges. Fix it in the Tailscale admin console, DNS, by adding `1.1.1.1` as a global nameserver with "Override local DNS".
- **Not used:** Cloudflare Tunnel and Access, Tailscale Funnel. Moving `escape-vektor.com` to Cloudflare nameservers would only be needed for access from a device without Tailscale.

## Data

All state lives in `/mnt/Manifest/apps/vektor-desk/data`, mounted at `/data`, owned by the TrueNAS `apps` user (568).

| Path | Written by | What it is |
|---|---|---|
| `mirror.db` | the mirror only | Escape Vektor's Firestore rows, read-only to everything else |
| `desk.db` | engine and agents (see [statistics.md](statistics.md), [agents.md](agents.md)) | The desk's own state; ATTACHes `mirror.db` read-only |
| `inbox/fidelity/` | you | Fidelity lot exports (Positions, Cost basis, Download) |
| `lab/data`, `lab/queue`, `lab/runs` | engine, agents, lab | Price and filing data, experiment specs, results ([statistics.md](statistics.md)) |
| `run/*.lock` | any long job | Who is running now; deploys wait for these |
| `home/` | Claude Code | The CLI's home folder |

### The mirror

`python -m desk.mirror` runs at 8:00 and 17:00 ET, after Escape Vektor's 7:30 and 16:30 bank pulls.

- **Read-only by construction.** It signs in as a Google service account with only the Cloud Datastore Viewer role, which can read Firestore and cannot write, delete or change rules. The code only lists, reads and queries. The desk never writes to Escape Vektor.
- **Every table.** It lists the collections under `lockIn/{uid}`, so `positions`, `snapshots`, `activity`, `plans`, `transactions`, `paystubs`, `prices` (`board`), `priceCloses` (`{SYM}_{YEAR}`), `priceProfiles` and anything Escape Vektor adds later come along. If listing is refused it falls back to a fixed list (`desk/config.py`).
- **Cheap on the free quota.** The first pull of each table, and one pull a week after that, reads every row; that weekly pass is also when deletions show up. The other pulls ask only for rows whose `at` timestamp moved since the last one, so a quiet day costs a handful of document reads instead of the whole dataset twice. `--full` forces a full pass.
- **Guards.** A pull that would empty the mirror (a wrong `DESK_UID`, a revoked key) is refused and the last good copy stays. Rows whose `json` doesn't parse are skipped and counted.

Schema (`desk/mirror/store.py`):

| Table | Holds |
|---|---|
| `rows(tbl, id, json, at)` | Current state, one row per Firestore document; a view `ev_<tbl>` per table |
| `row_history(seq, tbl, id, json, at, pulled_at, op)` | Append-only: one row each time a document's `json` changes (`upsert`) or it disappears (`delete`), so any past state can be rebuilt |
| `tables(tbl, rows, mirrored_at, full_at, max_at)` | Freshness per table |
| `runs(...)` | One row per pull: counts, seconds, error |

Firestore document ids are `encodeURIComponent(JSON.stringify(primaryKey))`; each row's `json` carries its own `id`, and `positions.json.snapshotId` equals `snapshots.json.id`.

## Compute budget

The box is a Ryzen 5 5600GT (6 cores, 12 threads) with 15 GiB of RAM and no swap, shared with Jellyfin, Home Assistant, Ollama, kokoro, Hemline and Starlite. There's no usable GPU, so everything runs on the CPU.

| Service | Now (16 GB) | After the 32 GB upgrade |
|---|---|---|
| tailscale, caddy | 96 MB each | same |
| api | 256 MB | same |
| cron (mirror, engine, one agent at a time) | 640 MB | 2 GB |
| lab | 1.5 GB, 3 CPUs, 3 workers | 8 GB, 8 CPUs, 8 workers |

- Heavy sweeps run from 1:00 to 6:00 ET and never alongside an agent run (`desk.runlock.job_lock`).
- Disk: the Manifest NVMe has about 110 GiB free. The desk's budget is 20 GiB, with lab data under 5 GiB and run artifacts pruned after 30 days.
- After the upgrade, raise the limits in `deploy/compose.yaml` and paste it into the app again.

## Claude Code

The image carries the Claude Code CLI 2.1.308, pinned through npm the way Hemline does it, with `DISABLE_AUTOUPDATER=1` and `HOME=/data/home`. The `cron` service is the only one with `CLAUDE_CODE_OAUTH_TOKEN`, from `claude setup-token` (one year, billed to your subscription, no API spend). How agents call it is in [agents.md](agents.md). `deploy.sh check` runs a one-line smoke test.

The desk status page counts down to `DESK_CLAUDE_TOKEN_EXPIRES` and flags renewal 30 days ahead. To renew: `claude setup-token` on your PC, run `setup-truenas.sh` again and answer "n" to keeping `desk.env`, then `midclt call app.redeploy vektor-desk`.

## Phone alerts

Self-hosted **ntfy** (`binwiederhier/ntfy:v2.33.1`) runs as the `ntfy` service. Caddy serves it at `https://desk.escape-vektor.com:8443` behind the same tailnet fence (ntfy can't live under a sub-path, so it gets its own port on the same name and certificate). Messages and a week of history stay on the NAS. With `upstream-base-url: https://ntfy.sh`, ntfy.sh only relays a "poll now" wake-up keyed by a hash of the topic, which the iPhone app needs for instant delivery. Free, no account.

| Topic | Server name | Carries |
|---|---|---|
| `alerts` | `desk-alerts` | Rule breaches, Preflight blocks, trigger hits, wash-sale windows |
| `research` | `desk-research` | Research ready, the daily brief, proposals waiting |
| `ops` | `desk-ops` | Stale or failing mirror, Claude token renewal, a stopped auto-deploy or failed nightly backup |

Calling it from a package:

```python
from desk.notify import publish

publish("alerts", "Plan keeper: rule breach", "Satellite cap passed. Open Decisions.", "high", click="/decisions", key="cap-2026-11-07")
```

| Rule | Detail |
|---|---|
| Never raises on delivery | A down server or bad answer returns `False` and logs `failed`; bad topic or priority names raise `ValueError` |
| Generic text | Dollar amounts become `$…`; title cut at 80 characters, body at 280. Keep symbols and figures in the desk, not the alert |
| Links | `click` must be a desk path (`/decisions/…`) or a full `https://desk.escape-vektor.com/…` link; anything else is dropped |
| Dedupe | Same `key` within 20 hours (`dedupe_hours=`) sends once; failed sends don't count, so the next try goes out |
| Off switches | Settings toggles per topic (`PUT /api/notify/topics/{topic}`); demo mode logs `demo` and sends nothing; an empty `DESK_NTFY_URL` logs `off` |
| Log | Every attempt goes to `notify_log` in `desk.db`; `GET /api/notify/recent` and `GET /api/notify/topics` read it |
| Ops check | `python -m desk.notify ops` at 9:20 and 18:20, after the mirror pulls; once a day per mirror state, once a week for the token |

The fallback, if self-hosting ever gets in the way, is the public ntfy.sh with a long random topic. It's simpler, but the text then passes through a third party.

## Secrets

Never in the repo, a chat or an issue. Everything lives in root-only files beside the data folder, outside the containers' `/data`. Templates with names only are in `deploy/env/`.

| File in `/mnt/Manifest/apps/vektor-desk/` | Names | Read by |
|---|---|---|
| `settings.env` | `DESK_FIREBASE_PROJECT`, `DESK_UID`, `DESK_CLAUDE_TOKEN_EXPIRES` (settings, not secret) | api, cron |
| `desk.env` | `CLAUDE_CODE_OAUTH_TOKEN`, `TIINGO_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY`, `DESK_SEC_USER_AGENT` | cron |
| `caddy.env` | `PORKBUN_API_KEY`, `PORKBUN_API_SECRET_KEY` | caddy |
| `tailscale.env` | `TS_AUTHKEY` (first sign-in only) | tailscale |
| `firestore-reader.json` | the service account key, owned by `apps`, mode 400 | cron |

The service account can also read life-stack's `users/` data in the same Firebase project. That's acceptable for a personal box, but keep its only copy on the NAS and in your password manager.

## Backups

- **Nightly at 3:45** (TrueNAS cron job, `deploy.sh backup`): consistent copies of every SQLite file through SQLite's backup API, each checked with `quick_check`, plus `inbox/`, as a dated tarball in `/mnt/Singularity/backups/vektor-desk`. The newest 14 are kept. Every deploy takes one first too.
- **What matters.** `desk.db` (decisions, proposals, scorecards) and `inbox/` can't be rebuilt. `mirror.db` can be re-pulled from Firestore at any time.
- **Restore.** Stop the app, then `tar -xzf /mnt/Singularity/backups/vektor-desk/vektor-desk-<date>.tar.gz -C /mnt/Manifest/apps/vektor-desk/data`, then `chown -R 568:568` that folder and start the app.
- **Why Singularity.** Manifest is a single disk, so backups go to the RAIDZ1 pool.

## Deploys

The same pattern as Hemline: `deploy/deploy.sh` runs as root on the NAS.

- `now` pulls `main`, builds `vektor-desk:local` and `vektor-desk/caddy:local` stamped with the commit, backs up, runs `app.redeploy`, and waits for the API to report healthy at that commit. If it doesn't, it rolls back to the previous images. It refuses while a desk job holds a run lock.
- `auto` does the same every 5 minutes when `main` has moved, waits out running jobs, and doesn't retry a failed commit until the next push.
- `status` shows what's live, GitHub, container health, the tailnet address, backups and the desk's own status.
- `check` tests the Claude sign-in, Firestore read access, the DNS record against the tailnet address and the certificate, and sends a test alert to `desk-ops`.
- `auto` and `backup` send a high-priority `desk-ops` alert when they stop on an error; `now` doesn't, since you're watching it.
- A change to `deploy/compose.yaml` isn't picked up by a redeploy. The deploy log says when it changed; paste it into Apps → vektor-desk → Edit.

## One-time setup

In order. Steps 1–4 happen in a browser or on your PC; 5–9 happen in the TrueNAS shell (`sudo -i`); 10 is on your phone.

1. **Tailscale.** In the admin console, Access controls, add `"tag:desk": ["autogroup:admin"]` to `tagOwners`, beside `tag:starlite`. Then go to Settings → Keys → Generate auth key, with reusable off and tag `tag:desk`. Tagged devices don't expire, so the node stays signed in.
2. **Porkbun.** Account → API Access: create a key and keep both the API key and the secret. Then go to Domain Management → `escape-vektor.com` → Details and turn on **API Access** for that domain.
3. **Firestore reader.** In the Google Cloud console for Escape Vektor's Firebase project, go to IAM & Admin → Service Accounts → Create service account (`vektor-desk-reader`). Give it the role **Cloud Datastore Viewer** and nothing else. Then Keys → Add key → JSON. Copy it to the NAS with `scp vektor-desk-reader.json truenas_admin@192.168.0.113:/tmp/` and delete it from your PC once it's in your password manager. Note your Firebase project ID and your user UID (Firebase console → Authentication → Users).
4. **Claude token.** On your PC, run `claude setup-token` and keep the token it prints.
5. **Checkout and setup.** Clone the repo with the token the other apps use, then run the setup script. It creates the datasets and folders, asks for each value (nothing is echoed), moves the key into place, pins the cron copy of `deploy.sh` and builds both images:

   ```sh
   git -c credential.helper="store --file=/mnt/Manifest/apps/.git-credentials" clone https://github.com/inzodious/vektor-desk.git /mnt/Manifest/apps/vektor-desk-src
   bash /mnt/Manifest/apps/vektor-desk-src/deploy/setup-truenas.sh /tmp/vektor-desk-reader.json
   ```

6. **Install the app.** Apps → Discover Apps → ⋮ → **Install via YAML**, name it `vektor-desk`, and paste `deploy/compose.yaml` as it is.
7. **DNS record.** `docker exec vektor-desk-tailscale tailscale ip -4` prints the node's address. At Porkbun, add an A record with host `desk`, that address, and TTL 600.
8. **Cron jobs.** System → Advanced Settings → Cron Jobs → **Add**, user `root`, for each one (tick Hide Standard Output and Hide Standard Error on the auto-deploy):

   | Description | Command | Schedule |
   |---|---|---|
   | Vektor Desk backup | `bash /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh backup` | Daily at 03:45 |
   | Vektor Desk auto-deploy | `bash /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh auto` | Custom: minutes `*/5` |

   The cron jobs run the pinned copy, not the checkout, so a push to `main` can't run new code as root. After reading any change to `deploy.sh`, copy it again: `install -m 700 /mnt/Manifest/apps/vektor-desk-src/deploy/deploy.sh /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh`.
9. **Check.** Run `bash /mnt/Manifest/apps/vektor-desk-src/deploy/deploy.sh check`, then `docker exec vektor-desk-cron python -m desk.mirror`. On your phone with Tailscale on, `https://desk.escape-vektor.com` should list today's positions.
10. **Phone alerts.** Install the ntfy app. Settings → Default server → `https://desk.escape-vektor.com:8443`. Subscribe to `desk-alerts`, `desk-research` and `desk-ops`. The test alert from step 9 shows up in `desk-ops`; send another any time with `docker exec vektor-desk-cron python -m desk.notify test`.

## Day to day

| What | How |
|---|---|
| Deploy | Nothing: within 5 minutes of a push to `main`. Right away: `deploy.sh now` |
| Status | `deploy.sh status`, or `https://desk.escape-vektor.com/api/status` |
| Pull Escape Vektor now | `docker exec vektor-desk-cron python -m desk.mirror` (`--full` for every row) |
| Logs | `docker logs -f vektor-desk-cron`, `docker logs vektor-desk-api`, `docker logs vektor-desk-caddy`, `tail -f /mnt/Manifest/apps/vektor-desk/deploy.log` |
| Add a schedule | A line in `deploy/crontab` (minute hour day month weekday command, Eastern time) |
| Test phone alerts | `docker exec vektor-desk-cron python -m desk.notify test`; recent ones with `... desk.notify recent` |

## Package seams

Each package under `desk/` plugs in through three optional modules, found on their own at startup:

| Module | Exposes | Picked up by |
|---|---|---|
| `desk/<pkg>/api.py` | `router`, a FastAPI `APIRouter` with its own prefix | `desk/api/app.py`, which includes every router it finds |
| `desk/<pkg>/schema.py` | `SCHEMA` (idempotent SQL), optional `apply(conn)`, optional `DEPENDS = ("other_pkg",)` | `desk.db.apply_schemas`, run when the API and scheduler start (or `python -m desk.db`), one transaction per package, into `desk.db` |
| `desk/<pkg>/jobs.py` | `JOBS`, a list of `("15 8,17 * * *", "python -m desk.engine holdings")` tuples or `{"name", "schedule", "command"}` dicts | `desk.scheduler`; each job runs under a run lock named after the package and command, so deploys wait for it |

Helpers: `desk.db.desk_conn(cfg, readonly=False)` opens `desk.db` with `mirror.db` attached read-only as `mirror`. `desk.api.deps` has `get_cfg`, `get_desk_db` and `get_desk_db_readonly` for route dependencies. `desk.notify.publish` sends a phone alert (see Phone alerts). Infrastructure's routes are `/api/health`, `/api/status`, `/api/positions` and `/api/notify/...`. Test fixtures in `tests/conftest.py` are `cfg`, `desk_db`, `client` and `app_client(packages=[...])`. Package tests go in `tests/<pkg>/`, and need no `__init__.py`.

## Web app

The image's `ui` stage builds `ui/` with `npm ci` and `npm run build` (or `npm install` until a lockfile exists) whenever `ui/package.json` is present, and the build has to produce `ui/dist/index.html`. The API serves `ui/dist` at `/`. Files under `/assets` are served as they are, any other path that isn't under `/api/` gets `index.html` so client-side routes work, and an unknown `/api/...` path answers JSON 404. Until `ui/` exists, `/` shows the plain status page. `DESK_UI_DIR` points the API at another build when testing locally.

## Demo data

`desk/demo.py` builds one synthetic `mirror.db`. It covers two years of a made-up investor with an Individual and an HSA account, a four-fund plan mix and one losing single stock (ACME, half sold). It has monthly deposits and buys, quarterly dividends reinvested, weekly snapshots, pay stubs, card spending, a price board, yearly closes and profiles. Every table has the same shapes Escape Vektor writes, and `row_history` holds about 100 weekly pulls. The same seed always gives the same world.

| Use | How |
|---|---|
| Tests | the `demo_cfg` fixture (a copy, built once per test run, dated November 6, 2026) |
| By hand | `python -m desk.demo /tmp/mirror.db [--today YYYY-MM-DD] [--seed N]` |
| Demo mode | `DESK_DEMO=1`: data moves to `/data/demo/`, the API rebuilds the demo mirror daily, `/api/health` says `"demo": true`, and the real mirror job is skipped, so real data is never mixed in |

## Developing

```sh
uv venv && . .venv/bin/activate && uv pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
shellcheck deploy/*.sh
docker build -t vektor-desk:local . && docker build -t vektor-desk/caddy:local deploy/caddy
```

Tests use synthetic rows only (`tests/fakes.py`, `desk/demo.py`), never real data.

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
  ├─ lab        python -m desk.engine.lab: overnight strategy sweeps, no network at all
  └─ eval       claude remote-control for QA: data and source read-only, own network, no keys (eval-access.md)
```

The NAS publishes no port for the desk. The TrueNAS UI keeps 443 on the LAN; Caddy listens inside the tailscale container's network namespace, so `desk.escape-vektor.com` answers only on the tailnet.

## Reaching it

- **Tailscale.** The `tailscale` service joins your tailnet as its own node, `desk`, separate from the existing `starlite` node. Your PC and phone reach it like any other tailnet device. It runs in kernel mode with `/dev/net/tun`, the same way your existing Tailscale app does.
- **DNS.** A Porkbun A record, `desk` → the node's `100.x.y.z` address. It resolves publicly but leads nowhere off the tailnet, and your home IP is never published.
- **Certificate.** Caddy is built with `caddy-dns/porkbun` and proves the domain with a DNS TXT record (Let's Encrypt DNS-01), so it needs no open port and works before the A record exists. Certificates renew on their own.
- **Home network.** The tailscale service also publishes 443 and 8443 on a NAS alias, `192.168.0.116`, where Caddy answers `desk-lan.escape-vektor.com` (Porkbun A record to that private address). The router forwards nothing, so it's reachable from the LAN only. Steps: [setup.md](setup.md#home-network).
- **Second fence.** Caddy drops any request whose source is not a tailnet or private address (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`, `192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`).
- **If the name doesn't resolve at home.** Some routers and DNS filters drop public answers that point at private ranges. Fix it in the Tailscale admin console, DNS, by adding `1.1.1.1` as a global nameserver with "Override local DNS".
- **Not used:** Cloudflare Tunnel and Access, Tailscale Funnel, and any port forward on the router.

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

The desk status page counts down to `DESK_CLAUDE_TOKEN_EXPIRES` and flags renewal 30 days ahead. Renewal steps are in [setup.md](setup.md#later).

## Phone alerts

Self-hosted **ntfy** (`binwiederhier/ntfy:v2.33.1`) runs as the `ntfy` service. Caddy serves it at `https://desk.escape-vektor.com:8443` behind the same tailnet fence (ntfy can't live under a sub-path, so it gets its own port on the same name and certificate). Messages and a week of history stay on the NAS. With `upstream-base-url: https://ntfy.sh`, ntfy.sh only relays a "poll now" wake-up keyed by a hash of the topic, which the iPhone app needs for instant delivery. Free, no account.

| Topic | Server name | Carries |
|---|---|---|
| `alerts` | `desk-alerts` | Rule breaches, Preflight blocks, trigger hits, wash-sale windows |
| `research` | `desk-research` | Research ready, the daily brief, proposals waiting |
| `ops` | `desk-ops` | Stale or failing mirror, a results review that didn't run, Claude token renewal, a stopped auto-deploy or failed nightly backup |

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
| Ops check | `python -m desk.notify ops` at 9:20 and 18:20, after the mirror pulls; once a day per mirror state and per review state, once a week for the token |

The fallback, if self-hosting ever gets in the way, is the public ntfy.sh with a long random topic. It's simpler, but the text then passes through a third party.

## Secrets

Never in the repo, a chat or an issue. Everything lives in root-only files beside the data folder, outside the containers' `/data`. Templates with names only are in `deploy/env/`.

| File in `/mnt/Manifest/apps/vektor-desk/` | Names | Read by |
|---|---|---|
| `settings.env` | `DESK_FIREBASE_PROJECT`, `DESK_UID`, `DESK_CLAUDE_TOKEN_EXPIRES` (settings, not secret) | api, cron |
| `desk.env` | `CLAUDE_CODE_OAUTH_TOKEN`, `TIINGO_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY`, `DESK_SEC_USER_AGENT`, `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` (Alpaca **paper** only) | cron |
| `caddy.env` | `PORKBUN_API_KEY`, `PORKBUN_API_SECRET_KEY` | caddy |
| `tailscale.env` | `TS_AUTHKEY` (first sign-in only) | tailscale |
| `firestore-reader.json` | the service account key, owned by `apps`, mode 400 | cron |

Alpaca keys are paper keys only (CLAUDE.md). `desk.paper_check.paper_base()` returns the one allowed base URL, `https://paper-api.alpaca.markets`, and raises `NotPaper` for anything else, including an `ALPACA_BASE_URL` override. Code that calls Alpaca builds its URLs from it. The lab container has no network, so paper orders go out from `cron`.

**Keys from the app** (Settings → Keys) are write-only. `PUT /api/box/keys/{NAME}` with `{"value": "..."}` seals the value to the box's own RSA-3072 key (OAEP-SHA256) and drops `data/run/box/keys/{NAME}.req`, mode 600. The private key, `/mnt/Manifest/apps/vektor-desk/box-keys.pem`, is root-only and outside `/data`, so neither the API nor any container that shares `data/run` can open a pending request. On its next run (within 5 minutes), the pinned `deploy.sh` decrypts the value, checks it again, writes that one line into the right env file (the same mapping as `setup-truenas.sh set`; a test keeps the two in step), and queues a redeploy. No call ever returns a value.

| Call | Answer |
|---|---|
| `GET /api/box/keys` | `{now, host_alive, ready, keys: [{name, file, secret, what, set, pending, last}]}`; `last` is `null` or `{name, request_id, result: saved\|refused\|failed, message, at}` |
| `PUT /api/box/keys/{NAME}` | `202 {ok: true, name, request_id, requested_at, message}` |
| Refusals | `{ok: false, error, message}`: `400 bad_body`; `404 refused` for a name that isn't a desk key (listed above, or already in an env file); `400 refused` for `PATH`, `HOME`, `LD_*`, `PYTHON*` and the like, an empty value, more than 1024 characters, a line break or `'`, an `ALPACA_API_KEY_ID` not starting `PK` (live keys never), or an `ALPACA_*URL*` that isn't the paper API; `503 host_down` until the box has checked in with its key |

The service account can also read life-stack's `users/` data in the same Firebase project. That's acceptable for a personal box, but keep its only copy on the NAS and in your password manager.

## Backups

- **Nightly at 3:45** (TrueNAS cron job, `deploy.sh backup`): consistent copies of every SQLite file through SQLite's backup API, each checked with `quick_check`, plus `inbox/`, as a dated tarball in `/mnt/Singularity/backups/vektor-desk`. The newest 14 are kept. Every deploy takes one first too.
- **One known false alarm is accepted.** SQLite 3.40 (the image's library) reports `NULL value in table.column` for some `WITHOUT ROWID` tables that hold no NULLs. When a check reports only such lines, the backup counts the NULLs in those columns itself. If there are none it keeps the copy and writes a note in the log; any real NULL, or any other line in the report, still fails the backup. The restore drill does the same.
- **What matters.** `desk.db` (decisions, proposals, scorecards) and `inbox/` can't be rebuilt. `mirror.db` can be re-pulled from Firestore at any time.
- **Restore.** Stop the app, then `tar -xzf /mnt/Singularity/backups/vektor-desk/vektor-desk-<date>.tar.gz -C /mnt/Manifest/apps/vektor-desk/data`, then `chown -R 568:568` that folder and start the app.
- **Restore drill.** `deploy.sh restore-test` unpacks the newest backup into a scratch folder, checks each database opens, passes `integrity_check` and has every package's tables, then deletes the scratch copy. The live data isn't touched. Run it once after the first nightly backup, and after any change to backups.
- **Why Singularity.** Manifest is a single disk, so backups go to the RAIDZ1 pool.

## Deploys

The same pattern as Hemline: `deploy/deploy.sh` runs as root on the NAS.

- `now` pulls `main` and builds `vektor-desk:candidate` and `vektor-desk/caddy:candidate`, stamped with the commit. Each named stage of a Dockerfile is built on its own first (`node`, `ui`, `deps`), then the image, then Caddy, so BuildKit never runs the UI build and the Python install side by side on a box that is short on memory. A build that fails while the kernel's out-of-memory count went up says so, and the hold is marked `memory`. It then backs up with the new build's code (`docker run` on the candidate image, no network), so a fix to the backup can unblock its own deploy, and only after a good backup tags the candidates `:local`, runs `app.redeploy`, and waits for the API to report healthy at that commit. If it doesn't, it rolls back to the images the containers were running, which it tagged `:previous` just before the swap. A failed backup changes no image, and the next try reuses the build. "Already live" means the running containers are at that commit, not just the image tags. It refuses while a desk job holds a run lock.
- `auto` does the same every 5 minutes when `main` has moved and been quiet for 10 minutes (`DESK_SETTLE`, seconds; commits that land together become one deploy and one restart, and **Deploy now** skips the wait), waits out running jobs, and doesn't retry a failed commit until the next push. With an approved builder (Builds on another machine) it takes that machine's image instead of building. Three things release a held-back commit without SSH: **Deploy now** in Settings → Box (`deploy.sh deploy-now`), a new box script (**Update box script**; the hold remembers which script made it), and, when the hold came from a failed backup, the next good backup (nightly, or **Back up now**).
- `status` shows what's live, GitHub, container health, the tailnet address, backups, a `Memory:` line and the desk's own status.
- `check` tests the Claude sign-in, Firestore read access, the DNS record against the tailnet address and the certificate, says whether the results reviews are fresh (with each stage of today's run), and sends a test alert to `desk-ops`.
- The cron jobs run a pinned copy at `/mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh`, so a push to `main` never reaches root on its own. When `main`'s `deploy.sh` moves on, `status`, `check` and Settings → Box say how many `deploy.sh` commits the copy is behind, and the **Update box script** action copies it over once the checkout is clean, sits exactly at `origin/main` and the script parses (temp file and `mv`, then a `desk-ops` alert). Its output names the old commit, the new one and the commits between. `touch /mnt/Manifest/apps/vektor-desk/deploy.no-self-pin` turns the action off.
- `auto` and `backup` send a high-priority `desk-ops` alert when they stop on an error; `now` doesn't, since you're watching it. A failed backup's alert carries the reason (for example the database and table that failed its check). When `auto`'s deploy stops, the same run still checks in and runs box actions, so Settings → Box keeps working.
- `redeploy` refuses when an image tagged `:local` isn't the build that's running, since it would start a build that has had no backup.
- A change to `deploy/compose.yaml` isn't picked up by a redeploy. The deploy log, a `desk-ops` alert and Settings → Box say when it changed, and **Apply compose** hands it to TrueNAS (`midclt call app.update` with `custom_compose_config_string`) after a backup. It does that only when the checkout is clean at `origin/main`, the live build is main, no job is running, and the change doesn't widen what containers can do (table below). Otherwise Settings → Box shows one banner with the reason and a Copy button, and you paste it into Apps → vektor-desk → Edit yourself.

| Needs your eyes (never applied from the app) | Compared with the installed compose, per service |
|---|---|
| Privilege | `privileged`, `build`, a `host` network, pid, ipc, uts, userns or cgroup mode |
| Grants | new `cap_add`, `devices`, `security_opt` (other than no-new-privileges), `device_cgroup_rules`, `group_add`; a shorter `cap_drop`; a changed `user`; `read_only` turned off |
| Images | an image repository the box doesn't already run (tags may change; `vektor-desk*:local` always pass) |
| Host paths | a bind mount outside `/mnt/Manifest/apps/vektor-desk` that the installed compose doesn't already have, after resolving symlinks; a relative path or `..`; a named volume with new `driver_opts`; a missing file (a missing folder is made, owned by 568) |

The check lives in the pinned `deploy.sh`, so a push to `main` can't loosen it without an Update box script tap.

## One-time setup

The checklist is in [setup.md](setup.md): ten steps, about 45 minutes, all free. It also covers what to do after `deploy.sh` or `compose.yaml` changes, the RAM upgrade, and token renewal.

## Day to day

| What | How |
|---|---|
| Deploy | Nothing: once `main` has been quiet for 10 minutes. Right away: Settings → Box → Deploy now, or `deploy.sh now` |
| Status | `deploy.sh status`, or `https://desk.escape-vektor.com/api/status` |
| Pull Escape Vektor now | Settings → Jobs → Run now, or `docker exec vektor-desk-cron python -m desk.mirror` (`--full` for every row) |
| Fill an empty desk | **Start the desk** on the Bridge (Start the desk, below): every job in order, one tap |
| Run any scheduled job now | Settings → Jobs (Run now, below); no SSH needed |
| A key or setting changes | Settings → Keys (Secrets, above); saved and redeployed within 5 minutes |
| Redeploy, deploy now, status, check, backup, restore drill, logs, update box script, apply compose | Settings → Box (Box actions, below); picked up within 5 minutes |
| Drop a Fidelity export in the inbox | Settings → Upload (Inbox upload, below) |
| Logs | `docker logs -f vektor-desk-cron`, `docker logs vektor-desk-api`, `docker logs vektor-desk-caddy`, `tail -f /mnt/Manifest/apps/vektor-desk/deploy.log`; redacted copies in `data/run/logs` every 5 minutes (`deploy.sh logs` now) |
| Let Claude QA the box | [eval-access.md](eval-access.md): a Remote Control session in the sealed `eval` container |
| Add a schedule | A line in `deploy/crontab` (minute hour day month weekday command, Eastern time) |
| Test phone alerts | `docker exec vektor-desk-cron python -m desk.notify test`; recent ones with `... desk.notify recent` |

## Run now

The API never runs a command. `POST /api/jobs/{name}/run` drops a request file in `data/run/requests/`. The scheduler in `cron` looks every 5 seconds and starts that job's own command from its job table, under the same run lock as a scheduled run. Clients send no arguments, and an unknown name is refused. Every request, accepted or not, is appended to `data/run/job-requests.log`. The scheduler writes each job's last run to `data/run/jobs/{name}.json`, and its heartbeat to `data/run/scheduler.alive`.

| Call | Answer |
|---|---|
| `GET /api/jobs` | `{now, scheduler_alive, cooldown_seconds: 300, pickup_seconds: 5, stages: ["mirror", "engine", "review", "desks", "paper", "overnight"], low_memory: {on, why}, jobs: [...]}` |
| One job | `name` (stable id, e.g. `mirror`, `engine-daily`), `title`, `package`, `schedules` (cron lines, Eastern), `running`, `running_since`, `queued`, `queued_at`, `waiting`, `waiting_since` (its turn hasn't come: heavy jobs run one at a time in low-memory mode and during the overnight run), `waiting_for` (`memory`, `night` or `null`), `last_run`, `cooldown_until`, `can_run`, `refreshes` (health check names the job fixes), `stage` (its step in today's run, or `null`) |
| `last_run` | `null`, or `{trigger: schedule\|request\|start, request_id, started, finished, result: ok\|failed\|skipped\|null, exit_code, detail, note, error, oom: cap\|box\|null}`. `result` is `null` while it runs; `trigger` is also `memory` for the alert job after a kill |
| `POST /api/jobs/{name}/run` | `202 {ok: true, job, request_id, requested_at, message}` |
| Refusals | `{ok: false, error, message, ...}`: `404 unknown_job`; `409 running` (`since`); `409 queued` (`since`); `409 waiting` (`since`); `429 cooldown` (`cooldown_until`, `retry_after`, plus a `Retry-After` header); `503 scheduler_down` |

**Today's run.** The Bridge strip walks `stages` in order and shows the jobs whose `stage` matches: `mirror`, `engine-daily`, `engine-review`, the Plan keeper, debrief and plan desks, and `engine-paper`. A package can set both fields itself with a dict entry in its `jobs.py`: `{"schedule", "command", "refreshes": ["debrief"], "stage": "desks"}`; otherwise the tables in `desk/jobrun.py` apply. A job with `"overnight"` (below) shows under the `overnight` stage.

**Reviews in health.** `/api/status` has `reviews: {state, due, last_ok, job, kinds, missing}`. `state` is `empty` before the first run, `ok` when `engine-review` finished (or the day pack in `period_reviews` was computed) since the last weekday 17:35 Eastern run that is at least 30 minutes old, `stale` when it didn't, and `failing` when the last run failed. `stale` and `failing` send one `desk-ops` alert a day.

To follow a run, poll `GET /api/jobs` every few seconds. A queued job shows `queued: true`, then `running: true`, then `last_run.finished` with the same `request_id`. The cooldown is 5 minutes from the last accepted request, per job. Times are UTC, ISO 8601, ending in `Z`.

## Start the desk

One tap runs everything a new or stale desk needs, in order. `POST /api/start` drops `data/run/start/request.json`; the scheduler in `cron` then starts each step's own job when the one before has finished, so the API still runs nothing and no cooldown applies. One chain at a time. The chain is kept in `data/run/start/chain.json` and survives a restart: a step that was cut off runs once more.

| Step | Job | Skipped when |
|---|---|---|
| Pull your accounts | `mirror` | Never |
| Fetch price history | `engine-backfill` | The `closes` health check is ok, or no pull has ever worked |
| Run today's numbers | `engine-daily` | No pull has ever worked |
| Fetch market history | `engine-french` | `french_returns` has rows |
| Write the results review | `engine-review` | There are no numbers yet |
| Scan for discounts | `engine-discounts` | There are no numbers yet |
| Check your plan, Write the debrief, Draft your stock plans | `agents-run-plan_keeper`, `agents-run-debrief`, `agents-run-plans` | All desks or that desk are off, the first-run guard holds it, the Claude token has expired, or (debrief) there is no review |
| Run the paper race | `engine-paper` | There are no numbers yet |

| Call | Answer |
|---|---|
| `GET /api/start` | `{state: idle\|running\|done, needs_start, can_start, blocked, result: ok\|partial, summary, started_at, finished_at, last_ok_at, scheduler_alive, memory: {state, low_memory, killed, note}, steps}` |
| One step | `{id, title, state: waiting\|running\|ok\|failed\|skipped, detail, fix: {label, to}\|null, job, started_at, finished_at, waiting}`. `waiting` is true while the step's job is held for its turn, in low-memory mode or behind tonight's run; `detail` says which |
| `POST /api/start` | `202` with the same body and `ok: true`; `409 running`; `503 scheduler_down` |

- A failed step is recorded and the chain goes on. `detail` is what the job said last, in its own words; `fix` names the screen that sorts it out.
- A job that exits 0 but says it skipped (`{"ok": true, "skipped": "..."}` as its last line) is shown as skipped with that reason. A desk run that ended disabled, guarded, over budget or failed is read from the crew status.
- A job already running on its schedule when its turn comes counts as the step.
- `needs_start` is true until a chain has finished with no failed step, or the desk already has accounts, numbers and a review. The UI shows the Start banner while it is true.

**What a job said.** The scheduler now reads each job's output, passes it on to the container log, and keeps the last line. `last_run` gains `note` (the `skipped` text of a job that exited 0) and `error` (the `error` text, or the last line, of one that failed). Long token-like strings are masked and both are cut at 300 characters.

## The overnight run

Every night the scheduler runs the night's work in order, one heavy job at a time, with no tap. Code: `desk/overnight.py`. State: `data/run/overnight/chain.json` (tonight's steps) and `build.json` (when the live version came up).

| Point | Rule |
|---|---|
| Window | Starts 23:30 Eastern, ends 06:30. A scheduler that comes up inside the window carries on where it was |
| One at a time | While it runs, heavy jobs take turns, whatever low-memory mode says. A job is light only if its `jobs.py` entry says `"heavy": False` or it is in `LIGHT` in `desk/scheduler.py` |
| First: the evening run again | `mirror`, `engine-daily`, `engine-review`, `engine-discounts`, the Plan keeper, the debrief. Only when a new version went live after 16:00, and then only the jobs that haven't run well on it. So a fix merged in the evening is on every page by morning, and a quiet night repeats nothing |
| Then: the night jobs | Every job whose `jobs.py` entry has `"overnight": N`, lowest first (Statistics 100 to 199, Agents 200 to 299, Concept 300 to 399). Keep `"schedule"` as the fallback: that line is skipped on a night when the run has done the job or is about to |
| A restart mid-step | The step runs again, up to three times in all. Steps already done stay done |
| A new version | Before 03:00 the night starts again from the top, so the fix is used. After 03:00 it only carries on, and adds any new night job |
| Room for a deploy | After each step the run waits for the host's next check-in (`data/run/box/host.alive`, every 5 minutes; 10 minutes at most), so a waiting deploy takes the gap instead of stopping a job |
| 06:30 | Steps that haven't started are closed as "The night ran out before its turn." A running one finishes |
| 06:45 | `notify-morning` sends one alert on `desk-research`: what is ready, then what didn't finish. It opens the Bridge |

A night job must be safe to start twice in a night and must skip what it already did. Its last printed line, as JSON, may say `{"ready": "14 holdings analysed"}` (shown on the step and in the alert) or `{"skipped": "why"}`. Beside `ready` it may add `"detail"`: one line, 300 characters at most, on what the run did; a step that ended ok shows it as its `detail`, and it never goes in the alert. Work that isn't a cron job (the lab container, a worker) is not a step; `ready(cfg)` in `desk.engine.lab.shelf` or `desk.opportunities`, when present, adds its line to the alert.

| Call | Answers |
|---|---|
| `GET /api/overnight` | `{night, state: idle\|running\|done, started_at, finished_at, build, restarts, starts: "23:30", ends: "06:30", summary, steps: [{id, job, title, state: waiting\|running\|ok\|skipped\|failed, detail, ready, started_at, finished_at}], ready: [...]}`. Before 23:30 it shows tonight's order as `idle`; through the day it shows last night's result |

## Readiness

`GET /api/readiness` tells the UI, for each page section, whether it has data and the one thing that fills it. It asks the app's own endpoints (the ones the pages load) inside the process and reads job records, the crew status and the health checks; it runs no SQL of its own against another package's tables.

| Field | Meaning |
|---|---|
| `start` | `{state, needs_start}`, copied from `/api/start` |
| `memory` | `{state, low_memory, killed, note}`, copied from `/api/start` |
| `sections[].key` | `bridge.value`, `bridge.brief`, `results.day`, `results.week`, `results.month`, `results.year`, `results.debrief`, `portfolio.holdings`, `portfolio.stock_plans`, `portfolio.risk`, `portfolio.tax`, `strategies.race`, `strategies.mixes`, `strategies.habits`, `decisions.queue`, `decisions.journal`, `research.feed`, `research.boards`, `settings.risk_check` |
| `state` | `ready`, `empty`, `stale` (results only: the review is behind) or `blocked` (it needs him on another screen) |
| `why` | One sentence; `null` when ready |
| `action` | `null` when ready, otherwise exactly one of `{kind: start, label}`, `{kind: job, job, label}`, `{kind: link, to, label}` |
| `next_auto`, `next_auto_text` | When the schedule next runs the job that fills it, e.g. `today at 5:35 PM` |

How a section that isn't ready picks its action, first match wins: something it needs is missing (it takes that section's action); its desk is off, guarded or without a token (link to the screen); the desk still needs starting (`start`); the job is running, failed last time or said it skipped (the job again, or a link for a missing key); otherwise the job, with the next scheduled time. `research.boards` is always `ready` because boards live in the browser. A package can sharpen its own rows with `desk/<pkg>/readiness.py` (Package seams).

## Memory

The NAS has 16 GB, no swap and most of it held outside the desk, so the desk watches memory itself and says what it sees in plain words. Everything here runs inside the containers except one host report; nothing new reaches root.

| Piece | What it does |
|---|---|
| `GET /api/memory` | `{state: ok\|tight\|unknown, total_mb, available_mb, swap_mb, cache_mb (ZFS file cache), scheduler: {limit_mb, used_mb}, low_memory, waiting: [{job, title, since}], queued_for_night: [{job, title, since}], killed: [{at, kind: job\|service\|outside, name, scope: cap\|box, words}], host_seen, note}`. The same block is `memory` in `/api/status` and `/api/box`; `/api/start` and `/api/readiness` carry the short form. `note` is the whole story in one or two sentences. `waiting` holds only memory waits. While the overnight run is going, a held job waits for the night's order, not for memory, so it is listed under `queued_for_night` and stays out of `waiting` and `note` |
| `low_memory` | `{on, mode: auto\|on\|off, why, since, paused: [], low_mb: 1500, roomy_mb: 4000}` |
| `PUT /api/memory/low` | `{"mode": "auto"\|"on"\|"off"}`. Answers `{ok: true}` plus the memory block; `422 bad_mode`. Logged in `data/run/job-requests.log` |
| Auto | The default. On only under real pressure: the box has under 1 GB available, or something was stopped for memory in the last 30 minutes. Off again at 1.5 GB, checked every 30 seconds. `DESK_LOW_MEMORY` sets the default before anyone picks |
| Heavy jobs one at a time | While the mode is on, the scheduler starts a heavy job only when no other heavy job is running. The rest wait in order (`data/run/waiting.json`), whether they came from the schedule, Run now or Start the desk; a waiting job shows `waiting: true` and Start shows "Waiting for its turn". A job that runs every minute skips the minute instead of queueing. Light jobs never wait: `engine-quotes`, `engine-lots`, `notify-ops`, `decisions-sync`, `agents-triggers`. A `jobs.py` dict entry can set `"heavy": false` itself |
| Pausing a service | Nothing pauses today: after #178 the lab fits. `python -m desk.memory hold -- <command>` is there for a service that measures too big: it stops the process while the mode is on and starts it again after, with the container left up so TrueNAS still sees a running app. A service is paused by listing it in `PAUSED` in `desk/memory.py` and wrapping its compose command |
| Out-of-memory kills | The scheduler compares its own cgroup's `memory.events` before and after each job. A failed job with a new kill gets `error` in plain words and `oom`: `cap` (it outgrew the scheduler's `mem_limit`) or `box` (the whole box ran out). A job killed with signal 9 counts as `box`. `desk.runlock` now passes a kill on as exit 137 |
| Host report | `deploy.sh auto` writes `data/run/box/memory.json` every 5 minutes: the kernel's `oom-kill:` lines from the last two days, each with the time, process, `cap` or `box`, and the desk service it was in (matched by container id). A cap kill in another app's container is left out |
| Alert | One `desk-ops` alert a day, sent straight after the first kill the scheduler sees (it starts `notify-ops`) and at the usual checks |

State lives in `data/run/`: `low-memory.mode.json` (his choice), `low-memory.state.json` (the scheduler's verdict every 30 seconds; other containers trust it for 10 minutes, then read `/proc/meminfo` themselves), `waiting.json`, `oom.log`.

## Container health

`/api/status` has `containers`, built from what the host already exports every 5 minutes into `data/run/logs` (`containers.txt`, `tailscale.log`, `exported_at`). It needs no newer box script and no tap. Code: `desk/containers.py`.

| Field | Meaning |
|---|---|
| `state` | `ok`, `trouble` (a core service is down, or the Tailscale log shows why the address isn't answering), `unknown` (no report yet, or older than 15 minutes) |
| `note` | The whole story in one or two sentences |
| `checked_at`, `fresh` | When the host last reported |
| `services` | `[{name, title, container, status (Docker's words), state: up\|starting\|unhealthy\|restarting\|stopped\|missing, up_seconds, exit_code, restarted_alone, words}]` for api, cron, caddy, ntfy, tailscale, and lab and eval when they exist. `restarted_alone` is true when a service came up more than 10 minutes after the last deploy |
| `tailnet` | `{state: ok\|trouble\|unknown, kind: key\|signed_out\|expired\|device\|unreachable, words, address, line}`. Read from the last 200 log lines: trouble counts only if no good start came after it, and a network blip only when it repeats. `address` is the node's tailnet address, to compare with the DNS record for `desk.escape-vektor.com` |

A container that is up says nothing about the path to it. If `tailnet.state` is `ok` and the address still doesn't answer, check that the device is on the tailnet and that the DNS record matches `address`.

## Workers

A second machine on the home network (Horizon) can take heavy jobs off the NAS. It runs the same image as `python -m desk.worker` with two settings, the desk's LAN address and a worker key, and it only ever calls the desk: the NAS opens no connection to it and needs no SSH. It holds no broker, Claude or Firestore key, and only the NAS writes the desk's databases.

| Step | How |
|---|---|
| Join | `POST /api/workers {name}` makes a key (`dwk_…`), shown once; the desk keeps only its SHA-256. Up to 4 workers. `DELETE /api/workers/{id}` removes one and its key stops working at once |
| Heartbeat | The worker posts `/api/worker/beat` every 30 seconds with its build, host name and the job it is on. `online` until 2 minutes pass without one, then `asleep`; `never` before the first |
| Queue | A package offers work with `desk.worker.offer(cfg, kind, inputs, copies=("lab",), key=...)` from a job in `cron`. That takes a copy of each database it names and queues the job in `data/run/worker/queue.db`. The same `key` is queued once, and a finished one is not repeated unless `again=True`. `desk.worker.online(cfg)` says whether a worker has checked in within the last 2 minutes, so a package can skip offering when none is there. A result is applied within seconds of landing: the result route drops a `worker-apply` request for the scheduler, and the 15-minute schedule is only the backstop |
| Copy | The worker receives `lab.db` and nothing else; widening that needs Joshua's decision. `desk.db` and `mirror.db` (his accounts, holdings, lots and the Escape Vektor copy) never leave the box: `offer`, `enqueue`, `take` and the lease all refuse any other name in plain words. `desk.worker.snapshots.take(cfg, "lab")` copies `data/lab/data/lab.db` byte for byte (the export replaces that file whole, so its fingerprint is the lab's own snapshot hash), gzips it and names it by the SHA-256 of its content (`data/run/worker/snapshots/<sha>.db.gz`). An unchanged database reuses the last copy. `snapshots.current(cfg, copy)` says whether a job's copy is still the live data |
| Lease | `GET /api/worker/next` hands the oldest queued job to the worker: `{job: {id, kind, key, inputs, attempts, snapshots: [{name, sha256, bytes, url}]}, code: {id, url}, build}`, or `204`. The worker downloads each copy once, checks its fingerprint and keeps it read-only |
| Same code | The lease names the desk's own `desk` package (`/api/worker/code/{id}`). The worker runs the job with that code in a child process, so it follows every deploy without being rebuilt. Its image only has to carry the Python packages |
| Result | `POST /api/worker/jobs/{id}/result?ok=1&seconds=…&peak_mb=…` with gzip-compressed JSON (64 MB limit), or `ok=0` with the reason as text. The API stores the file and runs nothing; it nudges the `worker-apply` job, and the scheduler in `cron` hands the file to the kind's `accept`, which checks it and writes. A refused result fails the job in plain words |
| Gone quiet | A leased job whose worker stops beating for 2 minutes goes back in line. After 3 starts it fails. Jobs must be safe to run twice |

| Call | Answer |
|---|---|
| `GET /api/workers` | `{now, summary: {state: online\|asleep\|never\|none, name, waiting, words}, workers: [{id, name, state, words, last_seen, build, host, job_id, added_at}], jobs: [...]}` |
| One job | `{id, kind, title, state: queued\|leased\|returned\|done\|failed, where: queue\|worker\|here\|null, why, queued_at, leased_at, finished_at, attempts, seconds, peak_mb}`. `why` always says where it is waiting and why, or how it ended |
| `POST /api/workers` | `201 {ok, id, name, key, desk_url, message}` plus the list; `422 bad_name`; `409 too_many` |
| `POST /api/worker/check` | Queues the built-in `worker.check` (a full integrity check of the lab data copy on the worker), to prove the path end to end; `202 {ok, job}` plus the list, or `409 no_data` when the lab data hasn't been exported yet |
| Worker calls | `Authorization: Bearer <key>`; `401` otherwise |

A job kind is a `Kind(name, title, run, accept)` listed in `desk/<pkg>/kinds.py` (Package seams). `run(inputs, files)` executes on the worker and must depend only on its inputs and the database copies; `accept(cfg, job, result_path)` executes on the NAS, validates and writes, and returns a one-line note. What happens to work no worker takes is the kind's business: the lab computes whatever its cache is missing itself.

## Builds on another machine

The image build is the heaviest thing left on the NAS. An approved builder (Horizon) makes the image for the commit auto-deploy is waiting on, signs it and sends it; the box checks the signature, loads it and carries on with the usual backup, restart and rollback. With no builder, a sleeping one, a slow one or a refused image, the box builds stage by stage as before.

| Step | How |
|---|---|
| Who may build | A worker key is not enough: anything on the home network can make one. The builder has its own RSA key, made on that machine and never sent anywhere. The box takes an image only when it is signed by a key that is both listed by fingerprint in `deploy/builders.txt` on `main` and pinned on the box by **Approve builder**. So it takes a push to `main` and a tap, the same two things the box script needs |
| Ask to build | `python -m desk.worker build` (the `builder` profile in `deploy/worker/compose.yaml`) posts `/api/build/hello {public_key, protocol}` every 30 seconds with the worker key. An unknown key is kept in `data/run/box/build/pending/` and the app shows its fingerprint |
| Approve | `deploy.sh approve-builder`, from the app: with the checkout clean and at `origin/main`, it copies each pending public key whose fingerprint is listed (read from git at `origin/main`, not from the working files) into `/mnt/Manifest/apps/.vektor-desk-deploy/builders/` (root only), recomputing the fingerprint with `openssl` first, and drops pinned keys that `main` no longer lists. `deploy.no-self-pin` turns it off |
| The box asks | When `main` moves, `auto` writes `data/run/box/build/want.json` and the commit's source (`git archive`) beside it. The builder downloads the source, checks its SHA-256, runs `docker build` with the same arguments the box uses, and `docker save`s the image through gzip |
| Sign and send | The builder signs the text `vektor-desk-image 1`, `commit <sha>`, `sha256 <of the file>` and posts the file to `/api/build/image/{commit}`. The API streams it to `data/run/box/build/in/` (3 GB limit), checks only that it arrived whole, and runs nothing |
| Check and load | `deploy.sh` copies the file into a root-only folder, rebuilds that text itself and verifies the signature against each pinned key with `openssl dgst -verify`. The archive may hold exactly one image named `vektor-desk:built-<commit>` and no other name (`manifest.json`, `index.json` and `repositories` are all read first), so a signed archive can't retag another app's image. Then `docker load`, and the image must carry this commit's revision label and the box's processor type. A refusal is logged, alerted on `desk-ops` and the box builds the image itself |
| Wait | `auto` waits for the image while the approved builder has checked in within 3 minutes, for at most 20 minutes (`DESK_BUILD_WAIT`). A builder that fails says so (`/api/build/failed/{commit}`) and the box stops waiting at once |
| What stays on the box | The Caddy image (cached unless `deploy/caddy` changes), the backup, the restart and the health check. The builder never gets a key, a database or a shell on the NAS |

| Call | Answer |
|---|---|
| `GET /api/build`, and `build` in `GET /api/box` | `{state: none\|asking\|approve\|online\|asleep, words, builders: [{fingerprint, name, online, last_seen}], asking: [{fingerprint, name, asked_at}], listed, want: {commit, since, arrived: image\|failed\|null}\|null, last: {commit, how: builder\|box, why, at}\|null, wait_seconds, settle_seconds, host_seen}`. `words` says who builds and where the last image came from |
| Builder calls | `Authorization: Bearer <worker key>`: `POST /api/build/hello`, `GET /api/build/source/{commit}`, `POST /api/build/image/{commit}` (`X-Desk-Sha256`, `X-Desk-Signature`), `POST /api/build/failed/{commit}` |

The builder runs Docker on its own machine, which is as good as root there, so it is a separate opt-in service and it runs the code of the checkout it was started from, never code sent by the NAS. The source of the wanted commit is served to any machine holding a worker key.

## Box actions

Chores that need root on the NAS are requests the host picks up, the same way Run now works. `POST /api/box/{action}/run` drops `data/run/box/requests/{action}.json`. The auto-deploy cron job (`deploy.sh auto`, every 5 minutes, as root) then runs `deploy.sh {action}` for each request on its allowlist: `redeploy`, `status`, `check`, `backup`, `restore-test`, `logs`, `update-script`, `apply-compose`, `deploy-now` and `approve-builder`. It reads nothing from the request except a hex id. The redacted last 300 lines of output go to `data/run/box/{action}.json`.

The host refuses to work through a symlinked `data/run/box` or a symlinked request. It writes results with `mktemp` and `mv`, so a planted link can't redirect a root write. Each auto run stamps `data/run/box/host.alive` and writes `data/run/box/script.json`, `compose.json`, `memory.json` and `builder.json`.

| Call | Answer |
|---|---|
| `GET /api/box` | `{now, host_alive, pickup_seconds: 300, script, compose, memory, build, actions: [...]}` (`memory`: Memory; `build`: Builds on another machine) |
| `script` | `null` until the host checks in, else `{checked_at, pinned, current, behind, from, to, off}`. `behind` counts `deploy.sh` commits since the cron copy (`null` if it matches no commit); `from` and `to` are full SHAs. Show Update box script when `current` is false |
| `compose` | `null` until the host checks in, else `{checked_at, state: current\|drift\|unknown, drift, escalations, missing_dirs, missing_files, can_apply, copy_available}`. On `drift`: `can_apply` shows Apply compose; otherwise one banner with `escalations` and a Copy button |
| `GET /api/box/compose.yaml` | The checkout's `compose.yaml` as `text/yaml` for the Copy button while `state` is `drift`; `404 no_change` otherwise |
| One action | `name`, `title`, `what`, `cooldown_seconds`, `running`, `queued`, `queued_at`, `last_run`, `cooldown_until`, `can_run` |
| `last_run` | `null`, or `{action, request_id, started, finished, result: ok\|failed\|skipped\|null, exit_code, output}`. `result` is `null` while it runs; a run with no finish after 2 hours counts as stale |
| `POST /api/box/{action}/run` | `202 {ok: true, action, request_id, requested_at, message}` |
| Refusals | `{ok: false, error, message, ...}`: `404 unknown_action`; `409 running` or `queued` (`since`); `429 cooldown` (`cooldown_until`, `retry_after`, plus a `Retry-After` header); `503 host_down` (no `host.alive` in 12 minutes: the cron copy of `deploy.sh` is older than this feature, or auto-deploy is off) |

Cooldowns: apply-compose 10 minutes, redeploy, update-script and deploy-now 5, status, logs and approve-builder 1, check 2, backup and restore-test 30. `update-script` and `apply-compose` end `skipped` while the checkout or live build is still catching up to `main`. Every request is logged to `data/run/box-requests.log`. `deploy.sh box` runs pending requests right away.

## Inbox upload

Broker exports go into `data/inbox/{broker}/` from the app, so no file copying over SSH. The engine's import job picks them up: `engine-lots` every 15 minutes, or straight away with Run now.

| Call | Answer |
|---|---|
| `GET /api/inbox` | `{max_bytes, suffixes: [".json", ".csv"], brokers: {fidelity: {import_job: "engine-lots", files: [{name, size, modified}]}}}` |
| `PUT /api/inbox/{broker}/{name}` | The file's bytes as the raw body (no form encoding). `201 {ok: true, broker, name, size, sha256, duplicate: false, import_job}`, or `200` with `duplicate: true` when the same bytes are already there |
| Refusals | `{ok: false, error, message}`: `404 unknown_broker`; `400 bad_name`, `empty`, `not_text`, `bad_json`, `bad_csv`; `413 too_large` |

The rules:
- Brokers on the allowlist: `fidelity`.
- Names: letters, numbers, spaces and `. _ - ( )`, ending in `.json` or `.csv`. No leading dot and no `..`.
- Content: UTF-8 text; JSON must parse; a CSV needs a comma or tab in its first line.
- Size: 25 MB (`DESK_INBOX_MAX_MB`, up to 200).
- Same name, new bytes: stored as `name-2.csv` and so on, never overwritten.
- Writes: a hidden temp file, then a hard link, so the import never sees half a file.

Every upload is logged in `data/run/inbox-uploads.log`, with its outcome, size and sha256.

## Package seams

Each package under `desk/` plugs in through five optional modules, found on their own at startup:

| Module | Exposes | Picked up by |
|---|---|---|
| `desk/<pkg>/api.py` | `router`, a FastAPI `APIRouter` with its own prefix | `desk/api/app.py`, which includes every router it finds |
| `desk/<pkg>/schema.py` | `SCHEMA` (idempotent SQL), optional `apply(conn)`, optional `DEPENDS = ("other_pkg",)` | `desk.db.apply_schemas`, run when the API and scheduler start (or `python -m desk.db`), one transaction per package, into `desk.db` |
| `desk/<pkg>/jobs.py` | `JOBS`, a list of `("15 8,17 * * *", "python -m desk.engine holdings")` tuples or `{"name", "schedule", "command", "refreshes", "stage", "heavy", "title"}` dicts (only `schedule` and `command` are required; `title` is the name he sees in `/api/jobs` and in memory messages, default the job name in words) | `desk.scheduler`; each job runs under a run lock named after the package and command, so deploys wait for it |
| `desk/<pkg>/kinds.py` | `KINDS`, a list of `desk.worker.Kind` | `desk.worker.registry`, on the NAS and inside the worker's child process |
| `desk/<pkg>/readiness.py` | `sections(cfg)`, returning `{key: {state, why, action, next_auto, next_auto_text}}` for the readiness keys it wants to answer itself | `desk.readiness`, which lays those fields over its own answer |

Helpers: `desk.db.desk_conn(cfg, readonly=False)` opens `desk.db` with `mirror.db` attached read-only as `mirror`. `desk.api.deps` has `get_cfg`, `get_desk_db` and `get_desk_db_readonly` for route dependencies. `desk.notify.publish` sends a phone alert (see Phone alerts). Infrastructure's routes are `/api/health`, `/api/status`, `/api/positions`, `/api/jobs/...`, `/api/start`, `/api/overnight`, `/api/readiness`, `/api/memory/...`, `/api/workers`, `/api/worker/...`, `/api/build/...`, `/api/box/...` (including `/api/box/keys`), `/api/inbox/...` and `/api/notify/...`. Test fixtures in `tests/conftest.py` are `cfg`, `desk_db`, `client` and `app_client(packages=[...])`. Package tests go in `tests/<pkg>/`, and need no `__init__.py`.

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
scripts/check.sh
```

| `scripts/check.sh` step | Runs |
|---|---|
| ruff check, ruff format | `ruff check .`, `ruff format --check .` (also formats Python blocks in docs) |
| pytest | the whole suite, quietly |
| shellcheck | `deploy/*.sh`, `scripts/*.sh` |
| secrets scan | tracked files for Claude, Tailscale, Porkbun, GitHub and private keys, and for `.csv`, `.xlsx`, `.ofx`, `.qfx`, `.pdf`, `.db` and `.env` files |
| compose config | `docker compose -f deploy/compose.yaml config -q --no-env-resolution` (the env files only exist on the NAS), when Docker is there |
| ui | `npm run lint`, `npm test` (each if defined) and `npm run build` in `ui/`, when it exists |
| image builds | with `--docker`: both images; the Caddy build validates the Caddyfile |

It prints one line per step and exits non-zero when any fail. Paste the summary into the PR body. Screenshots for visual changes stay with the UI's own Playwright script.

Tests use synthetic rows only (`tests/fakes.py`, `desk/demo.py`), never real data.

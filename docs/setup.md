# One-time setup

Joshua's checklist for putting Vektor Desk on the TrueNAS box. All of it is free, and it takes about 45 minutes. Steps 1–4 happen in a browser or on your PC. Steps 5–8 and 10 happen in the TrueNAS shell (System → Shell, then `sudo -i`). Step 9 is on your phone. How the pieces fit together is in [architecture.md](architecture.md).

## Checklist

| | Step | Where | Done when |
|---|---|---|---|
| ☐ | 1. Tailscale tag and auth key | Tailscale admin console | You have a `tskey-auth-…` key tagged `tag:desk` |
| ☐ | 2. Porkbun API key | porkbun.com | You have the API key and secret, and API Access is on for `escape-vektor.com` |
| ☐ | 3. Firestore read-only key | Google Cloud console | `vektor-desk-reader.json` is in `/tmp` on the NAS |
| ☐ | 4. Claude token and market keys | Your PC, three free sign-ups | You have the Claude token; market keys are optional for now |
| ☐ | 5. Checkout and setup script | TrueNAS shell | The script ends with "Next: Apps → … Install via YAML" |
| ☐ | 6. Install the app | TrueNAS Apps | `vektor-desk` shows Running |
| ☐ | 7. DNS record | Porkbun | `desk` A record points at the node's `100.x` address |
| ☐ | 8. Cron jobs | TrueNAS Advanced Settings | Both jobs listed and enabled |
| ☐ | 9. Phone alerts | ntfy app on your phone | Subscribed to the three `desk-` topics |
| ☐ | 10. Check | TrueNAS shell, then your browser | `deploy.sh check` passes, the test alert arrives, and the desk opens in your browser |

## Steps

1. **Tailscale.** In the admin console, go to Access controls and add `"tag:desk": ["autogroup:admin"]` to `tagOwners`, beside `tag:starlite`. Then go to Settings → Keys → Generate auth key. Leave reusable off and give it the tag `tag:desk`. Tagged devices don't expire, so the node stays signed in.
2. **Porkbun.** Go to Account → API Access, create a key, and keep both the API key and the secret. Then go to Domain Management → `escape-vektor.com` → Details and turn on **API Access** for that domain.
3. **Firestore reader.**
   - In the Google Cloud console, first switch the project picker at the top to Escape Vektor's Firebase project (`life-stack`), not a new project. Then go to IAM & Admin → Service Accounts → Create service account and name it `vektor-desk-reader`.
   - Give it the role **Cloud Datastore Viewer** and nothing else.
   - Then go to Keys → Add key → JSON.
   - Copy it to the NAS with `scp vektor-desk-reader.json truenas_admin@192.168.0.113:/tmp/`. Once it's in your password manager, delete it from your PC.
   - Note your Firebase project ID and your user UID (Firebase console → Authentication → Users).
4. **Claude token and market keys.** On your PC, run `claude setup-token` and keep the token it prints. It lasts a year and bills your subscription, not the API. The setup script also asks for these, and any can be left blank and added later:

   | Key | Where | Note |
   |---|---|---|
   | Tiingo | tiingo.com → Account → API | Reuse Escape Vektor's key; they share the free cap |
   | Finnhub | finnhub.io → Get free API key | Free tier |
   | FRED | fred.stlouisfed.org → My Account → API Keys | Free |
   | SEC contact | Nothing to sign up for | Typed as `Vektor Desk <your email>`; the SEC asks for a contact in the User-Agent |

5. **Checkout and setup.** Clone the repo with the token the other apps use, then run the setup script. It does the following:
   - creates the datasets and folders
   - asks for each value, without echoing it
   - moves the key into place and shreds the copy in `/tmp`
   - pins the cron copy of `deploy.sh`
   - builds both images, which takes a few minutes

   ```sh
   git -c credential.helper="store --file=/mnt/Manifest/apps/.git-credentials" clone https://github.com/inzodious/vektor-desk.git /mnt/Manifest/apps/vektor-desk-src
   bash /mnt/Manifest/apps/vektor-desk-src/deploy/setup-truenas.sh /tmp/vektor-desk-reader.json
   ```

6. **Install the app.** Go to Apps → Discover Apps → ⋮ → **Install via YAML**. Name it `vektor-desk` and paste `deploy/compose.yaml` as it is, for example from `cat /mnt/Manifest/apps/vektor-desk-src/deploy/compose.yaml`. If the install fails with "env file … not found", the setup script didn't finish: run it again (the last line says where it stopped), delete the failed app in Apps, and install again. When deleting the app, leave **Remove images** unticked: `vektor-desk:local` and `vektor-desk/caddy:local` are built on the box, not pulled, so a removed image fails the next install with "No such image" until `deploy.sh now` rebuilds it.
7. **DNS record.** `docker exec vektor-desk-tailscale tailscale ip -4` prints the node's address. At Porkbun, add an A record with host `desk`, that address, and TTL 600.
8. **Cron jobs.** Go to System → Advanced Settings → Cron Jobs → **Add** and create each job below as user `root`. Tick Hide Standard Output and Hide Standard Error on the auto-deploy job.

   | Description | Command | Schedule |
   |---|---|---|
   | Vektor Desk backup | `bash /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh backup` | Daily at 03:45 |
   | Vektor Desk auto-deploy | `bash /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh auto` | Custom: minutes `*/5` |

9. **Phone alerts.** With Tailscale on, install the ntfy app. Set Settings → Default server to `https://desk.escape-vektor.com:8443`. Then subscribe to `desk-alerts`, `desk-research` and `desk-ops`.
10. **Check.** Run these two commands in order:

    ```sh
    bash /mnt/Manifest/apps/vektor-desk-src/deploy/deploy.sh check
    docker exec vektor-desk-cron python -m desk.mirror
    ```

    | `check` line | Good looks like | If not |
    |---|---|---|
    | Claude | `signed in, answered: OK` | Redo step 4. Then `bash /mnt/Manifest/apps/vektor-desk-src/deploy/setup-truenas.sh set CLAUDE_CODE_OAUTH_TOKEN` (it saves the new token and redeploys) |
    | Firestore | `read access ok, N tables` | A 403 means the account has no role in the Firebase project. If it was made in another project, grant its `client_email` the Cloud Datastore Viewer role under IAM in the Firebase project. Then check the project ID and UID in `settings.env` |
    | Address | `match` | Redo step 7 with the printed address, then wait up to 10 minutes |
    | Home network | `not published` until you do [Home network](#home-network), then `match` | Steps 1–5 of that section |
    | Alpaca paper | `paper account ok, status ACTIVE` once the Filings lane is in use; `not set` until then | `setup-truenas.sh set ALPACA_API_KEY_ID`, then `set ALPACA_API_SECRET_KEY`, with the keys from Alpaca's **Paper Trading** dashboard. `rejected` means they're live keys or mistyped |
    | Reviews | `fresh: last run 17:36`, then each stage of today's run. `No reviews yet` until the first 17:35 weekday run | `stale` or `failing`: Settings → Jobs → Review → Run now. A stage that says `failed`: Settings → Box → Export logs, then read `cron.log` |
    | Phone alerts | `ops: sent`, and the alert arrives in `desk-ops` | Check that Tailscale is on and the server in step 9 has `:8443` |
    | Certificate | `certificate obtained` | Check that Porkbun API Access is on for the domain (step 2) |

    Then open `https://desk.escape-vektor.com` in your browser, on any device with Tailscale connected. It should show the mirror's last run and today's positions. If it hangs, Tailscale is off on that device.

## After updates

Deploys are automatic within 5 minutes of a push to `main`. Two kinds of change still need a tap in Settings → Box, and `deploy.sh status`, the deploy log and a `desk-ops` alert all say when one is waiting:

| When | Do |
|---|---|
| `deploy.sh` changed | Settings → Box → Update box script (the panel shows it when the copy is behind). Once, while the copy is older than this button, or with `deploy.no-self-pin` set, copy it by hand: `install -m 700 /mnt/Manifest/apps/vektor-desk-src/deploy/deploy.sh /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh` |
| Settings → Box says the box isn't checking in | The cron copy of `deploy.sh` is older than box actions: copy it by hand once (row above) |
| An alert says auto-deploy stopped | The alert names the reason. If it was the backup, fix that and tap Settings → Box → Back up now: a good backup releases the deploy. For anything else, Settings → Box → Deploy now retries it. Until then the old version keeps running |
| `deploy/compose.yaml` changed | Settings → Box → Apply compose. If the change widens what containers can do (a new image, host path, capability and so on; docs/architecture.md, Deploys), the panel shows why with a Copy button instead: read it, then Apps → `vektor-desk` → Edit, paste, save. `deploy.sh status` says which on its `Compose:` line |

## Home network

Open the desk at home without Tailscale, the way Hemline has its own address. Caddy also answers on a second NAS address, `192.168.0.116`, under `https://desk-lan.escape-vektor.com`, with its own certificate. Your router doesn't forward it, so it's reachable only from the home network. Tailscale and `desk.escape-vektor.com` keep working when you're away.

| | Step | Where |
|---|---|---|
| 1 | Check the address is free: `ping -c 2 192.168.0.116` should get no reply. If something answers, pick another free address and change it in both `ports:` lines of `deploy/compose.yaml` before step 5 | TrueNAS shell |
| 2 | Network → Interfaces → edit the interface that has `192.168.0.113` → Aliases → **Add**, `192.168.0.116` / `24` → Save → Test Changes → Save Changes | TrueNAS UI |
| 3 | If the TrueNAS UI listens on every address, port 443 on the alias is taken: System → General Settings → GUI → Settings → Web Interface IPv4 Address, choose `192.168.0.113` only (Hemline's `.115` may already have needed this) | TrueNAS UI |
| 4 | Add an A record: host `desk-lan`, answer `192.168.0.116`, TTL 600 | Porkbun |
| 5 | Copy `deploy.sh` for the cron jobs again (After updates), then Apps → `vektor-desk` → Edit, paste the new `deploy/compose.yaml`, save | TrueNAS shell, Apps |
| 6 | `deploy.sh check`: the Home network line says `match`. Then open `https://desk-lan.escape-vektor.com` with Tailscale off | TrueNAS shell, browser |

| If | Do |
|---|---|
| The app won't start: "address already in use" or "cannot assign requested address" | Step 3, or the alias from step 2 isn't saved |
| `desk-lan` doesn't resolve at home | The router blocks public names that point at private addresses (DNS rebind protection). Allow `escape-vektor.com` in that setting, or add `192.168.0.116 desk-lan.escape-vektor.com` to the PC's hosts file |
| You'd rather use one name everywhere | If the router can override DNS, point `desk.escape-vektor.com` at `192.168.0.116` there. At home it goes to the alias, away it resolves to the tailnet address |
| Phone alerts at home | The ntfy app still talks to `desk.escape-vektor.com:8443`, so keep Tailscale on the phone for alerts |

**App card.** In TrueNAS Apps, the app gets its own icon and a **Web UI** button that opens `https://desk-lan.escape-vektor.com`. TrueNAS forgets both when you edit the app's YAML, so `deploy.sh now`, and `auto` within 5 minutes, put them back and rebuild TrueNAS's app list (`midclt call app.metadata.generate`). To do it straight away, run `deploy.sh card` and hard-refresh the Apps page. The icon is served by the desk itself (`/icon-512.png`), so it shows when your browser is on the home network.

## Later

| When | Do |
|---|---|
| RAM goes to 32 GB | In Apps → `vektor-desk` → Edit, raise cron to `2g`. When the lab is switched on, raise it to `8g`, `cpus: 8` and `DESK_LAB_WORKERS` 8 (the notes in `compose.yaml` say where) |
| 30 days before the Claude token expires | Settings and a `desk-ops` alert flag it. Run `claude setup-token`, then paste it in Settings → Keys → `CLAUDE_CODE_OAUTH_TOKEN` and set `DESK_CLAUDE_TOKEN_EXPIRES` (or `setup-truenas.sh set` each) |
| The morning after the first nightly backup | Settings → Box → Restore drill (or `deploy.sh restore-test`): it should end with "Restore drill passed" |
| A market key arrives | Settings → Keys, or `setup-truenas.sh set TIINGO_API_KEY` (or `FINNHUB_API_KEY`, `FRED_API_KEY`; Alpaca paper: `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY`) |
| Any one setting changes | Settings → Keys (saved and redeployed within 5 minutes; values are never shown back), or `bash /mnt/Manifest/apps/vektor-desk-src/deploy/setup-truenas.sh set KEY`, e.g. `DESK_SEC_USER_AGENT` or `DESK_MARGIN_RATE_PCT`. It asks for the value (spaces kept; keys hidden), changes that one line in the right `*.env` file and redeploys. After editing an env file by hand, run `deploy.sh redeploy`: a `docker restart` or `deploy.sh now` with nothing new to build doesn't re-read env files |

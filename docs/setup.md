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
| ☐ | 10. Check | TrueNAS shell, then phone | `deploy.sh check` passes, the test alert arrives, and the desk opens on your phone |

## Steps

1. **Tailscale.** In the admin console, go to Access controls and add `"tag:desk": ["autogroup:admin"]` to `tagOwners`, beside `tag:starlite`. Then go to Settings → Keys → Generate auth key. Leave reusable off and give it the tag `tag:desk`. Tagged devices don't expire, so the node stays signed in.
2. **Porkbun.** Go to Account → API Access, create a key, and keep both the API key and the secret. Then go to Domain Management → `escape-vektor.com` → Details and turn on **API Access** for that domain.
3. **Firestore reader.**
   - In the Google Cloud console for Escape Vektor's Firebase project, go to IAM & Admin → Service Accounts → Create service account and name it `vektor-desk-reader`.
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
    | Claude | `signed in, answered: OK` | Redo step 4. Then run the setup script again, answer "n" to keeping `desk.env`, and run `midclt call app.redeploy vektor-desk` |
    | Firestore | `read access ok, N tables` | Check the role in step 3 and the project ID and UID in `settings.env` |
    | Address | `match` | Redo step 7 with the printed address, then wait up to 10 minutes |
    | Phone alerts | `ops: sent`, and the alert arrives in `desk-ops` | Check that Tailscale is on and the server in step 9 has `:8443` |
    | Certificate | `certificate obtained` | Check that Porkbun API Access is on for the domain (step 2) |

    Then open `https://desk.escape-vektor.com` on your phone. It should show the mirror's last run and today's positions.

## After updates

Deploys are automatic within 5 minutes of a push to `main`. Two kinds of change still need you, and `deploy.sh status`, the deploy log and a `desk-ops` alert all say when one is waiting:

| When | Do |
|---|---|
| `deploy.sh` changed | Read the change (`git -C /mnt/Manifest/apps/vektor-desk-src log -p -1 -- deploy/deploy.sh`), then copy it again for the cron jobs: `install -m 700 /mnt/Manifest/apps/vektor-desk-src/deploy/deploy.sh /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh`. The cron jobs run this pinned copy, so a push to `main` can't run new code as root |
| `deploy/compose.yaml` changed | Run the setup script again (it keeps what's there and adds any new folder). Then go to Apps → `vektor-desk` → Edit and paste the new file |

## Later

| When | Do |
|---|---|
| RAM goes to 32 GB | In Apps → `vektor-desk` → Edit, raise cron to `2g`. When the lab is switched on, raise it to `8g`, `cpus: 8` and `DESK_LAB_WORKERS` 8 (the notes in `compose.yaml` say where) |
| 30 days before the Claude token expires | Settings and a `desk-ops` alert flag it. Run `claude setup-token`, run the setup script again, answer "n" to keeping `desk.env` and `settings.env`, then run `midclt call app.redeploy vektor-desk` |
| A market key arrives | Run the setup script again and answer "n" to keeping `desk.env` |

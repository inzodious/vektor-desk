# Claude evaluation access

A sealed container on the box, `vektor-desk-eval`, runs Claude Code Remote Control so a Claude session (this project's threads, claude.ai/code or the Claude app) can QA the live desk: read its data and logs, re-run the engine on copies, and report. It never changes the live desk; fixes still arrive as pull requests.

## What it can and can't do

| | |
|---|---|
| Reads | `data/` (databases, inbox, lab) read-only at `/data`; the source checkout read-only at `/src`; redacted service logs in `/data/run/logs`, refreshed every 5 minutes |
| Writes | Only `eval/work` (its `/work`) and its own sign-in in `eval/home` |
| Can't | See any key or env file, or `data/home` (the desks' own Claude config and transcripts, masked by an empty tmpfs); reach the API, ntfy or the tailnet (own network); use Docker; gain privileges (all capabilities dropped) |
| Costs | Sessions draw on your Claude subscription's limits, like any Claude Code session |
| Telemetry | On in this container only. Remote Control turns away every session a project starts while Claude Code's telemetry and feature flags are off, so `start.sh` unsets the image's `DISABLE_TELEMETRY`. The desks keep it off |

The working rules Claude follows inside it are in [deploy/eval/CLAUDE.md](../deploy/eval/CLAUDE.md).

## One-time steps

Remote Control needs a full sign-in. The year-long `setup-token` the desks use is inference-only, and Remote Control refuses it ("requires a full-scope login token"). So you sign in once inside the container. The container answers the two one-time prompts itself (`deploy/eval/start.sh`): it trusts `/work` and enables Remote Control, so there's nothing to answer at a terminal.

| | Step | Where |
|---|---|---|
| 1 | Re-run the setup script (keeps your values, adds the `eval/` folders): `bash /mnt/Manifest/apps/vektor-desk-src/deploy/setup-truenas.sh` | TrueNAS shell |
| 2 | Copy the new `deploy.sh` for the cron jobs: `install -m 700 /mnt/Manifest/apps/vektor-desk-src/deploy/deploy.sh /mnt/Manifest/apps/.vektor-desk-deploy/deploy.sh` (it now exports the redacted logs) | TrueNAS shell |
| 3 | Apps → `vektor-desk` → Edit, paste the new `deploy/compose.yaml`, save | TrueNAS Apps |
| 4 | Sign in: `docker exec -it vektor-desk-eval claude auth login`. Open the link it prints, approve with your Claude account, paste the code back | TrueNAS shell, then browser |
| 5 | Within a minute it starts Remote Control: `docker logs vektor-desk-eval` shows the session link, and `vektor-desk-eval` appears as a device in claude.ai/code and in your projects | TrueNAS shell |

## Day to day

| Need | Do |
|---|---|
| Logs now, not in 5 minutes | `bash /mnt/Manifest/apps/vektor-desk-src/deploy/deploy.sh logs` |
| A project session didn't start | Read Remote Control's debug log from inside the eval session: `~/logs/remote-control.log` (on the NAS, `eval/home/logs/remote-control.log`). `Declined session` lines say why. Each start keeps the previous run as `.1`, and `deploy.sh logs` empties it past 100 MB. It holds the session's raw tool output, so it is never copied into `data/run/logs` |
| Pause it | `rm /mnt/Manifest/apps/vektor-desk/eval/home/.claude/.credentials.json && docker restart vektor-desk-eval`; it waits, idle, until step 4 is done again |
| Remove it | Delete the `eval` service in Apps → `vektor-desk` → Edit, then `rm -rf /mnt/Manifest/apps/vektor-desk/eval` |
| Clear scratch | `rm -rf /mnt/Manifest/apps/vektor-desk/eval/work/*` |

## Redaction

`deploy.sh logs` (and every `auto` run) writes the last 400 lines of each desk service's log (the eval container's too), and the deploy log into `data/run/logs`. Before writing, it replaces every value from the box's `*.env` files (8 characters or longer) and anything shaped like a Claude, Tailscale or Porkbun key, a bearer token, a `token=`/`key=`/`secret=` query value, a JWT or a service-account private key with `[redacted]`. The Firestore key file itself is never mounted into the eval container.

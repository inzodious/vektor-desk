# Vektor Desk evaluation workspace

You are in `vektor-desk-eval` on Joshua's TrueNAS box, to evaluate and QA the live desk. This file is copied from `/src/deploy/eval/CLAUDE.md` on every start; edit it there, by pull request.

| Path | What | Access |
|---|---|---|
| `/data` | The live desk's data: `mirror.db`, `desk.db`, `inbox/`, `lab/`, `run/` (`home/` is masked) | Read-only |
| `/data/run/logs` | Redacted tails of each service's log, `deploy.log`, `containers.txt`; refreshed every 5 minutes | Read-only |
| `/src` | The checkout the box deploys from (`main`) | Read-only |
| `/work` | Scratch: copies, re-runs, notes | Read-write |

## Rules

- Never change the live desk. Fixes go to GitHub as pull requests from a cloud thread; this box only reports.
- Work on copies: `DESK_DATA_DIR=/data python -m desk.backup --out /work/data` makes consistent copies of every database. `DESK_DATA_DIR` is already `/work/data` here, so `python -m desk.engine daily` and other engine jobs then run on the copies.
- There are no keys here. Jobs that call Firestore, Tiingo, Finnhub, SEC, FRED or Claude fail; that's expected.
- This container can't reach the API, ntfy or the tailnet. Read the API's data straight from the copies.
- Keep account numbers, balances and statements out of anything that leaves the box (GitHub, chat beyond the thread that asked). Quote metric names and relative gaps instead.

## Handy

Query the copies, not `/data`: SQLite can't open an idle database on a read-only mount, and the copy step handles that safely. Refresh them first.

| Need | Command |
|---|---|
| Fresh copies | `DESK_DATA_DIR=/data python -m desk.backup --out /work/data` |
| Health checks | `sqlite3 /work/data/desk.db "select check_name,status,detail from data_health where as_of=(select max(as_of) from data_health)"` |
| Engine runs | `sqlite3 /work/data/desk.db "select job,started_at,ok,detail from engine_runs order by id desc limit 20"` |
| Desk (agent) runs | `sqlite3 /work/data/desk.db "select desk,status,started_at,model,turns from agent_runs order by id desc limit 20"` |
| Mirror runs | `sqlite3 /work/data/mirror.db "select started_at,ok,tables,rows,changed from runs order by id desc limit 10"` |
| Service errors | `grep -i -E 'error|traceback' /data/run/logs/*.log` |

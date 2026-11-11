import argparse
import json
import os
import sys
from pathlib import Path

from desk.config import Config


def apply(cfg: Config) -> dict:
    from desk.worker import registry, store

    known = registry()
    saved, refused = 0, []
    for job in store.in_state(cfg, "returned"):
        path = store.result_path(cfg, job["id"])
        kind = known.get(job["kind"])
        try:
            if kind is None:
                raise ValueError("this build of the desk doesn't know that kind of job")
            if not path.is_file():
                raise ValueError("its result file is missing")
            store.finish(cfg, job["id"], note=kind.accept(cfg, job, path) or "Saved.")
            saved += 1
        except Exception as e:  # noqa: BLE001
            store.finish(cfg, job["id"], error=f"The desk didn't accept the result: {e}")
            refused.append(job["id"])
    tidy = store.tidy(cfg)
    if not saved and not refused:
        return {"ok": True, "skipped": "No results from a worker are waiting."} | tidy
    return {"ok": True, "saved": saved, "refused": refused} | tidy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.worker", description="Runs the desk's heavy jobs on another machine.")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("apply", help="on the desk: check and save results that came back, forget old jobs")
    sub.add_parser("check", help="on the desk: queue a full database check for a worker")
    add = sub.add_parser("add", help="on the desk: make a worker key")
    add.add_argument("name")
    sub.add_parser("build", help="on the other machine: build the desk's image when the box asks, sign it and send it")
    one = sub.add_parser("run-job", help="on the worker: run one job from its spec file")
    one.add_argument("spec")
    args = parser.parse_args(argv)
    if args.cmd == "run-job":
        from desk.worker.client import one as run_one

        return run_one(Path(args.spec))
    if args.cmd == "apply":
        print(json.dumps(apply(Config.from_env())))
        return 0
    if args.cmd == "check":
        from desk.worker import offer, snapshots
        from desk.worker.kinds import CHECK

        try:
            print(json.dumps({"ok": True, "job": offer(Config.from_env(), CHECK, {}, (snapshots.ONLY,))["id"]}))
        except FileNotFoundError:
            print(json.dumps({"ok": True, "skipped": snapshots.NOT_YET}))
        return 0
    if args.cmd == "add":
        from desk.worker import store

        made = store.add_worker(Config.from_env(), args.name)
        print(f"Worker {made['name']} added. Its key, shown once:\n{made['key']}")
        return 0
    from desk.worker.client import key_from, loop

    url = os.environ.get("DESK_URL", "").strip()
    work = Path(os.environ.get("DESK_WORKER_DIR", "/work"))
    if args.cmd == "build":
        from desk.worker import builder

        try:
            key = os.environ.get("DESK_WORKER_KEY", "").strip() or (work / "key").read_text().strip()
        except OSError:
            key = ""
        if not url.startswith("https://") and os.environ.get("DESK_WORKER_INSECURE") != "1":
            print("DESK_URL must start with https://", file=sys.stderr)
            return 2
        if not key:
            print("There is no worker key in the work folder yet. Start the worker first (docs/setup.md, Horizon worker).", file=sys.stderr)
            return 2
        return builder.loop(url, key, work)
    key = key_from(work)
    if not url or not key:
        print("Set DESK_URL (https://desk-lan.escape-vektor.com) and DESK_WORKER_KEY (Settings, Box, Workers, Add a worker).", file=sys.stderr)
        return 2
    if not url.startswith("https://") and os.environ.get("DESK_WORKER_INSECURE") != "1":
        print("DESK_URL must start with https://", file=sys.stderr)
        return 2
    return loop(url, key, work)


if __name__ == "__main__":
    sys.exit(main())

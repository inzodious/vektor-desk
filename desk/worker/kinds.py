import gzip
import json
from pathlib import Path

from desk import jobrun
from desk.backup import _inspect
from desk.config import Config
from desk.worker import Kind, home

CHECK = "worker.check"


def load(path: Path) -> object:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def run_check(inputs: dict, files: dict[str, Path]) -> dict:
    rows = []
    for name, path in sorted(files.items()):
        seen = _inspect(path)
        rows.append({"name": name, "check": seen["check"], "tables": len(seen["tables"]), "rows": sum(seen["tables"].values())})
    return {"files": rows}


def accept_check(cfg: Config, job: dict, result: Path) -> str:
    said = load(result)
    rows = said.get("files") if isinstance(said, dict) else None
    want = sorted(str(c.get("name")) for c in job["snapshots"])
    if not isinstance(rows, list) or sorted(str(r.get("name")) for r in rows if isinstance(r, dict)) != want:
        raise ValueError("the answer doesn't cover the copies that were sent")
    for row in rows:
        if not isinstance(row.get("tables"), int) or not isinstance(row.get("rows"), int) or not isinstance(row.get("check"), str):
            raise ValueError("the answer isn't in the expected shape")
    bad = [f"{r['name']}: {jobrun.plain(r['check'])}" for r in rows if r["check"] != "ok"]
    jobrun._write(home(cfg) / "check.json", {"at": jobrun.stamp(jobrun.now_utc()), "job": job["id"], "files": rows})
    if bad:
        raise ValueError("a copy failed its full check on the worker (" + "; ".join(bad) + ")")
    return "; ".join(f"{r['name']} passed the full check ({r['tables']} tables, {r['rows']:,} rows)" for r in rows) + "."


KINDS = [Kind(CHECK, "Check the lab data copy on the worker", run_check, accept_check)]

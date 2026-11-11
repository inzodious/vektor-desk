import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

from desk.config import Config
from desk.db import connect
from desk.packages import seams

MIRROR_TABLES = ("rows", "row_history", "tables", "runs")
TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", re.IGNORECASE)
NULL_REPORT = re.compile(r"^NULL value in ([^.\s]+)\.([^.\s]+)$")
CHECK_LINES = 1_000_000
FALSE_ALARM = "SQLite reported NULLs in {columns} that aren't there (a known false alarm in SQLite 3.40 on WITHOUT ROWID tables); the copy is good"


# ---- Integrity ----


def _report(conn: sqlite3.Connection, pragma: str) -> list[str]:
    return [str(r[0]) for r in conn.execute(f"PRAGMA {pragma}({CHECK_LINES})")]


def _nulls(conn: sqlite3.Connection, table: str, column: str) -> int:
    t, c = table.replace('"', '""'), column.replace('"', '""')
    return conn.execute(f"""SELECT count(*) FROM "{t}" NOT INDEXED WHERE typeof("{c}") = 'null'""").fetchone()[0]  # noqa: S608


def check(conn: sqlite3.Connection, pragma: str = "quick_check") -> tuple[str, list[str]]:
    lines = _report(conn, pragma)
    if lines == ["ok"]:
        return "ok", []
    problem = (lines[0] if lines else "no answer") + (f" (and {len(lines) - 1} more lines)" if len(lines) > 1 else "")
    hits = [NULL_REPORT.match(line) for line in lines]
    if not lines or len(lines) >= CHECK_LINES or not all(hits):
        return problem, []
    columns = sorted({(m[1], m[2]) for m in hits})
    try:
        real = [f"{t}.{c}" for t, c in columns if _nulls(conn, t, c)]
    except sqlite3.Error:
        return problem, []
    if real:
        return problem, []
    return "ok", [f"{t}.{c}" for t, c in columns]


# ---- Copies ----


def _source(db: Path) -> sqlite3.Connection:
    try:
        conn = connect(db, readonly=True)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except sqlite3.OperationalError:
        conn = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn


def snapshot(data_dir: Path, out_dir: Path) -> list[dict]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    done = []
    for db in sorted(data_dir.glob("*.db")):
        target = out_dir / db.name
        src = _source(db)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            verdict, false_alarm = check(dst)
        finally:
            dst.close()
            src.close()
        if verdict != "ok":
            raise sqlite3.DatabaseError(f"{db.name} copy failed its check: {verdict}")
        done.append({"db": db.name, "bytes": target.stat().st_size} | ({"false_alarm": false_alarm} if false_alarm else {}))
    inbox = data_dir / "inbox"
    if inbox.is_dir():
        shutil.copytree(inbox, out_dir / "inbox")
    return done


def notes(found: dict[str, dict] | list[dict]) -> list[str]:
    rows = [{"db": name} | info for name, info in found.items()] if isinstance(found, dict) else found
    return [f"{r['db']}: " + FALSE_ALARM.format(columns=", ".join(r["false_alarm"])) for r in rows if r.get("false_alarm")]


def expected_desk_tables() -> dict[str, list[str]]:
    out = {}
    for pkg, mod in seams("schema").items():
        names = TABLE.findall(getattr(mod, "SCHEMA", "") or "")
        if names:
            out[pkg] = names
    return out


def _inspect(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        verdict, false_alarm = check(conn, "integrity_check")
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {n: conn.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        conn.close()
    return {"check": verdict, "tables": counts, "false_alarm": false_alarm}


def verify(folder: Path) -> dict:
    problems: list[str] = []
    found: dict[str, dict] = {}
    for db in sorted(folder.glob("*.db")):
        try:
            found[db.name] = _inspect(db)
        except sqlite3.Error as e:
            problems.append(f"{db.name} won't open: {e}")
            continue
        if found[db.name]["check"] != "ok":
            problems.append(f"{db.name} failed its integrity check: {found[db.name]['check']}")
    if "desk.db" not in found:
        problems.append("there's no desk.db in the backup")
    else:
        have = set(found["desk.db"]["tables"])
        for pkg, names in expected_desk_tables().items():
            missing = [n for n in names if n not in have]
            if missing:
                problems.append(f"desk.db is missing {pkg} tables: {', '.join(missing)}")
    if "mirror.db" in found:
        missing = [n for n in MIRROR_TABLES if n not in found["mirror.db"]["tables"]]
        if missing:
            problems.append(f"mirror.db is missing {', '.join(missing)}")
    inbox = folder / "inbox"
    files = sum(1 for p in inbox.rglob("*") if p.is_file()) if inbox.is_dir() else 0
    summary = {name: {"tables": len(info["tables"]), "rows": sum(info["tables"].values())} for name, info in found.items()}
    return {"ok": not problems, "problems": problems, "databases": summary, "inbox_files": files, "notes": notes(found)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m desk.backup", description="Consistent copies of every SQLite file in the data folder, for deploy.sh backup to tar up."
    )
    parser.add_argument("--out", default="", help="folder to write into (replaced); default <data>/backup-staging")
    parser.add_argument(
        "--verify",
        default="",
        metavar="FOLDER",
        help="check an unpacked backup: every database opens, passes integrity_check and has its tables",
    )
    args = parser.parse_args(argv)
    if args.verify:
        report = verify(Path(args.verify))
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    cfg = Config.from_env()
    out = Path(args.out) if args.out else cfg.data_dir / "backup-staging"
    try:
        result = snapshot(cfg.data_dir, out)
    except (sqlite3.Error, OSError) as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "out": str(out), "files": result, "notes": notes(result)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

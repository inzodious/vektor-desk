import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from desk.config import Config
from desk.db import connect


def snapshot(data_dir: Path, out_dir: Path) -> list[dict]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    done = []
    for db in sorted(data_dir.glob("*.db")):
        target = out_dir / db.name
        src = connect(db, readonly=True)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            check = dst.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            dst.close()
            src.close()
        if check != "ok":
            raise sqlite3.DatabaseError(f"{db.name} copy failed its check: {check}")
        done.append({"db": db.name, "bytes": target.stat().st_size})
    inbox = data_dir / "inbox"
    if inbox.is_dir():
        shutil.copytree(inbox, out_dir / "inbox")
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m desk.backup", description="Consistent copies of every SQLite file in the data folder, for deploy.sh backup to tar up."
    )
    parser.add_argument("--out", default="", help="folder to write into (replaced); default <data>/backup-staging")
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    out = Path(args.out) if args.out else cfg.data_dir / "backup-staging"
    try:
        result = snapshot(cfg.data_dir, out)
    except (sqlite3.Error, OSError) as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "out": str(out), "files": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

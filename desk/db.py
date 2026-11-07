import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from desk.config import Config
from desk.packages import seams

META = """
CREATE TABLE IF NOT EXISTS schema_meta (
  pkg TEXT PRIMARY KEY,
  sha TEXT NOT NULL,
  applied_at TEXT NOT NULL
);
"""


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def desk_conn(cfg: Config | None = None, *, readonly: bool = False, mirror: bool = True) -> sqlite3.Connection:
    cfg = cfg or Config.from_env()
    if readonly:
        conn = sqlite3.connect(f"file:{cfg.desk_db}?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
    else:
        conn = connect(cfg.desk_db)
        conn.close()
        conn = sqlite3.connect(f"file:{cfg.desk_db}", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
    if mirror and cfg.mirror_db.exists():
        conn.execute("ATTACH DATABASE ? AS mirror", (f"file:{cfg.mirror_db}?mode=ro",))
    return conn


def _order(mods: dict) -> list[str]:
    done: list[str] = []
    seen: set[str] = set()

    def visit(pkg: str, chain: tuple[str, ...]) -> None:
        if pkg in done:
            return
        if pkg in chain:
            raise ValueError(f"schema dependency loop: {' -> '.join((*chain, pkg))}")
        for dep in getattr(mods[pkg], "DEPENDS", ()):
            if dep not in mods:
                raise ValueError(f"desk.{pkg}.schema depends on {dep!r}, which has no schema.py")
            visit(dep, (*chain, pkg))
        if pkg not in seen:
            seen.add(pkg)
            done.append(pkg)

    for pkg in sorted(mods):
        visit(pkg, ())
    return done


def apply_schemas(cfg: Config | None = None, *, only: list[str] | None = None) -> list[str]:
    cfg = cfg or Config.from_env()
    mods = seams("schema", only)
    conn = desk_conn(cfg)
    applied = []
    try:
        conn.executescript(META)
        for pkg in _order(mods):
            mod = mods[pkg]
            sql = getattr(mod, "SCHEMA", "")
            sha = hashlib.sha256(sql.encode()).hexdigest()[:16]
            with conn:
                conn.executescript(sql)
                extra = getattr(mod, "apply", None)
                if extra is not None:
                    extra(conn)
                conn.execute(
                    "INSERT INTO schema_meta (pkg, sha, applied_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(pkg) DO UPDATE SET sha=excluded.sha, applied_at=excluded.applied_at",
                    (pkg, sha, datetime.now(UTC).isoformat(timespec="seconds")),
                )
            applied.append(pkg)
    finally:
        conn.close()
    return applied


if __name__ == "__main__":
    print("applied:", ", ".join(apply_schemas()) or "nothing")

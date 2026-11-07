import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import desk
from desk.api.app import create_app
from desk.db import _order, apply_schemas, desk_conn
from desk.packages import packages, seams
from desk.scheduler import lock_name, package_jobs

FILES = {
    "alpha/__init__.py": "",
    "alpha/api.py": """
        from fastapi import APIRouter, Depends
        from desk.api.deps import get_desk_db_readonly

        router = APIRouter(prefix="/api/alpha")

        @router.get("/count")
        def count(db=Depends(get_desk_db_readonly)):
            return {"n": db.execute("SELECT count(*) FROM alpha_things").fetchone()[0]}
    """,
    "alpha/schema.py": """
        SCHEMA = "CREATE TABLE IF NOT EXISTS alpha_things (id INTEGER PRIMARY KEY, name TEXT);"

        def apply(conn):
            conn.execute("INSERT INTO alpha_things (name) SELECT 'seed' WHERE NOT EXISTS (SELECT 1 FROM alpha_things)")
    """,
    "alpha/jobs.py": """
        JOBS = [("15 8,17 * * *", "python -m desk.alpha refresh --fast")]
    """,
    "beta/__init__.py": "",
    "beta/schema.py": """
        DEPENDS = ("alpha",)
        SCHEMA = "CREATE VIEW IF NOT EXISTS beta_names AS SELECT name FROM alpha_things;"
    """,
}


@pytest.fixture
def fake_packages(tmp_path):
    root = tmp_path / "pkgs"
    for rel, body in FILES.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(textwrap.dedent(body))
    desk.__path__.append(str(root))
    yield ["alpha", "beta"]
    desk.__path__.remove(str(root))
    for name in [m for m in sys.modules if m.startswith(("desk.alpha", "desk.beta"))]:
        del sys.modules[name]


def test_discovers_packages_and_their_seams(fake_packages):
    assert {"alpha", "beta", "mirror"} <= set(packages())
    assert "api" not in packages()
    assert set(seams("schema", fake_packages)) == {"alpha", "beta"}
    assert set(seams("api", fake_packages)) == {"alpha"}


def test_schemas_apply_in_dependency_order_and_rerun_cleanly(fake_packages, cfg):
    assert apply_schemas(cfg, only=fake_packages) == ["alpha", "beta"]
    assert apply_schemas(cfg, only=fake_packages) == ["alpha", "beta"]
    conn = desk_conn(cfg, readonly=True)
    assert conn.execute("SELECT name FROM beta_names").fetchall()[0][0] == "seed"
    assert {r["pkg"] for r in conn.execute("SELECT pkg FROM schema_meta")} == {"alpha", "beta"}


def test_dependency_problems_fail_loudly():
    class Mod:
        DEPENDS = ("ghost",)

    with pytest.raises(ValueError, match="ghost"):
        _order({"a": Mod})


def test_app_includes_package_routers_and_applies_schemas(fake_packages, cfg):
    with TestClient(create_app(cfg, packages=fake_packages)) as client:
        assert client.get("/api/alpha/count").json() == {"n": 1}
        assert client.get("/api/health").json()["ok"] is True
        assert client.app.state.routers == ["alpha"]


def test_package_jobs_run_under_a_run_lock(fake_packages):
    (job,) = package_jobs(fake_packages)
    assert job.line == "alpha.jobs[0]"
    assert job.command[:5] == ["python", "-m", "desk.runlock", "--hold", "alpha-alpha-refresh"]
    assert job.command[6:] == ["python", "-m", "desk.alpha", "refresh", "--fast"]
    assert lock_name("mirror", ["python", "-m", "desk.mirror"]) == "mirror-mirror"


def test_mirror_job_is_scheduled():
    jobs = package_jobs(["mirror"])
    assert [j.command[-1] for j in jobs] == ["desk.mirror"]


def test_desk_conn_attaches_the_mirror_read_only(cfg):
    from desk.mirror import MirrorStore

    MirrorStore(cfg.mirror_db).close()
    conn = desk_conn(cfg)
    assert conn.execute("SELECT count(*) FROM mirror.rows").fetchone()[0] == 0
    with pytest.raises(Exception, match="readonly"):
        conn.execute("INSERT INTO mirror.rows VALUES ('a', 'b', '{}', NULL)")


def test_package_test_helpers(app_client):
    client = app_client(packages=[])
    assert client.get("/api/status").status_code == 200


def test_runlock_hold_passes_the_exit_code(cfg, monkeypatch):
    from desk.runlock import main

    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    assert main(["--hold", "x", "--", sys.executable, "-c", "raise SystemExit(3)"]) == 3
    assert main(["--hold", "x"]) == 2
    assert Path(cfg.data_dir, "run", "x.lock").exists()

import multiprocessing
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from desk.api.app import create_app
from desk.backup import snapshot, verify
from desk.db import apply_schemas, connect
from desk.mirror import FirestoreReader, MirrorStore, run_mirror
from desk.runlock import Busy, job_lock, running
from desk.status import status
from tests.fakes import FakeFirestore
from tests.infra.test_mirror import seed


def mirrored(cfg):
    store = MirrorStore(cfg.mirror_db)
    run_mirror(FirestoreReader("p", "u", FakeFirestore(seed())), store)
    store.close()


def test_status_reports_fresh_then_stale(cfg):
    assert status(cfg)["mirror"]["state"] == "empty"
    mirrored(cfg)
    assert status(cfg)["mirror"]["state"] == "ok"
    later = datetime.now(UTC) + timedelta(hours=20)
    assert status(cfg, now=later)["mirror"]["state"] == "stale"


def test_token_countdown(cfg):
    s = status(cfg, now=datetime(2027, 10, 15, tzinfo=UTC))
    assert s["claude_token"] == {"state": "renew", "expires": "2027-11-01", "days_left": 17}


def _hold(path, ready):
    from desk.config import Config

    with job_lock("agents", cfg=Config(data_dir=path)):
        ready.set()
        time.sleep(3)


def test_job_lock_is_seen_across_processes(cfg):
    ready = multiprocessing.Event()
    p = multiprocessing.Process(target=_hold, args=(cfg.data_dir, ready))
    p.start()
    assert ready.wait(5)
    try:
        assert [j["job"] for j in running(cfg)] == ["agents"]
        with pytest.raises(Busy):
            with job_lock("agents", cfg=cfg):
                pass
    finally:
        p.join()
    assert running(cfg) == []


def test_backup_copies_every_db_and_inbox(cfg, tmp_path):
    mirrored(cfg)
    conn = connect(cfg.desk_db)
    conn.execute("CREATE TABLE proposals (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    (cfg.inbox / "fidelity").mkdir(parents=True)
    (cfg.inbox / "fidelity" / "lots.txt").write_text("synthetic")
    out = tmp_path / "staging"
    files = snapshot(cfg.data_dir, out)
    assert sorted(f["db"] for f in files) == ["desk.db", "mirror.db"]
    assert connect(out / "mirror.db", readonly=True).execute("SELECT count(*) FROM rows").fetchone()[0] == 7
    assert (out / "inbox" / "fidelity" / "lots.txt").exists()


def test_backup_reads_idle_databases_on_a_read_only_mount(cfg, tmp_path, monkeypatch):
    import sqlite3

    import desk.backup as backup

    mirrored(cfg)

    def no_lock_file(path, *, readonly=False):
        if readonly:
            raise sqlite3.OperationalError("unable to open database file")
        return connect(path)

    monkeypatch.setattr(backup, "connect", no_lock_file)
    out = tmp_path / "copies"
    files = snapshot(cfg.data_dir, out)
    assert [f["db"] for f in files] == ["mirror.db"]
    assert sqlite3.connect(out / "mirror.db").execute("SELECT count(*) FROM rows").fetchone()[0] == 7


def test_api_health_status_positions_and_smoke_page(cfg):
    mirrored(cfg)
    client = TestClient(create_app(cfg))
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/status").json()["mirror"]["state"] == "ok"
    held = client.get("/api/positions").json()
    assert held["asOf"] == "2026-11-06T16:00"
    assert [p["symbol"] for p in held["positions"]][:2] == ["S5", "S4"]
    page = client.get("/")
    assert page.status_code == 200 and "Vektor Desk is up" in page.text and "S5" in page.text


def test_serves_the_built_ui_with_spa_fallback(cfg, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Vektor Desk</title><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("nope")
    monkeypatch.setenv("DESK_UI_DIR", str(dist))
    with TestClient(create_app(cfg, packages=[])) as client:
        assert "id=root" in client.get("/").text
        assert "id=root" in client.get("/bridge/holdings").text
        assert client.get("/assets/app.js").text == "console.log('hi')"
        assert client.get("/favicon.svg").text == "<svg/>"
        assert "id=root" in client.get("/../secret.txt").text
        assert client.get("/api/health").json()["ok"] is True
        missing = client.get("/api/nope")
        assert missing.status_code == 404 and missing.json()["ok"] is False


def test_restore_drill_checks_a_backup(cfg, tmp_path):
    mirrored(cfg)
    apply_schemas(cfg)
    (cfg.inbox / "fidelity").mkdir(parents=True)
    (cfg.inbox / "fidelity" / "lots.txt").write_text("synthetic")
    out = tmp_path / "restore"
    snapshot(cfg.data_dir, out)
    report = verify(out)
    assert report["ok"], report["problems"]
    assert report["inbox_files"] == 1 and report["databases"]["mirror.db"]["rows"] > 0
    conn = connect(out / "desk.db")
    conn.execute("DROP TABLE notify_log")
    conn.commit()
    conn.close()
    (out / "mirror.db").write_bytes(b"not a database")
    report = verify(out)
    assert not report["ok"]
    assert any("notify tables: notify_log" in p for p in report["problems"])
    assert any(p.startswith("mirror.db") for p in report["problems"])

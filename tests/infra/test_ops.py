import multiprocessing
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from desk.api.app import create_app
from desk.backup import snapshot
from desk.db import connect
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

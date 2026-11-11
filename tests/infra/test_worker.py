import gzip
import hashlib
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tarfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from desk import jobrun
from desk.api.app import create_app
from desk.worker import Kind, offer, registry, snapshots, store
from desk.worker import api as worker_api
from desk.worker.__main__ import apply
from desk.worker.client import loop

NOW = datetime(2026, 11, 11, 21, 0, tzinfo=UTC)


def lab_db(cfg, rows: int = 50) -> Path:
    path = cfg.data_dir / "lab" / "data" / "lab.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS bars (symbol TEXT, day TEXT, close REAL)")
    conn.executemany("INSERT INTO bars VALUES (?, ?, ?)", [("SYN", f"2026-01-{i % 28 + 1:02d}", 10.0 + i) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


def packed(obj) -> bytes:
    return gzip.compress(json.dumps(obj).encode())


def auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def client(app_client):
    return app_client(packages=["worker"])


@pytest.fixture
def horizon(client) -> dict:
    return client.post("/api/workers", json={"name": "Horizon"}).json()


@pytest.fixture
def live(cfg):
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_app(cfg, packages=["worker"]), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join(timeout=5)


# ---- Keys ----


def test_a_worker_key_is_shown_once_and_only_its_hash_is_kept(client, cfg):
    made = client.post("/api/workers", json={"name": "Horizon"})
    assert made.status_code == 201
    body = made.json()
    key = body["key"]
    assert key.startswith("dwk_") and len(key) > 40 and body["desk_url"] == "https://desk-lan.escape-vektor.com"
    seen = client.get("/api/workers").json()
    assert key not in json.dumps(seen) and seen["workers"][0]["name"] == "Horizon" and seen["workers"][0]["state"] == "never"
    assert seen["summary"] == {"state": "never", "name": "Horizon", "waiting": 0, "words": "Horizon has a key but hasn't checked in yet."}
    raw = store.db_path(cfg).read_bytes() + (
        store.db_path(cfg).with_name("queue.db-wal").read_bytes() if store.db_path(cfg).with_name("queue.db-wal").exists() else b""
    )
    assert key.encode() not in raw and hashlib.sha256(key.encode()).hexdigest().encode() in raw
    assert key not in (cfg.data_dir / "run" / "job-requests.log").read_text()


def test_names_are_checked_and_workers_are_capped(client):
    assert client.post("/api/workers", json={"name": "Horizon"}).status_code == 201
    assert client.post("/api/workers", json={"name": "horizon"}).json()["error"] == "bad_name"
    assert client.post("/api/workers", json={"name": "../etc"}).status_code == 422
    assert client.post("/api/workers", json={}).status_code == 422
    for n in range(3):
        assert client.post("/api/workers", json={"name": f"box {n}"}).status_code == 201
    assert client.post("/api/workers", json={"name": "one more"}).status_code == 409


def test_worker_calls_need_a_live_key(client, horizon, cfg):
    lab_db(cfg)
    for call in (
        lambda h: client.post("/api/worker/beat", json={}, headers=h),
        lambda h: client.get("/api/worker/next", headers=h),
        lambda h: client.get("/api/worker/snapshots/" + "a" * 64, headers=h),
        lambda h: client.get("/api/worker/code/x", headers=h),
        lambda h: client.post("/api/worker/jobs/aaaaaaaaaaaa/result", content=b"x", headers=h),
    ):
        assert call({}).status_code == 401
        assert call(auth("dwk_" + "x" * 43)).status_code == 401
        assert call({"Authorization": "Basic " + horizon["key"]}).status_code == 401
    assert client.post("/api/worker/beat", json={}, headers=auth(horizon["key"])).status_code == 200
    assert client.delete(f"/api/workers/{horizon['id']}").json()["workers"] == []
    assert client.post("/api/worker/beat", json={}, headers=auth(horizon["key"])).status_code == 401
    assert client.delete(f"/api/workers/{horizon['id']}").status_code == 404


# ---- Heartbeat ----


def test_a_worker_is_never_seen_then_online_then_asleep(cfg):
    made = store.add_worker(cfg, "Horizon", NOW)
    assert store.workers(cfg, NOW)[0]["state"] == "never"
    store.beat(cfg, made["id"], {"build": "abc1234", "host": "horizon", "job_id": None}, NOW)
    row = store.workers(cfg, NOW + timedelta(seconds=119))[0]
    assert (row["state"], row["build"], row["host"]) == ("online", "abc1234", "horizon")
    assert store.workers(cfg, NOW + timedelta(seconds=121))[0]["state"] == "asleep"
    seen = worker_api.describe(cfg, NOW + timedelta(hours=3))
    assert seen["summary"]["state"] == "asleep" and seen["summary"]["words"] == "Horizon is asleep or off: last heard 3 hours ago."
    assert worker_api.describe(cfg, NOW)["summary"]["words"] == "Horizon is online."


# ---- Copies ----


def test_a_copy_is_consistent_named_by_its_content_and_reused_until_the_database_changes(cfg):
    path = lab_db(cfg)
    first = snapshots.take(cfg, "lab")
    kept = snapshots.path_of(cfg, first["sha256"])
    raw = gzip.decompress(kept.read_bytes())
    assert hashlib.sha256(raw).hexdigest() == first["sha256"] and len(raw) == first["bytes"]
    assert raw == path.read_bytes()
    made = kept.stat().st_mtime_ns
    assert snapshots.take(cfg, "lab") == first and kept.stat().st_mtime_ns == made and snapshots.current(cfg, first)
    out = cfg.data_dir / "copy.db"
    snapshots.unpack(kept, out, first["sha256"])
    assert sqlite3.connect(out).execute("SELECT count(*) FROM bars").fetchone()[0] == 50
    with pytest.raises(ValueError, match="fingerprint"):
        snapshots.unpack(kept, cfg.data_dir / "bad.db", "0" * 64)
    assert not (cfg.data_dir / "bad.db").exists()
    time.sleep(0.01)
    lab_db(cfg, 5)
    second = snapshots.take(cfg, "lab")
    assert second["sha256"] != first["sha256"] and not snapshots.current(cfg, first) and path.exists()
    assert snapshots.prune(cfg, keep=set()) == [first["sha256"]] and snapshots.path_of(cfg, second["sha256"])
    with pytest.raises(FileNotFoundError):
        snapshots.take(cfg, "mirror")


def test_a_live_database_is_copied_through_sqlite_so_a_write_in_flight_cannot_tear_it(cfg):
    conn = sqlite3.connect(cfg.desk_db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    conn.executemany("INSERT INTO notes (body) VALUES (?)", [("x" * 200,) for _ in range(500)])
    conn.commit()
    conn.execute("INSERT INTO notes (body) VALUES ('not committed')")
    taken = snapshots.take(cfg, "desk")
    conn.rollback()
    conn.close()
    out = cfg.data_dir / "copy.db"
    snapshots.unpack(snapshots.path_of(cfg, taken["sha256"]), out, taken["sha256"])
    copy = sqlite3.connect(out)
    assert copy.execute("SELECT count(*) FROM notes").fetchone()[0] == 500 and copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert snapshots.path_of(cfg, "../../etc/passwd") is None


def test_the_code_bundle_is_the_desk_package_without_caches(cfg):
    code_id, path = worker_api.code(cfg)
    with tarfile.open(path) as tar:
        names = tar.getnames()
    assert "desk/worker/kinds.py" in names and "desk/__init__.py" in names and all(n.startswith("desk/") for n in names)
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names) and worker_api.code(cfg)[0] == code_id


# ---- Lease and result ----


def test_a_job_is_leased_run_returned_and_saved_by_the_scheduler(client, horizon, cfg):
    lab_db(cfg)
    head = auth(horizon["key"])
    asked = client.post("/api/worker/check")
    assert asked.status_code == 202
    waiting = asked.json()["jobs"][0]
    assert (waiting["state"], waiting["where"], waiting["why"]) == ("queued", "queue", "Waiting for a worker. None has checked in yet.")
    assert client.post("/api/worker/beat", json={"build": "abc"}, headers=head).json()["beat_seconds"] == 30
    assert client.get("/api/workers").json()["jobs"][0]["why"] == "Next in line for Horizon."
    lease = client.get("/api/worker/next", headers=head).json()
    job = lease["job"]
    assert job["kind"] == "worker.check" and job["attempts"] == 1 and job["snapshots"][0]["name"] == "lab"
    copy = client.get(job["snapshots"][0]["url"], headers=head)
    assert hashlib.sha256(gzip.decompress(copy.content)).hexdigest() == job["snapshots"][0]["sha256"]
    bundle = client.get(lease["code"]["url"], headers=head)
    assert "desk/worker/client.py" in tarfile.open(fileobj=io.BytesIO(bundle.content)).getnames()
    client.post("/api/worker/beat", json={"job_id": job["id"]}, headers=head)
    running = client.get("/api/workers").json()
    assert running["jobs"][0]["where"] == "worker" and running["jobs"][0]["why"].startswith("Running on Horizon, started")
    assert running["workers"][0]["words"] == "Horizon is online, working on: Check a database copy on the worker."
    assert client.get("/api/worker/next", headers=head).json()["job"]["attempts"] == 2
    result = packed({"files": [{"name": "lab", "check": "ok", "tables": 1, "rows": 50}]})
    sent = client.post(f"/api/worker/jobs/{job['id']}/result", params={"ok": "1", "seconds": "2.34", "peak_mb": "41"}, content=result, headers=head)
    assert sent.json() == {"ok": True, "state": "returned"}
    assert client.get("/api/workers").json()["jobs"][0]["where"] == "here"
    assert (jobrun.requests_dir(cfg) / "worker-apply.json").is_file()
    assert client.post(f"/api/worker/jobs/{job['id']}/result", content=result, headers=head).json() == {"ok": True, "already": True, "state": "returned"}
    assert client.get("/api/worker/next", headers=head).status_code == 204
    assert apply(cfg)["saved"] == 1
    done = client.get("/api/workers").json()["jobs"][0]
    assert (done["state"], done["seconds"], done["peak_mb"], done["where"]) == ("done", 2.3, 41, None)
    assert done["why"] == "lab passed the full check (1 tables, 50 rows)."
    assert not store.result_path(cfg, job["id"]).exists() and jobrun._read(cfg.data_dir / "run" / "worker" / "check.json")["files"][0]["rows"] == 50
    assert apply(cfg)["skipped"] == "No results from a worker are waiting."


def test_a_result_the_desk_does_not_accept_fails_in_plain_words(client, horizon, cfg):
    lab_db(cfg)
    head = auth(horizon["key"])
    for answer, why in (
        ({"files": []}, "the answer doesn't cover the copies that were sent"),
        ({"files": [{"name": "lab", "check": "row 3 missing from index", "tables": 1, "rows": 50}]}, "a copy failed its full check on the worker"),
    ):
        job = offer(cfg, "worker.check", {}, ("lab",))
        client.post("/api/worker/beat", json={}, headers=head)
        assert client.get("/api/worker/next", headers=head).json()["job"]["id"] == job["id"]
        assert client.post(f"/api/worker/jobs/{job['id']}/result", content=packed(answer), headers=head).status_code == 200
        assert apply(cfg)["refused"] == [job["id"]]
        failed = store.get(cfg, job["id"])
        assert failed["state"] == "failed" and failed["error"].startswith("The desk didn't accept the result: " + why)


def test_bad_uploads_are_turned_away(client, horizon, cfg, monkeypatch):
    lab_db(cfg)
    head = auth(horizon["key"])
    job = offer(cfg, "worker.check", {}, ("lab",))
    assert client.post(f"/api/worker/jobs/{job['id']}/result", content=b'{"files": []}', headers=head).status_code == 415
    monkeypatch.setattr(worker_api, "RESULT_MAX", 64)
    assert client.post(f"/api/worker/jobs/{job['id']}/result", content=gzip.compress(os.urandom(4096)), headers=head).status_code == 413
    assert store.get(cfg, job["id"])["state"] == "queued" and list(store.results_dir(cfg).iterdir()) == []
    assert client.post("/api/worker/jobs/ffffffffffff/result", content=packed({}), headers=head).status_code == 404
    said = client.post(
        f"/api/worker/jobs/{job['id']}/result", params={"ok": "0", "seconds": "1"}, content=b"The job failed on the worker: KeyError: 'x'", headers=head
    )
    assert said.json()["state"] == "failed" and store.get(cfg, job["id"])["error"] == "The job failed on the worker: KeyError: 'x'"


def test_a_lease_that_stops_beating_goes_back_in_line_and_gives_up_after_three_tries(cfg):
    lab_db(cfg)
    a, b = store.add_worker(cfg, "Horizon", NOW), store.add_worker(cfg, "Spare", NOW)
    job = offer(cfg, "worker.check", {}, ("lab",))
    known = set(registry())
    t = NOW
    store.beat(cfg, a["id"], {}, t)
    assert store.lease(cfg, a["id"], known, t)["id"] == job["id"]
    store.beat(cfg, b["id"], {}, t + timedelta(seconds=60))
    assert store.lease(cfg, b["id"], known, t + timedelta(seconds=60)) is None
    store.beat(cfg, a["id"], {"job_id": job["id"]}, t + timedelta(seconds=100))
    assert store.lease(cfg, b["id"], known, t + timedelta(seconds=200)) is None
    words = worker_api.describe(cfg, t + timedelta(seconds=230))["jobs"][0]
    assert words["where"] == "queue" and words["why"] == "Horizon went quiet while running it. It goes back in line when a worker checks in."
    store.beat(cfg, b["id"], {}, t + timedelta(seconds=230))
    taken = store.lease(cfg, b["id"], known, t + timedelta(seconds=230))
    assert taken["id"] == job["id"] and taken["attempts"] == 2 and taken["worker_id"] == b["id"]
    store.beat(cfg, a["id"], {}, t + timedelta(seconds=600))
    assert store.lease(cfg, a["id"], known, t + timedelta(seconds=600))["attempts"] == 3
    store.tidy(cfg, t + timedelta(seconds=900))
    failed = store.get(cfg, job["id"])
    assert failed["state"] == "failed" and failed["error"] == "It was started 3 times and the worker went quiet each time."


def test_the_same_request_is_queued_once_and_a_finished_one_is_not_repeated(cfg):
    lab_db(cfg)
    first = offer(cfg, "worker.check", {"a": 1}, ("lab",), key="k1")
    again = offer(cfg, "worker.check", {"a": 1}, ("lab",), key="k1")
    assert first["new"] is True and again["new"] is False and again["id"] == first["id"]
    assert offer(cfg, "worker.check", {"a": 2}, ("lab",), key="k2")["id"] != first["id"]
    worker = store.add_worker(cfg, "Horizon")
    store.beat(cfg, worker["id"], {})
    assert store.lease(cfg, worker["id"], set(registry()))["id"] == first["id"]
    store.result_path(cfg, first["id"]).parent.mkdir(parents=True, exist_ok=True)
    store.result_path(cfg, first["id"]).write_bytes(packed({"files": [{"name": "lab", "check": "ok", "tables": 1, "rows": 50}]}))
    assert store.returned(cfg, first["id"], True, 1.0, 10, None) == "returned" and apply(cfg)["saved"] == 1
    assert offer(cfg, "worker.check", {"a": 1}, ("lab",), key="k1")["state"] == "done"
    fresh = offer(cfg, "worker.check", {"a": 1}, ("lab",), key="k1", again=True)
    assert fresh["new"] is True and fresh["id"] != first["id"]


def test_a_job_whose_copy_or_kind_is_gone_fails_instead_of_blocking_the_line(cfg):
    lab_db(cfg)
    worker = store.add_worker(cfg, "Horizon")
    store.beat(cfg, worker["id"], {})
    lost = offer(cfg, "worker.check", {}, ("lab",))
    odd = store.enqueue(cfg, "old.kind", {}, lost["snapshots"])
    snapshots.path_of(cfg, lost["snapshots"][0]["sha256"]).unlink()
    assert store.lease(cfg, worker["id"], set(registry())) is None
    assert store.get(cfg, lost["id"])["error"] == "The database copy it was queued with is gone, so it can't be sent to a worker."
    assert store.get(cfg, odd["id"])["error"] == "This build of the desk doesn't know that kind of job any more."


def test_old_jobs_and_unused_copies_are_forgotten(cfg):
    lab_db(cfg)
    job = offer(cfg, "worker.check", {}, ("lab",))
    sha = job["snapshots"][0]["sha256"]
    assert store.returned(cfg, job["id"], False, 1.0, None, "boom", NOW) == "failed"
    lab_db(cfg, 3)
    snapshots.take(cfg, "lab")
    assert store.tidy(cfg, NOW + timedelta(days=1)) == {"forgotten": 0, "copies_removed": 1} and snapshots.path_of(cfg, sha) is None
    assert store.tidy(cfg, NOW + timedelta(days=8))["forgotten"] == 1 and store.get(cfg, job["id"]) is None


def test_the_apply_job_is_on_the_schedule(cfg):
    from desk.scheduler import package_jobs

    (job,) = package_jobs(["worker"])
    assert job.name == "worker-apply" and job.command[-4:] == ["python", "-m", "desk.worker", "apply"]


# ---- The worker itself ----


def slow(inputs: dict, files: dict) -> dict:
    conn = sqlite3.connect(f"file:{files['lab']}?mode=ro", uri=True)
    return {"rows": conn.execute("SELECT count(*) FROM bars").fetchone()[0], "asked": inputs}


def test_the_worker_loop_fetches_code_and_a_copy_runs_the_job_and_sends_the_result(live, cfg, tmp_path):
    lab_db(cfg)
    made = store.add_worker(cfg, "Horizon")
    job = offer(cfg, "worker.check", {}, ("lab",))
    work = tmp_path / "work"
    assert loop(live, made["key"], work, rounds=2, idle=0.05) == 0
    back = store.get(cfg, job["id"])
    assert back["state"] == "returned" and back["seconds"] is not None and back["peak_mb"] > 5
    assert json.loads(gzip.decompress(store.result_path(cfg, job["id"]).read_bytes())) == {"files": [{"name": "lab", "check": "ok", "tables": 1, "rows": 50}]}
    assert apply(cfg)["saved"] == 1 and store.get(cfg, job["id"])["state"] == "done"
    (code,) = (work / "code").iterdir()
    assert (code / "desk" / "worker" / "kinds.py").is_file()
    (copy,) = (work / "snapshots").iterdir()
    assert copy.name == job["snapshots"][0]["sha256"] + ".db" and copy.stat().st_mode & 0o222 == 0
    assert list((work / "jobs").iterdir()) == [] and store.workers(cfg)[0]["state"] == "online"
    second = offer(cfg, "worker.check", {}, ("lab",))
    assert loop(live, made["key"], work, rounds=1, idle=0.05) == 0 and store.get(cfg, second["id"])["state"] == "returned"
    assert len(list((work / "code").iterdir())) == 1 and len(list((work / "snapshots").iterdir())) == 1


def test_a_job_that_raises_on_the_worker_comes_back_as_a_plain_failure(live, cfg, tmp_path, monkeypatch):
    lab_db(cfg)
    made = store.add_worker(cfg, "Horizon")
    job = store.enqueue(cfg, "worker.check", {}, [{"name": "lab", "sha256": snapshots.take(cfg, "lab")["sha256"], "bytes": 1}])
    packed_copy = snapshots.path_of(cfg, job["snapshots"][0]["sha256"])
    packed_copy.write_bytes(gzip.compress(b"this is not a database"))
    assert loop(live, made["key"], tmp_path / "work", rounds=1, idle=0.05) == 0
    failed = store.get(cfg, job["id"])
    assert failed["state"] == "failed" and failed["error"].startswith(
        "The worker couldn't fetch what the job needs: The database copy didn't match its fingerprint"
    )


def test_the_worker_command_runs_end_to_end_and_keeps_its_key_out_of_the_job(live, cfg, tmp_path):
    lab_db(cfg)
    made = store.add_worker(cfg, "Horizon")
    job = offer(cfg, "worker.check", {}, ("lab",))
    work = tmp_path / "work"
    env = os.environ | {"DESK_URL": live, "DESK_WORKER_KEY": made["key"], "DESK_WORKER_DIR": str(work), "DESK_WORKER_INSECURE": "1", "DESK_BUILD": "abc1234"}
    proc = subprocess.Popen([sys.executable, "-m", "desk.worker"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(150):
            if store.get(cfg, job["id"])["state"] != "queued" and store.get(cfg, job["id"])["state"] != "leased":
                break
            time.sleep(0.1)
    finally:
        proc.terminate()
        out = proc.communicate(timeout=10)[0]
    assert store.get(cfg, job["id"])["state"] == "returned", out
    assert (work / "key").read_text().strip() == made["key"] and (work / "key").stat().st_mode & 0o777 == 0o600
    assert made["key"] not in out and "job " + job["id"] + " done" in out
    assert store.workers(cfg)[0]["build"] == "abc1234"
    refused = subprocess.run(
        [sys.executable, "-m", "desk.worker"],
        env=os.environ | {"DESK_URL": "http://desk.example", "DESK_WORKER_DIR": str(work)},
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 2 and "https://" in refused.stderr
    empty = subprocess.run([sys.executable, "-m", "desk.worker"], env=os.environ | {"DESK_WORKER_DIR": str(tmp_path / "none")}, capture_output=True, text=True)
    assert empty.returncode == 2 and "DESK_WORKER_KEY" in empty.stderr


def test_a_package_can_add_its_own_kind_through_the_seam(cfg, monkeypatch):
    kind = Kind("demo.count", "Count rows", slow, lambda cfg, job, path: "counted")
    monkeypatch.setattr("desk.worker.kinds.KINDS", [kind])
    assert set(registry()) == {"demo.count"} and registry()["demo.count"].title == "Count rows"


# ---- The one-time start on the other machine ----


def test_the_worker_compose_holds_no_secrets_and_publishes_nothing():
    import yaml

    root = Path(__file__).resolve().parents[2]
    text = (root / "deploy" / "worker" / "compose.yaml").read_text()
    (service,) = yaml.safe_load(text)["services"].values()
    assert service["restart"] == "unless-stopped" and service["command"] == ["python", "-m", "desk.worker"]
    assert "ports" not in service and "env_file" not in service and "privileged" not in service and service["read_only"] is True
    assert service["volumes"] == ["work:/work"] and service["cap_drop"] == ["ALL"]
    assert service["environment"]["DESK_URL"] == "${DESK_URL:-https://desk-lan.escape-vektor.com}"
    assert service["environment"]["DESK_WORKER_KEY"] == "${DESK_WORKER_KEY:-}" and "dwk_..." in text
    assert set(service["environment"]) == {"DESK_URL", "DESK_WORKER_KEY", "DESK_WORKER_DIR", "DESK_LAB_WORKERS", "HOME"}
    assert "chown 568:568 /work" in (root / "Dockerfile").read_text()

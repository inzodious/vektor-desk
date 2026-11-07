import json
from dataclasses import replace

from fastapi.testclient import TestClient

from desk.api.app import create_app
from desk.config import Config
from desk.db import connect, desk_conn
from desk.demo import build_demo_mirror
from desk.mirror.__main__ import main as mirror_main
from tests.conftest import DEMO_TODAY


def rows(conn, tbl):
    return [json.loads(r[0]) for r in conn.execute("SELECT json FROM rows WHERE tbl=?", (tbl,))]


def test_demo_mirror_has_every_table_with_history(demo_cfg):
    conn = connect(demo_cfg.mirror_db, readonly=True)
    tables = {r["tbl"]: r["rows"] for r in conn.execute("SELECT tbl, rows FROM tables")}
    assert set(tables) == {"activity", "positions", "snapshots", "transactions", "plans", "paystubs", "prices", "priceCloses", "priceProfiles"}
    assert tables["snapshots"] >= 100
    pulls = conn.execute("SELECT count(DISTINCT pulled_at) FROM row_history").fetchone()[0]
    assert pulls >= 100
    assert conn.execute("SELECT ok FROM runs ORDER BY id DESC").fetchone()[0] == 1


def test_latest_snapshot_adds_up(demo_cfg):
    conn = connect(demo_cfg.mirror_db, readonly=True)
    snap = max(rows(conn, "snapshots"), key=lambda s: s["asOf"])
    assert snap["asOf"].startswith(DEMO_TODAY.isoformat())
    held = [p for p in rows(conn, "positions") if p["snapshotId"] == snap["id"]]
    assert round(sum(p["value"] for p in held), 2) == snap["total"]
    for a in snap["accounts"]:
        assert round(sum(p["value"] for p in held if p["accountKey"] == a["key"]), 2) == a["value"]
    assert {p["symbol"] for p in held} >= {"FXAIX", "FTEC", "VXUS", "BND", "ACME"}


def test_activity_covers_the_kinds_the_desk_needs(demo_cfg):
    conn = connect(demo_cfg.mirror_db, readonly=True)
    kinds = {a["kind"] for a in rows(conn, "activity")}
    assert {"deposit", "buy", "sell", "dividend", "reinvest"} <= kinds
    sells = [a for a in rows(conn, "activity") if a["kind"] == "sell"]
    assert sells[0]["symbol"] == "ACME" and sells[0]["quantity"] < 0 < sells[0]["amount"]


def test_prices_and_plan_shapes(demo_cfg):
    conn = connect(demo_cfg.mirror_db, readonly=True)
    (board,) = rows(conn, "prices")
    assert set(board["quotes"]) == {"FXAIX", "FTEC", "VXUS", "BND", "ACME"}
    closes = rows(conn, "priceCloses")
    assert all(c["rows"][0][0].startswith(str(c["year"])) for c in closes)
    (plan,) = rows(conn, "plans")
    assert round(sum(f["target_weight"] for f in plan["plan"]["funds"]), 6) == 1


def test_same_seed_same_world(tmp_path):
    a = build_demo_mirror(tmp_path / "a.db", today=DEMO_TODAY)
    b = build_demo_mirror(tmp_path / "b.db", today=DEMO_TODAY)
    q = "SELECT tbl, id, json FROM rows ORDER BY tbl, id"
    assert connect(a, readonly=True).execute(q).fetchall() == connect(b, readonly=True).execute(q).fetchall()


def test_engine_style_read_through_desk_conn(demo_cfg):
    conn = desk_conn(demo_cfg)
    n = conn.execute("SELECT count(*) FROM mirror.ev_positions").fetchone()[0]
    assert n > 900


def test_demo_mode_serves_the_synthetic_mirror(tmp_path, monkeypatch):
    monkeypatch.setenv("DESK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DESK_DEMO", "1")
    cfg = Config.from_env()
    assert cfg.demo and cfg.data_dir == tmp_path / "demo"
    with TestClient(create_app(cfg, packages=[])) as client:
        assert client.get("/api/health").json()["demo"] is True
        held = client.get("/api/positions").json()
        assert held["asOf"] and held["positions"]
    assert mirror_main([]) == 0
    assert not (tmp_path / "mirror.db").exists()


def test_demo_flag_off_by_default(cfg):
    assert replace(cfg).demo is False
    assert Config.from_env({}).demo is False

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from desk.db import apply_schemas
from desk.decisions import approve, confirm_fills, create_proposal, get, mark_placed, unmatched, upcoming_deposits
from desk.decisions.plan import deposit_series

NOW = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
IND = "individual-0100"


@pytest.fixture
def broker(cfg):
    apply_schemas(cfg, only=["engine"])
    conn = sqlite3.connect(cfg.desk_db)
    conn.execute(
        "INSERT INTO broker_files (id, sha256, name, imported_at, window_start, window_end, rows, added, cancelled, accounts) "
        "VALUES (1, 'x', 'h.json', ?, ?, ?, 0, 0, 0, ?)",
        ("2026-11-08T00:00:00Z", "2026-05-01", "2026-11-07", json.dumps(["X0100"])),
    )
    conn.commit()
    seq = [0]

    def add(day, kind, amount, *, symbol=None, quantity=None, price=None, description="Electronic Funds Transfer Received"):
        seq[0] += 1
        conn.execute(
            "INSERT INTO broker_txns (id, file_id, seq, last4, account, date, kind, symbol, quantity, price, amount, description) "
            "VALUES (?, 1, ?, '0100', ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"b{seq[0]}", seq[0], IND, day, kind, symbol, quantity, price, amount, description),
        )
        conn.commit()
        return f"broker:b{seq[0]}"

    yield add
    conn.close()


def test_deposits_read_broker_history_then_mirror_after_it(cfg, mirror, broker):
    for day in ("2026-06-03", "2026-07-03", "2026-08-03", "2026-09-03", "2026-10-05", "2026-11-03"):
        broker(day, "deposit", 3000)
    mirror("sync-twin", date="2026-11-04", accountKey=IND, kind="deposit", action="EFT RECEIVED", amount=3000, source="sync")
    mirror("after", date="2026-11-12", accountKey=IND, kind="deposit", action="EFT RECEIVED", amount=500, source="sync")
    mode, series = deposit_series(cfg, now=NOW)
    assert mode == "auto" and [(s["cadence"], s["amount_usd"], s["observed"]) for s in series] == [("monthly", 3000, 6)]
    landed = [(d["date"], d["amount_usd"], d["scheduled"]) for d in upcoming_deposits(cfg, days=0, now=NOW) if d["status"] == "landed"]
    assert landed == [("2026-11-12", 500.0, False)]


def test_fills_prefer_broker_quantity_and_price(cfg, preflight, mirror, broker, proposal):
    now = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
    d = create_proposal(cfg, proposal(amount_usd=250, account="Individual"), "plan_keeper", now=now)
    approve(cfg, d["id"], now=now)
    mark_placed(cfg, d["id"], now=now)
    mirror("m-buy", date="2026-11-04", accountKey=IND, kind="buy", symbol="ABCD", amount=-250, source="sync")
    bid = broker("2026-11-04", "buy", -250, symbol="ABCD", quantity=10, price=25, description="YOU BOUGHT ABCD")
    assert confirm_fills(cfg, now=now) == [d["id"]]
    fill = get(cfg, d["id"])["fill"]
    assert fill["activity_id"] == bid and fill["shares"] == 10 and fill["price"] == 25


def test_a_trade_linked_before_the_import_is_not_unmatched_after(cfg, preflight, mirror, broker, proposal):
    now = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
    d = create_proposal(cfg, proposal(amount_usd=250, account="Individual"), "plan_keeper", now=now)
    approve(cfg, d["id"], now=now)
    mark_placed(cfg, d["id"], now=now)
    mirror("m-buy", date="2026-11-04", accountKey=IND, kind="buy", symbol="ABCD", amount=-250, source="sync")
    assert confirm_fills(cfg, now=now) == [d["id"]] and get(cfg, d["id"])["activity_id"] == "m-buy"
    broker("2026-11-04", "buy", -250, symbol="ABCD", quantity=10, price=25, description="YOU BOUGHT ABCD")
    broker("2026-11-05", "buy", -90, symbol="QRST", quantity=3, price=30, description="YOU BOUGHT QRST")
    assert [t["symbol"] for t in unmatched(cfg, now=now)] == ["QRST"]

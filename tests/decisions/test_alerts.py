import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from desk.decisions import alerts as alerting
from desk.decisions import approve, create_proposal, draft
from desk.decisions.alerts import item_priority, send_alerts
from desk.notify import recent

NOW = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


@pytest.fixture
def demo(cfg):
    return dataclasses.replace(cfg, demo=True)


@pytest.fixture
def captured(monkeypatch):
    sent = []

    def fake(topic, title, body="", priority="default", **kw):
        sent.append({"topic": topic, "title": title, "body": body, "priority": priority, **kw})
        return True

    monkeypatch.setattr(alerting, "publish", fake)
    return sent


def test_queue_items_go_out_with_priority(cfg, preflight, proposal, captured):
    plain = create_proposal(cfg, proposal(expires="2026-11-30"), "plan_keeper", now=NOW)
    preflight["result"]["value"] = {"status": "blocked", "lights": []}
    lit = create_proposal(cfg, proposal(funding="margin", expires="2026-11-30"), "research", now=NOW)
    draft(cfg, {"kind": "buy", "symbol": "ABCD", "amount_usd": 10, "thesis": "Mine"}, now=NOW)
    keys = send_alerts(cfg, now=NOW)
    assert set(keys) == {f"proposal-{plain['id']}", f"proposal-{lit['id']}"}
    by_key = {m["key"]: m for m in captured}
    assert by_key[f"proposal-{lit['id']}"]["priority"] == "high"
    assert by_key[f"proposal-{lit['id']}"]["body"].endswith("Preflight lit up.")
    assert by_key[f"proposal-{plain['id']}"]["priority"] == "default"
    assert by_key[f"proposal-{plain['id']}"]["topic"] == "research"
    assert by_key[f"proposal-{plain['id']}"]["click"] == f"/decisions?d={plain['id']}"


def test_min_priority_filters(cfg, preflight, proposal, captured):
    (cfg.data_dir / "desk.yaml").write_text("alerts:\n  min_priority: high\n")
    create_proposal(cfg, proposal(expires="2026-11-30"), "plan_keeper", now=NOW)
    tax = create_proposal(cfg, proposal(kind="harvest", expires="2026-11-30"), "tax", now=NOW)
    assert send_alerts(cfg, now=NOW) == [f"proposal-{tax['id']}"]


def test_item_priority(proposal):
    base = {"kind": "buy", "origin": "research", "preflight_status": "clear", "expires_at": "2026-11-30T21:00:00+00:00"}
    assert item_priority(base, NOW) == "default"
    assert item_priority({**base, "kind": "memo"}, NOW) == "low"
    assert item_priority({**base, "expires_at": (NOW + timedelta(hours=5)).isoformat()}, NOW) == "high"
    assert item_priority({**base, "origin": "risk"}, NOW) == "high"


def test_late_deposit_unmatched_trades_and_wash_clear(cfg, preflight, proposal, mirror, captured):
    (cfg.data_dir / "desk.yaml").write_text('deposits:\n  - {id: payday, account: brokerage, cadence: biweekly, anchor: "2026-11-06", amount_usd: 500}\n')
    mirror("t1", date="2026-11-19", accountKey="brokerage-9", kind="buy", symbol="ABCD", quantity=1, amount=-40)
    mirror("old", date="2026-11-01", accountKey="brokerage-9", kind="buy", symbol="ABCD", quantity=1, amount=-40)
    preflight["result"]["value"] = {"status": "clear", "lights": [], "tax": {"wash_clear_date": "2026-11-20"}}
    d = create_proposal(cfg, proposal(kind="harvest", expires="2026-11-30"), "tax", now=NOW - timedelta(days=31))
    approve(cfg, d["id"], now=NOW - timedelta(days=31))
    keys = send_alerts(cfg, now=NOW)
    assert "deposit-late-payday-2026-11-06" in keys
    assert "unmatched-t1" in keys and "unmatched-old" not in keys
    assert f"wash-{d['id']}-2026-11-20" in keys
    titles = {m["key"]: m["title"] for m in captured}
    assert titles["unmatched-t1"] == "Buy ABCD has no decision record"
    assert titles[f"wash-{d['id']}-2026-11-20"] == "ABCD wash-sale window clears today"


def test_many_unmatched_trades_batch(cfg, mirror, captured):
    for i in range(4):
        mirror(f"t{i}", date="2026-11-19", accountKey="brokerage-9", kind="buy", symbol="ABCD", quantity=1, amount=-40)
    keys = send_alerts(cfg, now=NOW)
    assert keys == ["unmatched-batch-t0,t1,t2,t3"]
    assert captured[0]["title"] == "4 trades have no decision record"


def test_real_publish_dedupes_across_runs(demo, preflight, proposal):
    d = create_proposal(demo, proposal(expires="2026-11-30"), "plan_keeper", now=NOW)
    assert send_alerts(demo, now=NOW) == [f"proposal-{d['id']}"]
    assert send_alerts(demo, now=NOW) == []
    log = recent(demo)
    assert len(log) == 1 and log[0]["status"] == "demo" and "$" not in log[0]["body"].replace("$…", "")

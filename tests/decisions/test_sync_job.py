from datetime import timedelta

from desk.decisions import approve, create_proposal, get, mark_placed, records
from desk.decisions.__main__ import main, sync


def test_sync_expires_reruns_and_confirms(cfg, mirror, monkeypatch, now, capsys, proposal):
    monkeypatch.setattr(records, "_checker", lambda: None)
    stale = create_proposal(cfg, proposal(expires="2026-11-01"), "tax", now=now - timedelta(days=10))
    waiting = create_proposal(cfg, proposal(expires="2099-01-01"), "plan_keeper")
    placed = create_proposal(cfg, proposal(expires="2099-01-01"), "plan_keeper")
    approve(cfg, placed["id"])
    mark_placed(cfg, placed["id"])
    day = placed["created_at"][:10]
    mirror("fill", date=day, accountKey="brokerage-9", kind="buy", symbol="ABCD", quantity=10, amount=-500)
    monkeypatch.setattr(records, "_checker", lambda: lambda c, t, ticket_id: {"status": "clear", "lights": []})
    monkeypatch.setattr("desk.decisions.__main__.Config.from_env", lambda: cfg)
    result = sync(cfg)
    assert result["expired"] == 1 and result["preflight_rerun"] == 1 and result["filled"] == 1
    assert get(cfg, stale["id"])["status"] == "expired"
    assert get(cfg, waiting["id"])["preflight_status"] == "clear"
    assert get(cfg, placed["id"])["status"] == "filled"
    assert main(["sync"]) == 0
    assert '"expired": 0' in capsys.readouterr().out

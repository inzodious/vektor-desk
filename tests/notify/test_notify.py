import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
import requests

from desk import notify
from desk.notify import publish, recent, set_enabled
from desk.notify.__main__ import main
from desk.notify.ops import ops_check
from tests.fakes import Res
from tests.infra.test_ops import mirrored


class FakeNtfy:
    def __init__(self, status=200, error=None):
        self.status = status
        self.error = error
        self.sent = []

    def post(self, url, json=None, timeout=None):
        if self.error:
            raise self.error
        self.sent.append((url, json))
        return Res(self.status, {})


@pytest.fixture
def on(cfg):
    return dataclasses.replace(cfg, ntfy_url="http://ntfy")


def test_publish_sends_a_clean_message(on):
    ntfy = FakeNtfy()
    title, body = "Rule breach: trim $1,250.40", "Cash under $500 floor, down -$3.2k"
    assert publish("alerts", title, body, "high", tags=["warning", "Bad Tag"], click="/decisions/abc", cfg=on, session=ntfy)
    url, msg = ntfy.sent[0]
    assert url == "http://ntfy/"
    assert msg == {
        "topic": "desk-alerts",
        "title": "Rule breach: trim $…",
        "message": "Cash under $… floor, down $…",
        "priority": 4,
        "tags": ["warning"],
        "click": "https://desk.escape-vektor.com/decisions/abc",
    }
    assert recent(on)[0]["status"] == "sent"


def test_long_text_and_foreign_links_are_cut(on):
    ntfy = FakeNtfy()
    publish("research", "x" * 200, "y " * 400, click="https://example.com/phish", cfg=on, session=ntfy)
    msg = ntfy.sent[0][1]
    assert len(msg["title"]) == notify.TITLE_MAX and msg["title"].endswith("…")
    assert len(msg["message"]) <= notify.BODY_MAX
    assert "click" not in msg


def test_bad_topic_or_priority_is_a_programming_error(on):
    with pytest.raises(ValueError):
        publish("trades", "x", cfg=on, session=FakeNtfy())
    with pytest.raises(ValueError):
        publish("alerts", "x", priority="max", cfg=on, session=FakeNtfy())


def test_delivery_failures_never_raise(on):
    assert not publish("ops", "Down", cfg=on, session=FakeNtfy(error=requests.ConnectionError("refused")))
    assert not publish("ops", "Down", cfg=on, session=FakeNtfy(status=500))
    rows = recent(on)
    assert [r["status"] for r in rows] == ["failed", "failed"]
    assert "500" in rows[0]["error"] and "refused" in rows[1]["error"]


def test_off_demo_and_muted_send_nothing(cfg, on):
    ntfy = FakeNtfy()
    assert not publish("ops", "No server", cfg=cfg, session=ntfy)
    assert publish("ops", "Demo", cfg=dataclasses.replace(on, demo=True), session=ntfy)
    set_enabled(on, "research", False)
    assert not publish("research", "Muted", cfg=on, session=ntfy)
    assert ntfy.sent == []
    assert [r["status"] for r in recent(on)] == ["muted", "demo", "off"]
    set_enabled(on, "research", True)
    assert publish("research", "Back", cfg=on, session=ntfy)


def test_key_dedupes_but_failures_retry(on):
    assert not publish("alerts", "Wash-sale window", key="wash-FTEC", cfg=on, session=FakeNtfy(status=502))
    ntfy = FakeNtfy()
    assert publish("alerts", "Wash-sale window", key="wash-FTEC", cfg=on, session=ntfy)
    assert not publish("alerts", "Wash-sale window", key="wash-FTEC", cfg=on, session=ntfy)
    assert len(ntfy.sent) == 1
    assert publish("alerts", "Wash-sale window", key="wash-FTEC", dedupe_hours=0, cfg=on, session=ntfy)


def test_ops_check_alerts_once_per_day(on):
    ntfy = FakeNtfy()
    assert ops_check(on, session=ntfy) == []
    mirrored(on)
    assert ops_check(on, session=ntfy) == []
    later = datetime.now(UTC) + timedelta(hours=20)
    assert ops_check(on, now=later, session=ntfy) == ["mirror-stale"]
    assert ops_check(on, now=later, session=ntfy) == []
    assert ntfy.sent[0][1]["title"] == "Mirror is stale" and ntfy.sent[0][1]["priority"] == 4


def test_ops_check_token_renewal_weekly(on):
    soon = dataclasses.replace(on, claude_token_expires=(datetime.now(UTC) + timedelta(days=12)).date().isoformat())
    mirrored(soon)
    ntfy = FakeNtfy()
    assert ops_check(soon, session=ntfy) == ["token-renew"]
    assert ops_check(soon, session=ntfy) == []
    assert "days left" in ntfy.sent[0][1]["message"]
    assert ops_check(dataclasses.replace(soon, demo=True), session=ntfy) == []


def test_api_topics_switch_and_recent(app_client, on):
    client = app_client(packages=["notify"], config=on)
    topics = client.get("/api/notify/topics").json()
    assert topics["on"] is True
    assert [t["subscribe"] for t in topics["topics"]][0] == "https://desk.escape-vektor.com:8443/desk-alerts"
    assert client.put("/api/notify/topics/ops", json={"enabled": False}).json() == {"topic": "ops", "enabled": False}
    assert client.put("/api/notify/topics/nope", json={"enabled": False}).status_code == 404
    assert {t["topic"]: t["enabled"] for t in client.get("/api/notify/topics").json()["topics"]}["ops"] is False
    publish("alerts", "Hello", cfg=on, session=FakeNtfy())
    assert client.get("/api/notify/recent").json()["alerts"][0]["title"] == "Hello"


def test_cli_send_and_test_without_a_server(cfg, monkeypatch, capsys):
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    monkeypatch.delenv("DESK_NTFY_URL", raising=False)
    monkeypatch.delenv("DESK_DEMO", raising=False)
    assert main(["send", "ops", "Backup failed", "See deploy.log", "--priority", "high"]) == 1
    assert main(["test", "ops"]) == 1
    assert main(["topics"]) == 0
    out = capsys.readouterr().out
    assert "ops: off, DESK_NTFY_URL is empty" in out
    assert "https://desk.escape-vektor.com:8443/desk-ops" in out

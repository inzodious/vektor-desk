import json
import sqlite3
from datetime import UTC, datetime

import pytest

from desk.decisions import records
from desk.mirror.store import SCHEMA as MIRROR_SCHEMA

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


@pytest.fixture
def now():
    return NOW


@pytest.fixture(autouse=True)
def profile_env(cfg, monkeypatch):
    monkeypatch.setenv("DESK_PROFILE", str(cfg.data_dir / "desk.yaml"))


@pytest.fixture
def mirror(cfg):
    conn = sqlite3.connect(cfg.mirror_db)
    conn.executescript(MIRROR_SCHEMA)

    def add(rid, **row):
        body = json.dumps({"key": rid, **row})
        conn.execute("INSERT OR REPLACE INTO rows (tbl, id, json, at) VALUES ('activity', ?, ?, ?)", (rid, body, "2026-11-10T00:00:00Z"))
        conn.commit()

    yield add
    conn.close()


@pytest.fixture
def preflight(monkeypatch):
    calls = []
    result = {"value": {"status": "clear", "lights": [{"check": "Funding", "status": "ok"}]}}

    def check_trade(cfg, trade, ticket_id):
        calls.append((trade, ticket_id))
        value = result["value"]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(records, "_checker", lambda: check_trade)
    return {"calls": calls, "result": result}


def make_proposal(**over):
    base = {
        "kind": "buy",
        "symbol": "abcd",
        "account": "Brokerage",
        "amount_usd": 500,
        "funding": "cash",
        "thesis": "Made-up thesis for a test.",
        "bear_case": "Made-up bear case.",
        "rule_served": "drift-max",
        "invalidation": "Price below 10",
        "horizon": "90 days",
        "numbers_used": [{"field": "plan.drift:ABCD:now", "value": -3.1}],
        "sources": [{"url": "https://example.com/a", "title": "A", "primary": True}, {"url": "https://example.com/b", "title": "B"}],
        "confidence": 0.6,
        "order_ticket": {"action": "buy", "symbol": "ABCD", "order_type": "market", "account": "Brokerage"},
    }
    base.update(over)
    return base


@pytest.fixture
def proposal():
    return make_proposal

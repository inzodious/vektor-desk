import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse

import pytest

from desk.db import connect
from desk.engine import lane, paper_exec, schema
from desk.engine.market import trading_day

SESSIONS = [d for d in (date(2026, 9, 28) + timedelta(days=i) for i in range(40)) if trading_day(d)]
PRE = datetime(2026, 11, 6, 13, 0, tzinfo=UTC)
AFTER = datetime(2026, 11, 6, 22, 0, tzinfo=UTC)


def seed(cfg, signals):
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    rows = []
    for i, d in enumerate(SESSIONS):
        for sym, base, step in (("SMOL", 10.0, 0.1), ("MIDZ", 20.0, -0.05), ("IWM", 200.0, 0.2)):
            px = base + step * i
            rows.append((sym, d.isoformat(), px, px, px, px, px * 0.5, 100000, px))
    with conn:
        conn.executemany("INSERT INTO alpaca_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        for acc, sym, direction, conf, scored in signals:
            conn.execute(
                "INSERT INTO filing_signals VALUES (?, ?, ?, '8-K', '[]', ?, 'claude-test', ?, ?, 'earnings', 20, 'r', '[]', 'run')",
                (acc, sym, scored, scored, direction, conf),
            )
    return conn


SIGNALS = [
    ("a1", "SMOL", 2, 0.8, "2026-10-05T08:15:00+00:00"),
    ("a2", "MIDZ", 1, 0.5, "2026-10-05T08:15:00+00:00"),
    ("a3", "MIDZ", -1, 0.9, "2026-10-06T08:15:00+00:00"),
    ("a4", "MIDZ", 1, 0.9, "2026-11-06T09:15:00+00:00"),
]


def test_entry_is_the_next_open_after_scoring():
    assert lane.entry_session(datetime(2026, 11, 6, 9, 15, tzinfo=UTC)) == date(2026, 11, 6)
    assert lane.entry_session(datetime(2026, 11, 6, 15, 0, tzinfo=UTC)) == date(2026, 11, 9)
    assert lane.entry_session(datetime(2026, 11, 7, 9, 0, tzinfo=UTC)) == date(2026, 11, 9)
    assert lane.add_sessions(date(2026, 10, 5), 20) == date(2026, 11, 2)


def test_forward_record_follows_the_rule(cfg):
    conn = seed(cfg, SIGNALS)
    result = lane.rebuild(conn)
    assert result["status"] == "paper" and result["start"] == "2026-10-05"
    trades = [dict(r) for r in conn.execute("SELECT * FROM paper_trades WHERE strategy_id='filings-lane' ORDER BY date, side")]
    assert [(t["date"], t["symbol"], t["side"]) for t in trades] == [
        ("2026-10-05", "SMOL", "buy"),
        ("2026-11-02", "SMOL", "sell"),
        ("2026-11-06", "MIDZ", "buy"),
    ]
    assert trades[0]["cost"] == 100.0
    row = dict(conn.execute("SELECT * FROM paper_portfolios WHERE strategy_id='filings-lane'").fetchone())
    summary = json.loads(row["summary"])
    assert summary["forward_only"] and summary["benchmark"] == "IWM" and summary["closed"] == 1 and summary["hit_rate"] == 1.0
    assert row["return_pct"] > 0 and row["days"] == 32
    held = [dict(r) for r in conn.execute("SELECT * FROM paper_positions WHERE strategy_id='filings-lane'")]
    assert [h["symbol"] for h in held] == ["MIDZ"]
    conn.close()


def test_nothing_starts_before_the_first_score(cfg):
    conn = seed(cfg, [])
    assert lane.rebuild(conn)["status"] == "not_started"
    conn.close()


def test_ten_slots_and_one_position_per_name(cfg):
    sigs = [(f"s{i}", f"N{i:02d}", 1, 0.7 + i / 100, "2026-10-05T08:15:00+00:00") for i in range(12)] + [("dup", "N11", 2, 0.99, "2026-10-06T08:15:00+00:00")]
    conn = seed(cfg, sigs)
    picked = lane.plan(lane.signals(conn), date(2026, 10, 30))
    assert len(picked) == 10 and "N00" not in {t.symbol for t in picked} and "N01" not in {t.symbol for t in picked}
    assert sum(1 for t in picked if t.symbol == "N11") == 1
    conn.close()


class Res:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeAlpaca:
    def __init__(self, account="PA0000001", positions=None, reject=(), fill=1.0):
        self.account = account
        self.held = positions or {}
        self.reject = set(reject)
        self.fill = fill
        self.sent: list[dict] = []
        self.urls: list[str] = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.urls.append(url)
        path = urlparse(url).path
        if path == "/v2/account":
            return Res(200, {"account_number": self.account, "status": "ACTIVE"})
        if path == "/v2/positions":
            return Res(200, [{"symbol": s, "qty": str(q)} for s, q in self.held.items()])
        if path == "/v2/orders":
            return Res(
                200,
                [
                    {
                        "id": f"id-{o['client_order_id']}",
                        "client_order_id": o["client_order_id"],
                        "status": "filled" if self.fill == 1.0 else "partially_filled",
                        "filled_qty": str(float(o["qty"]) * self.fill),
                        "filled_avg_price": "19.0",
                        "filled_at": "2026-11-06T14:30:01Z",
                    }
                    for o in self.sent
                ],
            )
        return Res(404, {})

    def post(self, url, headers=None, json=None, timeout=None):
        self.urls.append(url)
        if json["symbol"] in self.reject:
            return Res(422, {"message": "asset not found"})
        if any(o["client_order_id"] == json["client_order_id"] for o in self.sent):
            return Res(422, {"message": "client_order_id must be unique"})
        self.sent.append(json)
        return Res(200, {"id": f"id-{json['client_order_id']}", "status": "accepted"})


@pytest.fixture
def paper_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "paper-id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "paper-secret")
    for k in ("ALPACA_BASE_URL", "DESK_PAPER_EXECUTE", "DESK_PAPER_BUDGET", "DESK_PAPER_MAX_STRATEGIES"):
        monkeypatch.delenv(k, raising=False)


def last_close(i_step):
    base, step = i_step
    return base + step * (len(SESSIONS) - 1)


def held_leg(conn, strategy_id, symbol, qty, px, day="2026-10-05", version=1):
    with conn:
        conn.execute(
            "INSERT INTO paper_legs (date, strategy_id, version, symbol, qty, filled_qty, price, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'filled')",
            (day, strategy_id, version, symbol, qty, qty, px),
        )


def lab_strategy(conn, strategy_id, positions, status="paper", started="2026-10-01", excess=1.0, days=36):
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO paper_portfolios VALUES (?, 1, ?, ?, '2026-11-05', ?, 1000.0, 2.0, ?, ?, ?)",
            (strategy_id, f"{strategy_id} title", started, days, excess, status, json.dumps({"mdd_pct": -3.5})),
        )
        conn.executemany("INSERT INTO paper_positions VALUES (?, 1, '2026-11-05', ?, ?, ?)", [(strategy_id, s, n, v) for s, n, v in positions])


def book(conn, strategy_id):
    return paper_exec.books(conn, 1000.0)[(strategy_id, 1)]


# ---- Executor ----


def test_executor_buys_targets_before_the_open_once(cfg, paper_keys):
    conn = seed(cfg, SIGNALS)
    web = FakeAlpaca()
    result = paper_exec.run(conn, web, now=PRE)
    assert result["ok"] and result["session"] == "pre"
    qty = int(100 // last_close((20.0, -0.05)))
    assert [(o["symbol"], o["side"], o["qty"]) for o in web.sent] == [("MIDZ", "buy", str(qty))] and web.sent[0]["time_in_force"] == "day"
    again = paper_exec.run(conn, web, now=PRE)
    assert not again["orders"] and "already placed" in again["note"] and len(web.sent) == 1
    row = dict(conn.execute("SELECT * FROM paper_orders").fetchone())
    assert row["status"] == "filled" and row["filled_avg_price"] == 19.0 and row["client_order_id"] == "vd-2026-11-06-MIDZ-buy"
    b = book(conn, "filings-lane")
    assert b.held == {"MIDZ": qty} and b.cash == pytest.approx(1000 - qty * 19.0)
    ledger = dict(conn.execute("SELECT * FROM paper_ledger_daily WHERE strategy_id='filings-lane'").fetchone())
    assert ledger["date"] == "2026-11-06" and ledger["cash"] == pytest.approx(1000 - qty * 19.0)
    assert {urlparse(u).hostname for u in web.urls} == {"paper-api.alpaca.markets"}
    conn.close()


def test_executor_sells_only_its_own_exits(cfg, paper_keys):
    conn = seed(cfg, SIGNALS)
    lane.rebuild(conn)
    held_leg(conn, "filings-lane", "SMOL", 9, 10.0)
    web = FakeAlpaca(positions={"SMOL": 9, "AAPL": 3, "MIDZ": 4})
    paper_exec.run(conn, web, now=PRE)
    assert {(o["symbol"], o["side"]) for o in web.sent} == {("SMOL", "sell"), ("MIDZ", "buy")}
    assert next(o for o in web.sent if o["symbol"] == "SMOL")["qty"] == "9"
    assert book(conn, "filings-lane").held.get("SMOL") is None
    conn.close()


def test_strategies_net_into_one_order_per_symbol(cfg, paper_keys):
    conn = seed(cfg, SIGNALS)
    lane.rebuild(conn)
    held_leg(conn, "filings-lane", "SMOL", 9, 10.0)
    smol = last_close((10.0, 0.1))
    lab_strategy(conn, "sector-momentum", [("SMOL", 50.0, 1000.0)])
    web = FakeAlpaca(positions={"SMOL": 9})
    paper_exec.run(conn, web, now=PRE)
    want = int(1000 / 1.02 // smol)
    smol_orders = [o for o in web.sent if o["symbol"] == "SMOL"]
    assert smol_orders == [smol_orders[0]] and smol_orders[0]["side"] == "buy" and smol_orders[0]["qty"] == str(want - 9)
    assert book(conn, "filings-lane").held.get("SMOL") is None
    lab = book(conn, "sector-momentum")
    assert lab.held == {"SMOL": want} and lab.cash == pytest.approx(1000 - want * 19.0)
    conn.close()


def test_partial_fills_split_pro_rata(cfg):
    conn = seed(cfg, [])
    with conn:
        conn.execute(
            "INSERT INTO paper_orders (client_order_id, date, symbol, side, qty, status, filled_qty, filled_avg_price, submitted_at, updated_at) "
            "VALUES ('vd-2026-11-06-SMOL-buy', '2026-11-06', 'SMOL', 'buy', 8, 'canceled', 4, 12.0, 'x', 'x')"
        )
        conn.executemany(
            "INSERT INTO paper_legs (date, strategy_id, version, symbol, qty, status) VALUES ('2026-11-06', ?, 1, 'SMOL', ?, 'planned')",
            [("a", 6.0), ("b", 4.0), ("c", -2.0)],
        )
    paper_exec.allocate(conn)
    got = {r["strategy_id"]: (r["filled_qty"], r["price"]) for r in conn.execute("SELECT * FROM paper_legs")}
    assert got == {"a": (3.6, 12.0), "b": (2.4, 12.0), "c": (-2.0, 12.0)}
    conn.close()


def test_a_crossed_symbol_waits_for_the_days_open(cfg):
    conn = seed(cfg, [])
    with conn:
        conn.executemany(
            "INSERT INTO paper_legs (date, strategy_id, version, symbol, qty, status) VALUES (?, ?, 1, 'SMOL', ?, 'planned')",
            [("2026-11-09", "a", 5.0), ("2026-11-09", "b", -5.0), ("2026-11-06", "a", 2.0), ("2026-11-06", "b", -2.0)],
        )
    paper_exec.allocate(conn)
    got = {(r["date"], r["strategy_id"]): (r["filled_qty"], r["status"]) for r in conn.execute("SELECT * FROM paper_legs")}
    assert got[("2026-11-09", "a")] == (None, "waiting") and got[("2026-11-06", "a")] == (2.0, "crossed") and got[("2026-11-06", "b")] == (-2.0, "crossed")
    conn.close()


def test_a_rejected_order_leaves_the_book_alone(cfg, paper_keys):
    conn = seed(cfg, SIGNALS)
    web = FakeAlpaca(reject={"MIDZ"})
    result = paper_exec.run(conn, web, now=PRE)
    assert result["orders"][0]["status"] == "rejected" and result["orders"][0]["message"] == "asset not found"
    b = book(conn, "filings-lane")
    assert b.held == {} and b.cash == 1000.0
    conn.close()


def test_retired_strategies_flatten_and_untradable_names_are_skipped(cfg, paper_keys):
    conn = seed(cfg, SIGNALS)
    lab_strategy(conn, "old-idea", [], status="retired")
    held_leg(conn, "old-idea", "SMOL", 7, 10.0)
    lab_strategy(conn, "fund-mix", [("FXAIX", 5.0, 1000.0)])
    with conn:
        conn.execute("INSERT INTO alpaca_assets VALUES ('SMOL', 'Smol', 'NASDAQ', 1, 'x')")
    web = FakeAlpaca(positions={"SMOL": 7})
    result = paper_exec.run(conn, web, now=PRE)
    assert ("SMOL", "sell", "7") in {(o["symbol"], o["side"], o["qty"]) for o in web.sent}
    assert not any(o["symbol"] == "FXAIX" for o in web.sent) and result["plan"]["skipped"]["fund-mix@1"] == ["FXAIX"]
    conn.close()


def test_after_the_open_it_only_reconciles(cfg, paper_keys):
    conn = seed(cfg, SIGNALS)
    web = FakeAlpaca()
    result = paper_exec.run(conn, web, now=AFTER)
    assert result["ok"] and not web.sent and result["session"] == "after"
    conn.close()


def test_a_live_url_or_account_is_refused(cfg, paper_keys, monkeypatch):
    conn = seed(cfg, SIGNALS)
    web = FakeAlpaca()
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    result = paper_exec.run(conn, web, now=PRE)
    assert not result["ok"] and "paper" in result["error"] and not web.urls
    monkeypatch.delenv("ALPACA_BASE_URL")
    live = FakeAlpaca(account="123456789")
    result = paper_exec.run(conn, live, now=PRE)
    assert not result["ok"] and "paper account" in result["error"] and not live.sent
    conn.close()


def test_kill_switch_and_budget_cap(cfg, paper_keys, monkeypatch):
    conn = seed(cfg, SIGNALS)
    monkeypatch.setenv("DESK_PAPER_EXECUTE", "0")
    web = FakeAlpaca()
    result = paper_exec.run(conn, web, now=PRE)
    assert result["ok"] and not web.sent and "DESK_PAPER_EXECUTE=0" in result["note"]
    monkeypatch.setenv("DESK_PAPER_BUDGET", "1000000")
    assert paper_exec.budget() == paper_exec.BUDGET_CAP
    conn.close()


def test_paper_job_is_scheduled():
    from desk.engine import __main__ as engine_main
    from desk.engine.jobs import JOBS

    assert "paper" in engine_main.JOBS
    assert sum(1 for _, c in JOBS if c == "python -m desk.engine paper") == 2


# ---- Lane variants ----


def test_variants_validate_and_start_when_registered(cfg):
    conn = seed(cfg, SIGNALS)
    with pytest.raises(ValueError, match="hold_sessions"):
        lane.register(conn, "fast-lane", "Fast", {"hold_sessions": 2})
    with pytest.raises(ValueError, match="event_types"):
        lane.register(conn, "fast-lane", "Fast", {"event_types": ["rumor"]})
    with pytest.raises(ValueError, match="same params"):
        lane.register(conn, "copy-lane", "Copy", {})
    with pytest.raises(ValueError, match="id must be"):
        lane.register(conn, "filings-lane", "Again", {"hold_sessions": 10})
    spec = lane.register(conn, "fast-lane", "Fast exits", {"hold_sessions": 10, "event_types": ["earnings"]}, now=datetime(2026, 10, 20, 12, tzinfo=UTC))
    assert spec.version == 1 and spec.registered_at.startswith("2026-10-20")
    out = lane.rebuild(conn)
    fast = out["variants"][0]
    assert fast["strategy_id"] == "fast-lane" and fast["start"] == "2026-10-20"
    trades = [(r["date"], r["symbol"]) for r in conn.execute("SELECT * FROM paper_trades WHERE strategy_id='fast-lane' AND side='buy'")]
    assert trades == [("2026-11-06", "MIDZ")]
    again = lane.register(conn, "fast-lane", "Fast exits", {"hold_sessions": 12}, now=datetime(2026, 10, 22, 12, tzinfo=UTC))
    assert again.version == 2 and [v.version for v in lane.variants(conn) if v.id == "fast-lane"] == [2]
    conn.close()
    from desk.engine import lab

    listed = {(r["id"], r["kind"]) for r in lab.strategies(cfg)}
    assert ("fast-lane", "lane") in listed and ("filings-lane", "lane") in listed


# ---- Leaderboard ----


def test_leaderboard_endpoint_and_register_helper(cfg, app_client):
    client = app_client(packages=["engine"])
    empty = client.get("/api/engine/lab/leaderboard").json()
    assert empty["rows"] == [] and empty["gate_days"] == 182 and empty["note"].startswith("No strategies")
    made = lane.register_variant(cfg, "earnings-lane", "Earnings only", {"event_types": ["earnings"]}, hypothesis="earnings filings move more")
    assert made["version"] == 1 and made["params"]["event_types"] == ["earnings"]


def test_leaderboard_orders_and_carries_the_account(cfg, paper_keys):
    from desk.engine import leaderboard

    assert leaderboard.build(None, 1000.0)["note"].startswith("No strategies are paper trading yet")
    conn = seed(cfg, SIGNALS)
    paper_exec.run(conn, FakeAlpaca(), now=PRE)
    lab_strategy(conn, "winner", [], status="eligible", excess=4.0, days=190)
    lab_strategy(conn, "loser", [], status="retired", excess=-2.0, days=190)
    lab_strategy(conn, "blank", [], excess=None)
    board = leaderboard.build(conn, 1000.0)
    assert board["benchmark"] == "IWM" and board["gate_days"] == 182 and board["note"] is None
    ids = [r["id"] for r in board["rows"]]
    assert ids[0] == "winner" and ids[-1] == "loser" and ids.index("filings-lane") < ids.index("blank")
    lane_row = next(r for r in board["rows"] if r["id"] == "filings-lane")
    assert lane_row["kind"] == "lane" and lane_row["waiting_on"] == "time" and lane_row["eligible_on"] == "2027-04-05"
    assert lane_row["account"]["sleeve"] == 1000.0 and lane_row["account"]["as_of"] == "2026-11-06" and lane_row["open_positions"] == 1
    assert next(r for r in board["rows"] if r["id"] == "winner")["max_drawdown_pct"] == -3.5
    conn.close()

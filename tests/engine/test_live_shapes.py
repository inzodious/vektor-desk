import hashlib
import json
from datetime import UTC, datetime

import pytest

from desk.db import connect
from desk.engine import __main__ as engine_main
from desk.engine import core, schema
from desk.engine.__main__ import run_holdings, run_market_backfill
from desk.engine.backfill import sync_roles
from desk.engine.core import guess_kind, symbol_kinds
from desk.engine.source import open_mirror
from tests.engine.helpers import closes_doc, position, snapshot
from tests.engine.test_market import FakeHttp, bar

K401 = "401k-0001"
HSA = "hsa-0002"
IND = "individual-0003"
THU, FRI, SAT = "2026-11-05", "2026-11-06", "2026-11-07"
SAT_NOW = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
HELD = [
    (K401, "P10001", 10.0, 500.0, False),
    (K401, "Q20002", 2.0, 150.0, False),
    (HSA, "ROKT", 20.0, 700.0, False),
    (HSA, "FXAIX", 2.0, 520.0, False),
    (HSA, "FDRXX", 150.0, 150.0, True),
    (IND, "ROKT", 100.0, 3500.0, False),
    (IND, "CHIP", 4.0, 2000.0, False),
    (IND, "SPY", 3.0, 2100.0, False),
    (IND, "SCHD", 50.0, 1500.0, False),
    (IND, "FTIHX", 40.0, 800.0, False),
    (IND, "SPAXX", 20.0, 20.0, True),
]
THURSDAY = {"ROKT": 30.0, "FXAIX": 250.0, "CHIP": 480.0, "SPY": 690.0, "SCHD": 29.5, "FTIHX": 19.5}


def seed_like_the_box(m):
    total = sum(v for *_, v, _ in HELD)
    m.put("snapshots", 1, snapshot(1, f"{FRI}T21:30", total, len(HELD)))
    for i, (acct, sym, qty, value, cash) in enumerate(HELD, start=1):
        m.put("positions", i, position(i, 1, acct, sym, qty, value, value * 0.9, cash=cash))
    for sym, px in THURSDAY.items():
        m.put("priceCloses", f"{sym}_2026", closes_doc(sym, 2026, [["2026-11-03", px, px], ["2026-11-04", px, px], [THU, px, px]]))
    m.put("plans", "p1", {"loadedAt": "2026-11-01T00:00:00Z", "plan": {"funds": [{"ticker": "FXAIX", "target_weight": 1.0}]}})
    m.pull(f"{SAT}T14:00:00+00:00")


def rows_on(cfg, day):
    conn = connect(cfg.desk_db, readonly=True)
    try:
        return {(r["account"], r["symbol"]): dict(r) for r in conn.execute("SELECT * FROM holdings_daily WHERE date=?", (day,))}
    finally:
        conn.close()


def health(cfg, mirror_builder=None, now=SAT_NOW):
    mirror = open_mirror(cfg)
    desk = connect(cfg.desk_db)
    try:
        out = core.compute(cfg, mirror, desk, now=now)
    finally:
        desk.close()
        mirror.close()
    return {c: (s, d) for _, c, s, d in out.health}


def add_bars(cfg, rows):
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    with desk:
        desk.executemany(
            "INSERT OR REPLACE INTO price_bars (symbol, date, open, high, low, close, adj_close, volume, div_cash, split_factor) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 1)",
            [(s, d, c, c, c, c, c) for s, d, c in rows],
        )
    desk.close()


# ---- Prices ----


def test_snapshot_day_uses_the_broker_price_when_closes_lag(cfg, mirror):
    seed_like_the_box(mirror)
    run_holdings(cfg)
    fri = rows_on(cfg, FRI)
    assert fri[(IND, "ROKT")]["close"] == pytest.approx(35.0) and fri[(IND, "ROKT")]["value"] == 3500.0
    assert all(abs(r["value"] - r["reported_value"]) < 0.01 for r in fri.values())
    assert fri[(K401, "P10001")]["close"] == pytest.approx(50.0) and fri[(K401, "P10001")]["quality"] == "pro_forma"
    checks = health(cfg)
    assert checks["value"][0] == "ok"


def test_official_bars_beat_the_mirror_and_fill_after_it(cfg, mirror):
    seed_like_the_box(mirror)
    run_holdings(cfg)
    add_bars(cfg, [("ROKT", THU, 30.5), ("ROKT", FRI, 35.5), ("CHIP", FRI, 500.0)])
    run_holdings(cfg)
    assert rows_on(cfg, FRI)[(IND, "ROKT")]["close"] == 35.5
    desk = connect(cfg.desk_db, readonly=True)
    assert desk.execute("SELECT count(*) FROM prices_daily WHERE symbol='ROKT' AND date=?", (THU,)).fetchone()[0] == 0
    desk.close()
    status, detail = health(cfg)["value"]
    assert status == "warn" and "ROKT 35.50 vs 35.00" in detail and "Fix:" in detail


def test_held_symbols_are_fetched_unless_the_mirror_has_the_last_session(cfg, mirror, monkeypatch):
    seed_like_the_box(mirror)
    run_holdings(cfg)
    desk = connect(cfg.desk_db)
    sync_roles(desk, SAT_NOW)
    held = {r[0] for r in desk.execute("SELECT symbol FROM market_symbols WHERE role='held'")}
    desk.close()
    assert {"ROKT", "CHIP", "FXAIX", "P10001", "Q20002"} <= held and "FDRXX" not in held
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    bars = {s: [bar(THU, px), bar(FRI, px * 1.1)] for s, px in THURSDAY.items()}
    monkeypatch.setattr("desk.engine.backfill.datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: SAT_NOW)}))
    result = run_market_backfill(cfg, FakeHttp(bars=bars))
    assert result["ok"] and {"P10001", "Q20002"} <= set(result["unpriced"]) and "ROKT" in result["fetched"]
    run_holdings(cfg)
    assert rows_on(cfg, FRI)[(IND, "ROKT")]["close"] == pytest.approx(33.0)
    status, detail = health(cfg)["closes"]
    assert status == "ok" and "P10001, Q20002" in detail and "snapshot price" in detail


def test_fresh_mirror_closes_skip_the_fetch(cfg, mirror):
    seed_like_the_box(mirror)
    mirror.put("priceCloses", "ROKT_2026", closes_doc("ROKT", 2026, [[THU, 30.0, 30.0], [FRI, 35.0, 35.0]]))
    mirror.pull(f"{SAT}T15:00:00+00:00")
    run_holdings(cfg)
    desk = connect(cfg.desk_db)
    sync_roles(desk, SAT_NOW)
    held = {r[0] for r in desk.execute("SELECT symbol FROM market_symbols WHERE role='held'")}
    desk.close()
    assert "ROKT" not in held and "CHIP" in held


# ---- Kinds ----


def test_kinds_from_sec_lists_benchmarks_and_ticker_shape(cfg, mirror):
    titles = {"CHIP": "Chipmaker Holdings Inc", "ROKT": "Rocket Radio Corp", "SCHD": "Schwab Strategic Trust", "ARKK": "ARK ETF Trust"}
    assert guess_kind("FTIHX", set(), titles) == "fund" and guess_kind("P10001", set(), titles) == "fund"
    assert guess_kind("SPY", set(), {}) == "fund" and guess_kind("SCHD", {"SCHD"}, titles) == "fund" and guess_kind("ARKK", set(), titles) == "fund"
    assert guess_kind("ROKT", set(), titles) == "stock" and guess_kind("ROKT", set(), {}) == "unknown"
    seed_like_the_box(mirror)
    run_holdings(cfg)
    desk = connect(cfg.desk_db)
    with desk:
        desk.executemany("INSERT INTO sec_tickers VALUES (?, 1, ?, 'x')", list(titles.items()))
        desk.execute("INSERT INTO sec_funds VALUES ('SCHD', 2, 'S1', 'C1', 'x')")
    mirror_conn = open_mirror(cfg)
    kinds = symbol_kinds(mirror_conn, {"FXAIX": 1.0}, desk)
    mirror_conn.close()
    desk.close()
    assert {s: kinds[s] for s in ("ROKT", "CHIP", "SPY", "SCHD", "FTIHX", "FXAIX", "P10001")} == {
        "ROKT": "stock",
        "CHIP": "stock",
        "SPY": "fund",
        "SCHD": "fund",
        "FTIHX": "fund",
        "FXAIX": "fund",
        "P10001": "fund",
    }
    assert "symbol_kinds" not in health(cfg)


# ---- Health ----


def test_every_problem_names_a_fix(cfg, mirror, monkeypatch):
    for key in ("TIINGO_API_KEY", "FINNHUB_API_KEY", "FRED_API_KEY", "DESK_SEC_USER_AGENT"):
        monkeypatch.delenv(key, raising=False)
    seed_like_the_box(mirror)
    run_holdings(cfg)
    checks = health(cfg)
    assert checks["market_keys"][0] == "warn" and "TIINGO_API_KEY" in checks["market_keys"][1]
    problems = {c: d for c, (s, d) in checks.items() if s != "ok"}
    assert problems and all("Fix:" in d for d in problems.values()), problems
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setenv("FRED_API_KEY", "k")
    monkeypatch.setenv("DESK_SEC_USER_AGENT", "Desk test@example.com")
    assert health(cfg)["market_keys"][0] == "ok"


# ---- Dry run ----


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def test_dry_run_writes_nothing_and_sends_nothing(cfg, mirror, monkeypatch, capsys):
    seed_like_the_box(mirror)
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    sent = []
    monkeypatch.setattr("desk.engine.triggers.publish", lambda *a, **kw: sent.append(a))
    assert engine_main.main(["daily", "--dry-run"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["dry_run"] and body["core"]["triggers"] == "skipped in a dry run" and not cfg.desk_db.exists()
    assert {h["check"] for h in body["health_detail"]} >= {"value", "closes", "market_keys"}
    run_holdings(cfg)
    before = digest(cfg.desk_db)
    assert engine_main.main(["daily", "--dry-run"]) == 0
    capsys.readouterr()
    assert digest(cfg.desk_db) == before and sent == []
    assert engine_main.main(["backfill", "--dry-run"]) == 2


# ---- Flows and moves ----


def seed_two_snapshots(m):
    thu = [(IND, "ROKT", 100.0, 3000.0, False), (IND, "SPAXX", 500.0, 500.0, True), (K401, "Q20002", 2.0, 150.0, False)]
    fri = [(IND, "ROKT", 200.0, 6060.0, False), (IND, "SPAXX", 1500.0, 1500.0, True), (K401, "Q20002", 2.5, 164.0, False)]
    pid = 0
    for sid, (stamp, rows) in enumerate(((f"{THU}T21:30", thu), (f"{FRI}T21:30", fri)), start=1):
        m.put("snapshots", sid, snapshot(sid, stamp, sum(r[3] for r in rows), len(rows)))
        for acct, sym, qty, value, cash in rows:
            pid += 1
            m.put("positions", pid, position(pid, sid, acct, sym, qty, value, value, cash=cash))
    m.put("priceCloses", "ROKT_2026", closes_doc("ROKT", 2026, [["2026-11-04", 29.0, 29.0], [THU, 30.0, 30.0], [FRI, 30.3, 30.3]]))
    m.put("activity", "dep", {"date": FRI, "accountKey": IND, "kind": "deposit", "symbol": None, "quantity": None, "amount": 1000.0, "core": False})
    m.pull(f"{SAT}T14:00:00+00:00")


def stored_run(cfg, now=SAT_NOW):
    from desk.engine import triggers

    mirror = open_mirror(cfg)
    desk = connect(cfg.desk_db)
    try:
        out = core.compute(cfg, mirror, desk, now=now)
        stored = core.store(desk, out)
        found = triggers.detect(cfg, desk, stored["as_of"], now=now)
        day = desk.execute(
            "SELECT value FROM metric_values WHERE metric_id='ret.twr' AND scope='portfolio' AND \"window\"='1D' AND as_of=?", (stored["as_of"],)
        ).fetchone()
    finally:
        desk.close()
        mirror.close()
    return out, found, day[0] if day else None


def test_a_margin_buy_and_deposit_are_flows_not_return(cfg, mirror):
    seed_two_snapshots(mirror)
    run_holdings(cfg)
    out, found, day = stored_run(cfg)
    assert out.implied[(IND, FRI)] == pytest.approx(3030.0) and out.implied[(K401, FRI)] == pytest.approx(32.8)
    start, end = 3500.0 + 150.0, 7560.0 + 164.0
    want = (end - 1000.0 - 3030.0 - 32.8) / start - 1
    assert day == pytest.approx(want * 100, abs=1e-3) and abs(day) < 1.5
    assert not [f for f in found if f[1] == "daily_move" and f[2] == "portfolio"]
    status, detail = {c: (s, d) for _, c, s, d in out.health}["flows"]
    assert status == "ok" and IND in detail and "+3,030.00" in detail and "not return" in detail


def test_unpriced_plan_codes_never_fire_a_daily_move(cfg, mirror):
    seed_two_snapshots(mirror)
    run_holdings(cfg)
    _, found, _ = stored_run(cfg)
    assert not [f for f in found if f[1] == "daily_move" and f[2] == "Q20002"]
    add_bars(cfg, [("ROKT", THU, 30.0), ("ROKT", FRI, 36.0)])
    run_holdings(cfg)
    _, found, _ = stored_run(cfg)
    moves = {f[2]: f[3]["ret_pct"] for f in found if f[1] == "daily_move"}
    assert moves.get("ROKT") == 20.0 and "Q20002" not in moves


def test_eft_and_ach_transfers_are_external_flows():
    from desk.engine.flows import classify

    rows = [
        {"date": FRI, "accountKey": IND, "kind": "transfer", "amount": 800.0, "action": "Electronic Funds Transfer Received"},
        {"date": FRI, "accountKey": IND, "kind": "other", "amount": -300.0, "description": "ACH WITHDRAWAL TO BANK"},
        {"date": FRI, "accountKey": IND, "kind": "transfer", "amount": 5.0, "symbol": "ROKT", "action": "TRANSFER OF ASSETS"},
        {"date": FRI, "accountKey": IND, "kind": "other", "amount": 12.0, "action": "DIVIDEND RECEIVED", "core": True},
        {"date": FRI, "accountKey": IND, "kind": "other", "amount": 40.0, "action": "FEE REBATE"},
        {"date": THU, "accountKey": HSA, "kind": "transfer", "amount": -250.0, "action": "TRANSFER TO HSA INVESTMENTS"},
        {"date": THU, "accountKey": IND, "kind": "transfer", "amount": 250.0, "action": "TRANSFER FROM CASH"},
    ]
    flows = {(f["account"], f["amount"]): f["external_portfolio"] for f in classify(rows)}
    assert flows == {(IND, 800.0): 1, (IND, -300.0): 1, (HSA, -250.0): 0, (IND, 250.0): 0}


def test_a_transfer_on_a_rolled_day_is_not_return(cfg, mirror):
    rows = [(IND, "ROKT", 100.0, 3000.0, False), (IND, "SPAXX", 500.0, 500.0, True)]
    mirror.put("snapshots", 1, snapshot(1, f"{THU}T21:30", 3500.0, 2))
    for pid, (acct, sym, qty, value, cash) in enumerate(rows, start=1):
        mirror.put("positions", pid, position(pid, 1, acct, sym, qty, value, value, cash=cash))
    mirror.put("priceCloses", "ROKT_2026", closes_doc("ROKT", 2026, [[THU, 30.0, 30.0], [FRI, 30.3, 30.3]]))
    mirror.put("activity", "eft", {"date": FRI, "accountKey": IND, "kind": "transfer", "amount": 1000.0, "action": "Electronic Funds Transfer Received"})
    mirror.pull(f"{SAT}T14:00:00+00:00")
    run_holdings(cfg)
    assert rows_on(cfg, FRI)[(IND, "SPAXX")]["value"] == 1500.0
    out, _, day = stored_run(cfg)
    assert out.implied == {} and day == pytest.approx(30 / 3500 * 100, abs=1e-3)


# ---- QA pass on real shapes ----

WED = "2026-11-04"


def one_snapshot(m, day, rows, stamp="21:30"):
    m.put("snapshots", 1, snapshot(1, f"{day}T{stamp}", sum(r[3] for r in rows), len(rows)))
    for pid, (acct, sym, qty, value, cash) in enumerate(rows, start=1):
        m.put("positions", pid, position(pid, 1, acct, sym, qty, value, value, cash=cash))


def test_buys_without_quantity_move_shares_at_the_days_close(cfg, mirror):
    one_snapshot(mirror, THU, [(IND, "ROKT", 100.0, 3000.0, False), (IND, "SPAXX", 3000.0, 3000.0, True)])
    mirror.put("priceCloses", "ROKT_2026", closes_doc("ROKT", 2026, [[THU, 30.0, 30.0], [FRI, 30.3, 30.3]]))
    mirror.put("activity", "b1", {"date": FRI, "accountKey": IND, "kind": "buy", "symbol": "ROKT", "quantity": None, "amount": -1515.0})
    mirror.put("activity", "b2", {"date": FRI, "accountKey": IND, "kind": "buy", "symbol": "Z9999", "amount": -100.0})
    mirror.pull(f"{SAT}T14:00:00+00:00")
    run_holdings(cfg)
    fri = rows_on(cfg, FRI)
    assert fri[(IND, "ROKT")]["shares"] == pytest.approx(150.0) and fri[(IND, "SPAXX")]["value"] == 1485.0
    assert (IND, "Z9999") not in fri
    _, _, day = stored_run(cfg)
    assert day == pytest.approx(30 / 6000 * 100, abs=1e-3)


def test_recomputing_a_day_withdraws_triggers_that_no_longer_hold(cfg, mirror):
    from desk.engine import triggers

    seed_two_snapshots(mirror)
    run_holdings(cfg)
    stored_run(cfg)
    desk = connect(cfg.desk_db)
    with desk:
        desk.execute("INSERT INTO triggers VALUES (?, 'daily_move', 'Q20002', '{\"ret_pct\": -12.5}', 'x')", (FRI,))
        desk.execute("INSERT INTO triggers VALUES (?, 'lot_export', 'lots', '{}', 'x')", (FRI,))
    result = triggers.run(cfg, desk, FRI, now=SAT_NOW)
    left = {(r[0], r[1]) for r in desk.execute("SELECT kind, scope_id FROM triggers WHERE as_of=?", (FRI,))}
    desk.close()
    assert result["withdrawn"] == 1 and ("daily_move", "Q20002") not in left and ("lot_export", "lots") in left


def test_a_snapshot_carrying_older_closes_is_called_stale(cfg, mirror):
    one_snapshot(mirror, FRI, [(IND, "ROKT", 100.0, 2900.0, False), (IND, "SPAXX", 100.0, 100.0, True)], stamp="08:00")
    mirror.put("priceCloses", "ROKT_2026", closes_doc("ROKT", 2026, [["2026-11-03", 28.0, 28.0], [WED, 29.0, 29.0], [THU, 30.0, 30.0]]))
    mirror.pull(f"{SAT}T14:00:00+00:00")
    run_holdings(cfg)
    assert rows_on(cfg, FRI)[(IND, "ROKT")]["close"] == 30.0
    status, detail = health(cfg)["value"]
    assert status == "warn" and f"carries {WED} closes" in detail and "Fix: nothing to do" in detail


def test_market_keys_warn_for_any_missing_key(cfg, mirror, monkeypatch):
    for key in ("TIINGO_API_KEY", "FINNHUB_API_KEY", "FRED_API_KEY"):
        monkeypatch.setenv(key, "k")
    monkeypatch.delenv("DESK_SEC_USER_AGENT", raising=False)
    seed_like_the_box(mirror)
    run_holdings(cfg)
    checks = health(cfg)
    status, detail = checks["market_keys"]
    assert status == "warn" and detail.endswith("Fix: run `sudo bash /mnt/Manifest/apps/vektor-desk-src/deploy/setup-truenas.sh set DESK_SEC_USER_AGENT`.")
    assert all("answer n" not in d for _, d in checks.values())


def test_money_in_without_a_schedule_reads_as_money_landed():
    from desk.engine.triggers import _words

    base = {"kind": "deposit_landed", "scope_id": "x", "as_of": FRI}
    planned = _words(base | {"detail": {"date": FRI, "account": IND, "expected": THU, "scheduled": True}})
    loose = _words(base | {"detail": {"date": FRI, "account": IND, "expected": FRI, "scheduled": False}})
    assert planned == f"The deposit expected {THU} landed on {FRI}." and loose == f"Money landed in {IND} on {FRI}."

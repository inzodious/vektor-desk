import json
import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from desk.db import connect, desk_conn
from desk.decisions.plan import cash_in
from desk.engine import __main__ as engine_main
from desk.engine import broker, core, schema
from desk.engine.__main__ import run_holdings
from desk.engine.flows import classify
from desk.engine.lots import current_lots
from desk.engine.source import open_mirror
from desk.engine.tax import realized
from tests.engine.helpers import closes_doc, position, snapshot

ET = ZoneInfo("America/New_York")
IND_NUM, HSA_NUM = "X55550003", "X55550002"
IND, HSA = "individual-0003", "hsa-0002"
SUBS = {
    "Buy": ("BY", "ST"),
    "Sell": ("SL", "ST"),
    "Dividend reinvest": ("RN", "ST"),
    "Dividend Paid": ("VP", "IT"),
    "Deposit": ("DP", "CT"),
    "Withdrawal": ("WD", "CT"),
    "Taxes": ("TX", "CT"),
    "Other Interest": ("OI", "IT"),
    "Reverse Split": ("RS", "CA"),
    "Distribution/Split spin-off": ("DS", "CA"),
    "Other Cash": ("OC", "CT"),
}
SEQ = [0]
FI_PREFS = {"key": "fi", "value": {"birthDate": "1990-07-12", "fiTargetAge": 50, "fiYearlySpend": 40000, "fiMultiple": 25}}


def epoch(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=ET).timestamp())


def txn(acct, day, sub, *, symbol=None, qty=None, net=0.0, price=0.0, dw="W", desc="", sec="Equity", cusip="000000000", cancelled=False, margin=False):
    SEQ[0] += 1
    code, typ = SUBS[sub]
    return {
        "acctNum": acct,
        "amtDetail": {"price": price, "commission": 0, "fees": 0, "interest": 0, "net": net, "principal": net},
        "brokerageDetail": {
            "tradeTypeCodeDesc": "Margin" if margin else "Cash",
            "isCancelled": cancelled,
            "additionalDetail": {"depositWithdrawalCode": dw},
        },
        "catDetail": {"txnTypeCode": typ, "txnSubCatCode": code, "txnSubCatDesc": sub},
        "date": epoch(day),
        "dateDetail": {"tradedDate": epoch(day), "postedDate": epoch(day), "stlmntDate": epoch(day) + 86400},
        "description": desc or f"{sub.upper()} ({symbol or 'CASH'}) (Cash)",
        "shortDesc": desc or sub.upper(),
        "quantity": "" if qty is None else str(qty),
        "securityDetail": {"symbol": symbol, "typeCodeDesc": sec if symbol or cusip.strip("0") else None, "cusip": cusip},
        "txnNum": f"T{SEQ[0]:06d}",
    }


def export(rows, start="2025-01-01", end="2026-11-07"):
    return {"config": {"yearsBack": 2, "accounts": [IND_NUM, HSA_NUM]}, "fetchLog": [{"range": f"{start} → {end}", "status": 200}], "transactions": rows}


def history_rows():
    return [
        txn(IND_NUM, "2025-01-10", "Buy", symbol="ROKT", qty=10, net=200, price=20),
        txn(IND_NUM, "2025-03-10", "Buy", symbol="ROKT", qty=10, net=300, price=30),
        txn(IND_NUM, "2026-02-02", "Sell", symbol="ROKT", qty=-15, net=600, price=40, dw="D"),
        txn(IND_NUM, "2025-04-01", "Buy", symbol="FXAIX", qty=2, net=200, price=100, sec="Mutual Fund"),
        txn(IND_NUM, "2025-05-01", "Buy", symbol="FXAIX", qty=2, net=400, price=200, sec="Mutual Fund"),
        txn(IND_NUM, "2026-01-15", "Sell", symbol="FXAIX", qty=-1, net=180, price=180, dw="D", sec="Mutual Fund"),
        txn(IND_NUM, "2025-06-02", "Buy", symbol="TRDR", qty=100, net=500, price=5, cusip="11111A111"),
        txn(IND_NUM, "2025-09-02", "Reverse Split", qty=-100, dw="D", desc="REVERSE SPLIT R/S TO 22222B222 (11111A111) (Cash)", cusip="11111A111"),
        txn(IND_NUM, "2025-09-02", "Reverse Split", qty=9, dw="D", desc="REVERSE SPLIT R/S FROM 11111A111 (22222B222) (Cash)", cusip="22222B222"),
        txn(IND_NUM, "2025-09-02", "Other Interest", net=3.1, dw="D", desc="IN LIEU OF FRX SHARE LEU PAYOUT (22222B222) (Cash)", cusip="22222B222"),
        txn(IND_NUM, "2026-03-02", "Sell", symbol="TRDR", qty=-9, net=90, price=10, dw="D", cusip="22222B222"),
        txn(IND_NUM, "2025-02-03", "Buy", symbol="GMEX", qty=2, net=200, price=100),
        txn(IND_NUM, "2025-07-22", "Distribution/Split spin-off", symbol="GMEX", qty=6, dw="D", desc="DISTRIBUTION GMEX CORP (GMEX) (Cash)"),
        txn(IND_NUM, "2026-01-05", "Buy", symbol="CHIP", qty=4, net=2000, price=500),
        txn(IND_NUM, "2026-02-10", "Sell", symbol="CHIP", qty=-4, net=1600, price=400, dw="D"),
        txn(IND_NUM, "2026-02-20", "Buy", symbol="CHIP", qty=2, net=780, price=390),
        txn(IND_NUM, "2026-01-20", "Sell", symbol="OLDY", qty=-5, net=100, price=20, dw="D"),
        txn(IND_NUM, "2026-10-21", "Other Cash", net=25, desc="MARGIN INTEREST as of 2026-10-20 (Margin)", margin=True),
        txn(IND_NUM, "2026-10-01", "Deposit", net=1000, dw="D", desc="Electronic Funds Transfer Received (Cash)"),
        txn(IND_NUM, "2026-10-05", "Withdrawal", net=50, desc="Electronic Funds Transfer Paid (Cash)"),
        txn(IND_NUM, "2026-09-30", "Dividend Paid", symbol="SPAXX", net=1.23, dw="D", sec="Mutual Fund"),
        txn(IND_NUM, "2026-09-30", "Dividend reinvest", symbol="SPAXX", qty=1.23, net=1.23, sec="Mutual Fund"),
        txn(IND_NUM, "2026-09-30", "Other Cash", net=40, dw="D", desc="TRANSFERRED FROM VS 000-000000 (Cash)"),
        txn(IND_NUM, "2026-08-01", "Buy", symbol="ROKT", qty=99, net=999, price=10, cancelled=True),
        txn(HSA_NUM, "2026-10-15", "Other Cash", net=100, dw="D", desc="PARTIC CONTR CURRENT HSA CONTRIBUTION CURRENT YEAR CONTRIB (Cash)"),
    ]


def drop(cfg, name, body):
    folder = cfg.inbox / "fidelity"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(body))


def desk_db(cfg):
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    return conn


# ---- Parsing ----


def test_parse_types_signs_and_symbols():
    rows, info = broker.parse(export(history_rows()))
    assert info == {"cancelled": 1, "start": "2025-01-01", "end": "2026-11-07"}
    by = {(r["date"], r["kind"], r["symbol"]): r for r in rows}
    assert by[("2025-01-10", "buy", "ROKT")]["amount"] == -200 and by[("2025-01-10", "buy", "ROKT")]["quantity"] == 10
    assert by[("2026-02-02", "sell", "ROKT")]["amount"] == 600 and by[("2026-02-02", "sell", "ROKT")]["quantity"] == -15
    assert by[("2026-10-21", "margin_interest", None)]["amount"] == -25
    assert by[("2026-10-01", "deposit", None)]["amount"] == 1000
    assert by[("2026-10-05", "withdrawal", None)]["amount"] == -50
    assert by[("2026-09-30", "dividend", None)]["amount"] == 1.23
    assert ("2026-09-30", "journal", None) in by
    splits = sorted(r["quantity"] for r in rows if r["kind"] == "split")
    assert splits == [-100, 9] and {r["symbol"] for r in rows if r["kind"] == "split"} == {"TRDR"}
    assert next(r for r in rows if r["kind"] == "in_lieu")["symbol"] == "TRDR"
    hsa = next(r for r in rows if r["last4"] == "0002")
    assert hsa["kind"] == "deposit" and hsa["amount"] == 100
    assert all(r["last4"] in ("0003", "0002") for r in rows)


def test_parse_reads_the_export_shape():
    body = json.loads((Path(__file__).parent / "fixtures" / "fidelity_history_shape.json").read_text())
    rows, info = broker.parse(body)
    kinds = {r["kind"] for r in rows}
    assert kinds == {"buy", "sell", "reinvest", "dividend", "deposit", "withdrawal", "tax", "margin_interest", "split", "in_lieu", "distribution"}
    assert info["end"] == "2026-11-07" and {r["last4"] for r in rows} == {"0003", "0002"}
    assert next(r for r in rows if r["kind"] == "margin_interest")["amount"] < 0
    assert next(r for r in rows if r["last4"] == "0002")["kind"] == "deposit"
    assert all(not re.search(r"\d{6,}", r["description"]) for r in rows)


def test_parse_rejects_a_file_without_transactions():
    with pytest.raises(broker.BrokerFileError):
        broker.parse({"positions": []})


# ---- Import ----


def test_import_is_idempotent_and_keeps_only_the_last_four(cfg):
    conn = desk_db(cfg)
    drop(cfg, "history.json", export(history_rows()))
    first = broker.import_inbox(cfg, conn)
    assert first["ok"] and first["imported"][0]["added"] == 24 and first["imported"][0]["accounts"] == [HSA, IND]
    again = broker.import_inbox(cfg, conn)
    assert again["skipped"] and not again["imported"]
    rows = history_rows()
    drop(cfg, "newer.json", export(rows[-3:] + [txn(IND_NUM, "2026-11-04", "Buy", symbol="ROKT", qty=10, net=350, price=35)], start="2026-08-01"))
    more = broker.import_inbox(cfg, conn)
    assert more["imported"][0]["added"] >= 1
    dump = "\n".join(conn.iterdump())
    assert IND_NUM not in dump and HSA_NUM not in dump and "55550003" not in dump
    conn.close()


def test_bad_json_is_an_error_not_a_crash(cfg):
    conn = desk_db(cfg)
    folder = cfg.inbox / "fidelity"
    folder.mkdir(parents=True)
    (folder / "broken.json").write_text("{nope")
    result = broker.import_inbox(cfg, conn)
    assert not result["ok"] and result["errors"][0]["file"] == "broken.json"
    conn.close()


def test_accounts_follow_the_mirror_keys(cfg):
    conn = desk_db(cfg)
    drop(cfg, "history.json", export(history_rows()))
    broker.import_inbox(cfg, conn)
    broker.remap(conn, {"0003": "brokerage-0003"})
    assert {r[0] for r in conn.execute("SELECT DISTINCT account FROM broker_txns")} == {"brokerage-0003", HSA}
    conn.close()


def test_journals_between_accounts_become_paired_transfers(cfg):
    conn = desk_db(cfg)
    rows = [
        txn(IND_NUM, "2026-10-02", "Other Cash", net=250, desc="TRANSFERRED TO 000-000002 (Cash)"),
        txn(HSA_NUM, "2026-10-02", "Other Cash", net=250, dw="D", desc="TRANSFERRED FROM 000-000003 (Cash)"),
        txn(IND_NUM, "2026-10-09", "Other Cash", net=80, dw="D", desc="JOURNALED MARGIN TO CASH (Cash)"),
    ]
    drop(cfg, "history.json", export(rows, start="2026-09-01"))
    broker.import_inbox(cfg, conn)
    h = broker.load(conn, {"0002": HSA, "0003": IND})
    moved = {(r["accountKey"], r["kind"], r["amount"]) for r in h.rows}
    assert moved == {(IND, "withdrawal", -250.0), (HSA, "deposit", 250.0)}
    flows = classify(h.rows)
    assert all(f["external_account"] and not f["external_portfolio"] for f in flows) and len(flows) == 2
    conn.close()


# ---- Lots ----


def book_for(cfg, rows):
    conn = desk_db(cfg)
    drop(cfg, "history.json", export(rows))
    broker.import_inbox(cfg, conn)
    h = broker.load(conn)
    book = broker.build_book(h.rows, h)
    conn.close()
    return book


def lots_of(book, symbol):
    return [lot for lot in book.lots if lot["symbol"] == symbol]


def sales_of(book, symbol):
    return [r for r in book.realized if r["symbol"] == symbol]


def test_fifo_for_stocks_with_terms(cfg):
    book = book_for(cfg, history_rows())
    rokt = sales_of(book, "ROKT")
    assert [(r["acquired"], r["shares"], r["cost"], r["gain"], r["term"]) for r in rokt] == [
        ("2025-01-10", 10, 200, 200, "long"),
        ("2025-03-10", 5, 150, 50, "short"),
    ]
    left = lots_of(book, "ROKT")
    assert len(left) == 1 and left[0]["shares"] == 5 and left[0]["cost"] == 150 and left[0]["method"] == "fifo"


def test_average_cost_for_mutual_funds(cfg):
    book = book_for(cfg, history_rows())
    sale = sales_of(book, "FXAIX")[0]
    assert sale["cost"] == 150 and sale["gain"] == 30 and sale["acquired"] == "2025-04-01" and sale["method"] == "average"
    assert sum(lot["cost"] for lot in lots_of(book, "FXAIX")) == pytest.approx(450)


def test_reverse_split_carries_basis_and_cash_in_lieu_is_a_sale(cfg):
    book = book_for(cfg, history_rows())
    trdr = sales_of(book, "TRDR")
    lieu = next(r for r in trdr if r["shares"] == 0)
    assert lieu["proceeds"] == 3.1 and lieu["cost"] == 0
    sold = next(r for r in trdr if r["shares"])
    assert sold["shares"] == pytest.approx(9) and sold["cost"] == 500 and sold["gain"] == -410 and sold["acquired"] == "2025-06-02"
    assert not lots_of(book, "TRDR")


def test_distribution_of_a_held_symbol_is_a_split(cfg):
    book = book_for(cfg, history_rows())
    gme = lots_of(book, "GMEX")
    assert len(gme) == 1 and gme[0]["shares"] == 8 and gme[0]["cost"] == 200 and gme[0]["acquired"] == "2025-02-03"


def test_wash_sale_disallows_the_loss_and_moves_it_into_the_new_lot(cfg):
    book = book_for(cfg, history_rows())
    sale = sales_of(book, "CHIP")[0]
    assert sale["gain"] == -400 and sale["wash_disallowed"] == 200
    lot = lots_of(book, "CHIP")[0]
    assert lot["acquired"] == "2026-02-20" and lot["cost"] == 980


def test_shares_sold_before_the_history_have_unknown_basis(cfg):
    book = book_for(cfg, history_rows())
    old = sales_of(book, "OLDY")[0]
    assert old["cost"] is None and old["gain"] is None
    assert "before 2025-01-01" in book.notes[(IND, "OLDY")]
    year = realized(book.realized, 2026)
    assert year["unknown"] == 1 and year["modelled"] == year["rows"]
    assert year["st"] == pytest.approx(50 + 30 - 410 - 400) and year["lt"] == pytest.approx(200) and year["wash_disallowed"] == 200


def test_a_lot_export_beats_the_rebuilt_lots(cfg):
    conn = desk_db(cfg)
    book = book_for(cfg, history_rows())
    broker.store(conn, book, "2026-11-06")
    conn.commit()
    assert {r["quality"] for r in current_lots(conn)} == {"modelled"}
    with conn:
        fid = conn.execute(
            "INSERT INTO lot_files (sha256, name, kind, as_of, imported_at, rows) VALUES ('x', 'lots.csv', 'lots', '2026-11-01', 'now', 1)"
        ).lastrowid
        conn.execute(
            "INSERT INTO lots (file_id, as_of, account, symbol, acquired, shares, cost) VALUES (?, '2026-11-01', ?, 'ROKT', '2025-01-10', 5, 100)",
            (fid, IND),
        )
    lots = current_lots(conn)
    assert {(r["account"], r["quality"]) for r in lots} == {(IND, "ok")}
    conn.close()


# ---- Merge with the mirror ----


def test_broker_rows_replace_matching_mirror_rows(cfg):
    conn = desk_db(cfg)
    rows = [txn(IND_NUM, "2026-11-04", "Buy", symbol="ROKT", qty=10, net=350, price=35), txn(IND_NUM, "2026-10-01", "Deposit", net=1000, dw="D")]
    drop(cfg, "history.json", export(rows, start="2026-09-01", end="2026-11-05"))
    broker.import_inbox(cfg, conn)
    h = broker.load(conn)
    mirror_rows = [
        {"key": "m1", "date": "2026-11-05", "accountKey": IND, "kind": "buy", "symbol": "ROKT", "quantity": None, "amount": -350.0},
        {"key": "m2", "date": "2026-10-20", "accountKey": IND, "kind": "dividend", "symbol": "ROKT", "amount": 4.0},
        {"key": "m3", "date": "2026-11-06", "accountKey": IND, "kind": "buy", "symbol": "ROKT", "amount": -100.0},
        {"key": "m4", "date": "2026-10-03", "accountKey": "401k-0001", "kind": "buy", "symbol": "P10001", "amount": -50.0},
    ]
    merged = broker.merge(mirror_rows, h)
    keys = {r["key"] for r in merged}
    assert "m1" not in keys and {"m2", "m3", "m4"} <= keys and h.matched == 1
    assert [r["key"] for r in h.kept] == ["m2"]
    buy = next(r for r in merged if r.get("source") == "broker" and r["kind"] == "buy")
    assert buy["quantity"] == 10 and buy["accountKey"] == IND
    conn.close()


# ---- Engine run ----


MON, WED, THU, FRI = "2026-11-02", "2026-11-04", "2026-11-05", "2026-11-06"
NOW = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)


def seed(mirror):
    mirror.put("snapshots", 1, snapshot(1, f"{MON}T21:00", 1300.0, 2))
    mirror.put("positions", 1, position(1, 1, IND, "ROKT", 10.0, 300.0, 300.0))
    mirror.put("positions", 2, position(2, 1, IND, "SPAXX", 1000.0, 1000.0, cash=True))
    mirror.put("activity", "a1", {"date": WED, "accountKey": IND, "kind": "buy", "symbol": "ROKT", "quantity": None, "amount": -350.0, "core": False})
    mirror.put("priceCloses", "ROKT_2026", closes_doc("ROKT", 2026, [[MON, 30, 30], ["2026-11-03", 31, 31], [WED, 36, 36], [THU, 36, 36], [FRI, 37, 37]]))
    mirror.put("plans", "p1", {"loadedAt": "2026-11-01T00:00:00Z", "plan": {"funds": [{"ticker": "FXAIX", "target_weight": 1.0}]}})
    mirror.pull(f"{FRI}T22:00:00+00:00")


def run_rows():
    return [
        txn(IND_NUM, "2026-10-01", "Deposit", net=1300, dw="D"),
        txn(IND_NUM, "2026-10-01", "Buy", symbol="ROKT", qty=10, net=300, price=30),
        txn(IND_NUM, WED, "Buy", symbol="ROKT", qty=10, net=350, price=35),
        txn(IND_NUM, "2026-10-21", "Other Cash", net=12.5, desc="MARGIN INTEREST as of 2026-10-20 (Margin)", margin=True),
    ]


def computed(cfg):
    mirror = open_mirror(cfg)
    desk = connect(cfg.desk_db)
    try:
        out = core.compute(cfg, mirror, desk, now=NOW)
        core.store(desk, out)
    finally:
        desk.close()
        mirror.close()
    return out


def test_roll_forward_uses_broker_shares(cfg, mirror):
    seed(mirror)
    drop(cfg, "history.json", export(run_rows(), start="2026-09-01", end=WED))
    assert engine_main.run_history(cfg)["ok"]
    run_holdings(cfg)
    conn = connect(cfg.desk_db, readonly=True)
    rokt = conn.execute("SELECT shares FROM holdings_daily WHERE date=? AND account=? AND symbol='ROKT'", (THU, IND)).fetchone()[0]
    conn.close()
    assert rokt == 20
    out = computed(cfg)
    checks = {c: (s, d) for _, c, s, d, *_ in out.health}
    assert checks["history"][0] == "ok" and "1 Escape Vektor rows replaced" in checks["history"][1]
    assert checks["shares"][0] == "ok" and "FIFO for stocks and ETFs" in checks["shares"][1]
    paid = {m[3]: m[5] for m in out.metrics if m[0] == "margin.interest_paid"}
    assert paid == {"YTD": 12.5, "1Y": 12.5}
    assert out.book is not None and sum(lot["shares"] for lot in out.book.lots) == 20
    conn = connect(cfg.desk_db, readonly=True)
    assert conn.execute("SELECT count(*) FROM broker_lots").fetchone()[0] == 2
    conn.close()


def test_without_history_nothing_changes(cfg, mirror):
    seed(mirror)
    run_holdings(cfg)
    out = computed(cfg)
    checks = {c: (s, d) for _, c, s, d, *_ in out.health}
    assert checks["history"][0] == "ok" and checks["shares"][0] == "warn" and out.book is None
    assert not [m for m in out.metrics if m[0] == "margin.interest_paid"]


def test_fi_deposits_come_from_broker_history(cfg, mirror):
    mirror.put("prefs", "fi", FI_PREFS)
    seed(mirror)
    drop(cfg, "history.json", export(run_rows(), start="2026-09-01", end=WED))
    engine_main.run_history(cfg)
    run_holdings(cfg)
    out = computed(cfg)
    assert out.views["fi"]["deposit_note"] == "from your last 2 months of deposits, net of withdrawals"


def test_decisions_see_broker_deposits(cfg, mirror):
    seed(mirror)
    drop(cfg, "history.json", export(run_rows(), start="2026-09-01", end=WED))
    engine_main.run_history(cfg)
    conn = desk_conn(cfg)
    try:
        rows = broker.decision_rows(conn, "2026-09-01")
    finally:
        conn.close()
    assert {a.get("source") for _, a in rows} == {"broker"}
    landed = cash_in(rows)
    assert [(x["date"], x["accountKey"], x["amount"]) for x in landed] == [("2026-10-01", IND, 1300.0)]


def test_daily_imports_the_history_first(cfg, mirror, monkeypatch):
    seed(mirror)
    drop(cfg, "history.json", export(run_rows(), start="2026-09-01", end=WED))
    monkeypatch.setattr(engine_main, "run_core", lambda c: {"ok": True})
    result = engine_main.run_daily(cfg)
    assert result["history"]["imported"][0]["added"] == 4 and result["holdings"]["ok"]

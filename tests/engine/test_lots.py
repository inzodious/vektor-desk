import os

import pytest

from desk.db import connect
from desk.engine.__main__ import run_lots
from desk.engine.lots import LotFileError, account_key, current_lots, parse_date, parse_lot_file, term_of

UNREALIZED = """Account Name,Account Number,Symbol,Description,Date Acquired,Quantity,Cost Basis Per Share,Cost Basis,Current Value,Term
Individual,Z00001111,ABCD,ABCD CORP,03/14/2025,10,$50.00,$500.00,$300.00,Long
,,ABCD,ABCD CORP,11/02/2025,5,$40.00,$200.00,$150.00,Short
,,SPAXX**,HELD IN MONEY MARKET,,100,,,$100.00,
Health Savings Account,Z00002222,FXAIX,FIDELITY 500 INDEX,Various,2,,"$1,000.00","$1,100.00",

"Date downloaded Nov-07-2026 9:15 a.m ET"
"""

REALIZED = (
    "Symbol,Security Description,Quantity,Date Acquired,Date Sold,Proceeds,Cost Basis,"
    "Short-Term Gain/Loss,Long-Term Gain/Loss,Wash Sale Loss Disallowed,Account Name,Account Number\n"
    """WXYZ,WXYZ INC,4,01/05/2025,10/10/2026,$200.00,$400.00,,($200.00),,Individual,Z00001111
QRST,QRST INC,2,09/01/2026,10/12/2026,$90.00,$100.00,($10.00),,$10.00,Individual,Z00001111
"""
)


def test_parses_unrealized_lots_and_skips_cash():
    f = parse_lot_file(UNREALIZED)
    assert f.kind == "lots" and f.as_of == "2026-11-07"
    assert [(r["account"], r["symbol"], r["acquired"], r["shares"], r["cost"]) for r in f.rows] == [
        ("individual-1111", "ABCD", "2025-03-14", 10, 500.0),
        ("individual-1111", "ABCD", "2025-11-02", 5, 200.0),
        ("hsa-2222", "FXAIX", None, 2, 1000.0),
    ]
    assert f.rows[0]["term"] == "long" and f.rows[1]["term"] == "short" and f.rows[0]["cost_per_share"] == 50.0
    assert f.rows[2]["cost_per_share"] == 500.0
    assert any("no acquired date" in w for w in f.warnings)


def test_parses_realized_with_wash_and_terms():
    f = parse_lot_file(REALIZED, fallback_as_of="2026-11-07")
    assert f.kind == "realized" and f.as_of == "2026-11-07"
    wxyz, qrst = f.rows
    assert wxyz["gain"] == -200.0 and wxyz["term"] == "long" and wxyz["account"] == "individual-1111"
    assert qrst["gain"] == -10.0 and qrst["term"] == "short" and qrst["wash_disallowed"] == 10.0


def test_rejects_files_that_are_not_lot_exports():
    with pytest.raises(LotFileError, match="No header row"):
        parse_lot_file("hello,world\n1,2\n")
    with pytest.raises(LotFileError, match="missing the acquired"):
        parse_lot_file("Symbol,Quantity,Current Value,Cost Basis\nABCD,1,2,3\n")


def test_dates_terms_and_account_keys():
    assert parse_date("3/4/26") == "2026-03-04" and parse_date("Mar-04-2026") == "2026-03-04" and parse_date("VARIOUS") is None
    assert term_of("", "2025-11-07", None, "2026-11-07") == "short"
    assert term_of("", "2025-11-07", None, "2026-11-08") == "long"
    assert term_of("", "2024-02-29", "2025-03-01", None) == "long"
    assert account_key("Individual (•••1111)", "") == "individual-1111"
    assert account_key("Health Savings Account", "Z99992222") == "hsa-2222"


def test_inbox_import_is_idempotent_and_latest_file_wins(cfg):
    inbox = cfg.inbox / "fidelity"
    inbox.mkdir(parents=True)
    (inbox / "lots-old.csv").write_text(UNREALIZED.replace("Nov-07-2026", "Nov-01-2026").replace(",5,$40.00,$200.00", ",6,$40.00,$240.00"))
    (inbox / "lots-new.csv").write_text(UNREALIZED)
    (inbox / "realized.csv").write_text(REALIZED)
    (inbox / "junk.csv").write_text("not,a,lot,file\n")
    os.utime(inbox / "realized.csv", (1_793_000_000, 1_793_000_000))
    first = run_lots(cfg)
    assert not first["ok"] and [e["file"] for e in first["errors"]] == ["junk.csv"]
    assert len(first["imported"]) == 3
    second = run_lots(cfg)
    assert len(second["skipped"]) == 3 and not second["imported"]
    conn = connect(cfg.desk_db, readonly=True)
    lots = current_lots(conn)
    assert sorted((r["account"], r["shares"]) for r in lots) == [("hsa-2222", 2), ("individual-1111", 5), ("individual-1111", 10)]
    assert conn.execute("SELECT count(*) FROM realized_lots").fetchone()[0] == 2
    conn.close()


def test_api_lots(cfg, app_client):
    client = app_client(packages=["engine"])
    assert client.get("/api/engine/lots").json() == {"lots": [], "files": [], "history": []}
    inbox = cfg.inbox / "fidelity"
    inbox.mkdir(parents=True)
    (inbox / "lots.csv").write_text(UNREALIZED)
    run_lots(cfg)
    body = client.get("/api/engine/lots", params={"symbol": "abcd"}).json()
    assert [r["acquired"] for r in body["lots"]] == ["2025-03-14", "2025-11-02"] and body["files"][0]["kind"] == "lots"

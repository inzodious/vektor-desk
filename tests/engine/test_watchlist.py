from desk.db import connect
from desk.engine import schema


def test_watchlist_routes(cfg, app_client, monkeypatch):
    monkeypatch.setenv("DESK_WATCHLIST", "msft, aapl")
    client = app_client(packages=["engine"])
    before = client.get("/api/engine/watchlist").json()["symbols"]
    assert [(r["symbol"], r["source"]) for r in before] == [("AAPL", "env"), ("MSFT", "env")]

    added = client.post("/api/engine/watchlist", json={"symbol": " nvda "}).json()
    assert added["added"] == "NVDA" and [r["symbol"] for r in added["symbols"]] == ["NVDA", "AAPL", "MSFT"]
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    with desk:
        desk.executemany(
            "INSERT INTO prices_daily (symbol, date, close, adj_close, source) VALUES ('NVDA', ?, ?, ?, 'tiingo')",
            [("2026-11-05", 190, 190), ("2026-11-06", 200, 200)],
        )
        desk.execute("INSERT INTO sec_tickers VALUES ('NVDA', 1045810, 'NVIDIA CORP', '2026-11-01')")
    desk.close()
    row = client.get("/api/engine/watchlist").json()["symbols"][0]
    assert row | {"added_at": None} == {
        "symbol": "NVDA",
        "name": "NVIDIA CORP",
        "source": "desk",
        "added_at": None,
        "last_close": 200,
        "prev_close": 190,
        "last_bar": "2026-11-06",
        "has_research": False,
    }
    assert row["added_at"]

    for bad, words in (("BRK.B.C", "not a ticker"), ("", "not a ticker")):
        r = client.post("/api/engine/watchlist", json={"symbol": bad})
        assert r.status_code == 400 and words in r.json()["detail"]
    r = client.delete("/api/engine/watchlist/MSFT")
    assert r.status_code == 400 and "DESK_WATCHLIST" in r.json()["detail"]
    assert client.delete("/api/engine/watchlist/TSLA").status_code == 400
    gone = client.delete("/api/engine/watchlist/nvda").json()
    assert gone["removed"] == "NVDA" and [r["symbol"] for r in gone["symbols"]] == ["AAPL", "MSFT"]


def test_held_symbol_keeps_its_role(cfg, app_client):
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    with desk:
        desk.execute("INSERT INTO market_symbols (symbol, role, priority, added_at) VALUES ('ACME', 'held', 0, '2026-11-01')")
    desk.close()
    client = app_client(packages=["engine"])
    assert client.post("/api/engine/watchlist", json={"symbol": "ACME"}).status_code == 200
    assert client.get("/api/engine/watchlist").json()["symbols"] == []
    assert client.delete("/api/engine/watchlist/ACME").status_code == 400

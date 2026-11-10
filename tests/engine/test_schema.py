from desk.db import apply_schemas, connect
from desk.engine import schema

OLD_QUOTES = """
CREATE TABLE quotes_live (
  symbol TEXT NOT NULL,
  at TEXT NOT NULL,
  price REAL NOT NULL,
  prev_close REAL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (symbol, fetched_at)
) WITHOUT ROWID;
CREATE INDEX quotes_live_fetched ON quotes_live (fetched_at);
"""


def test_no_without_rowid_table_ends_on_a_primary_key_column(cfg):
    apply_schemas(cfg)
    conn = connect(cfg.desk_db, readonly=True)
    tables = [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND upper(sql) LIKE '%WITHOUT ROWID%'")]
    bad = []
    for t in tables:
        cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
        if cols[-1]["pk"] and not all(c["pk"] for c in cols):
            bad.append(t)
    conn.close()
    assert len(tables) > 40 and "quotes_live" not in tables and bad == []


def test_an_old_quotes_table_is_rebuilt_with_its_rows(cfg):
    conn = connect(cfg.desk_db)
    conn.executescript(OLD_QUOTES)
    with conn:
        conn.execute("INSERT INTO quotes_live VALUES ('ACME', '2026-11-09T15:00:00Z', 21.5, 21.0, 'finnhub', '2026-11-09T15:00:05Z')")
        conn.execute("INSERT INTO quotes_live VALUES ('ACME', '2026-11-09T15:05:00Z', 21.7, 21.0, 'finnhub', '2026-11-09T15:05:05Z')")
    schema.apply(conn)
    made = conn.execute("SELECT sql FROM sqlite_master WHERE name='quotes_live'").fetchone()[0]
    assert "WITHOUT ROWID" not in made.upper() and conn.execute("SELECT count(*), max(price) FROM quotes_live").fetchone()[:] == (2, 21.7)
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='quotes_live_fetched'").fetchone() and schema.rebuild_quotes(conn) is False
    with conn:
        conn.execute("INSERT OR REPLACE INTO quotes_live VALUES ('ACME', '2026-11-09T15:05:00Z', 21.8, 21.0, 'finnhub', '2026-11-09T15:05:05Z')")
    assert conn.execute("SELECT count(*), max(price) FROM quotes_live").fetchone()[:] == (2, 21.8)
    assert (
        conn.execute("PRAGMA quick_check").fetchone()[0] == "ok" and conn.execute("SELECT 1 FROM sqlite_master WHERE name='quotes_live_old'").fetchone() is None
    )
    conn.close()

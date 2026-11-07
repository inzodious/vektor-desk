import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS engine_runs (
  id INTEGER PRIMARY KEY,
  job TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  ok INTEGER NOT NULL DEFAULT 0,
  detail TEXT,
  engine_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS engine_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  as_of TEXT NOT NULL,
  date TEXT NOT NULL,
  source TEXT,
  total REAL,
  positions INTEGER NOT NULL,
  expected_positions INTEGER,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  alive INTEGER NOT NULL,
  anchor INTEGER NOT NULL DEFAULT 0,
  quality TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS engine_snapshots_date ON engine_snapshots (date);
CREATE TABLE IF NOT EXISTS prices_daily (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  close REAL NOT NULL,
  adj_close REAL,
  source TEXT NOT NULL,
  PRIMARY KEY (symbol, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS holdings_daily (
  date TEXT NOT NULL,
  account TEXT NOT NULL,
  symbol TEXT NOT NULL,
  shares REAL NOT NULL,
  close REAL,
  value REAL NOT NULL,
  cost REAL,
  reported_value REAL,
  is_cash INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL,
  anchor TEXT NOT NULL,
  quality TEXT NOT NULL,
  PRIMARY KEY (date, account, symbol)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS holdings_daily_symbol ON holdings_daily (symbol, date);
"""


def apply(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)

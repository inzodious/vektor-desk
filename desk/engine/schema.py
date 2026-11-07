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
CREATE TABLE IF NOT EXISTS lot_files (
  id INTEGER PRIMARY KEY,
  sha256 TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('lots', 'realized')),
  as_of TEXT,
  imported_at TEXT NOT NULL,
  rows INTEGER NOT NULL,
  warnings TEXT
);
CREATE TABLE IF NOT EXISTS lots (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES lot_files (id),
  as_of TEXT,
  account TEXT NOT NULL,
  symbol TEXT NOT NULL,
  acquired TEXT,
  shares REAL NOT NULL,
  cost REAL,
  cost_per_share REAL,
  value REAL,
  term TEXT
);
CREATE INDEX IF NOT EXISTS lots_symbol ON lots (symbol, account);
CREATE TABLE IF NOT EXISTS realized_lots (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES lot_files (id),
  account TEXT NOT NULL,
  symbol TEXT NOT NULL,
  acquired TEXT,
  sold TEXT,
  shares REAL NOT NULL,
  proceeds REAL,
  cost REAL,
  gain REAL,
  term TEXT,
  wash_disallowed REAL NOT NULL DEFAULT 0,
  UNIQUE (account, symbol, acquired, sold, shares, proceeds)
);
CREATE TABLE IF NOT EXISTS quotes_live (
  symbol TEXT NOT NULL,
  at TEXT NOT NULL,
  price REAL NOT NULL,
  prev_close REAL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (symbol, fetched_at)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS quotes_live_fetched ON quotes_live (fetched_at);
CREATE TABLE IF NOT EXISTS price_bars (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  open REAL,
  high REAL,
  low REAL,
  close REAL NOT NULL,
  adj_close REAL,
  volume REAL,
  div_cash REAL NOT NULL DEFAULT 0,
  split_factor REAL NOT NULL DEFAULT 1,
  PRIMARY KEY (symbol, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS market_symbols (
  symbol TEXT PRIMARY KEY,
  role TEXT NOT NULL,
  priority INTEGER NOT NULL,
  added_at TEXT NOT NULL,
  first_bar TEXT,
  last_bar TEXT,
  fetched_at TEXT,
  error TEXT
);
CREATE TABLE IF NOT EXISTS api_calls (
  id INTEGER PRIMARY KEY,
  provider TEXT NOT NULL,
  at TEXT NOT NULL,
  symbol TEXT,
  ok INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS api_calls_provider ON api_calls (provider, at);
"""


def apply(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)

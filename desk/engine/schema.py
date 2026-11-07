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
CREATE TABLE IF NOT EXISTS cash_flows (
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,
  account TEXT NOT NULL,
  amount REAL NOT NULL,
  kind TEXT NOT NULL,
  external_account INTEGER NOT NULL,
  external_portfolio INTEGER NOT NULL,
  ref TEXT
);
CREATE INDEX IF NOT EXISTS cash_flows_date ON cash_flows (date);
CREATE TABLE IF NOT EXISTS metric_values (
  metric_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  window TEXT NOT NULL,
  as_of TEXT NOT NULL,
  value REAL,
  unit TEXT NOT NULL,
  n_obs INTEGER,
  quality TEXT NOT NULL,
  engine_version TEXT NOT NULL,
  PRIMARY KEY (metric_id, scope, scope_id, window, as_of)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS metric_values_as_of ON metric_values (as_of);
CREATE TABLE IF NOT EXISTS series_daily (
  series_id TEXT NOT NULL,
  scope TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  date TEXT NOT NULL,
  value REAL NOT NULL,
  quality TEXT NOT NULL,
  PRIMARY KEY (series_id, scope, scope_id, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS data_health (
  as_of TEXT NOT NULL,
  check_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok', 'warn', 'fail')),
  detail TEXT,
  PRIMARY KEY (as_of, check_name)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS preflight (
  ticket_id TEXT NOT NULL,
  metric_id TEXT NOT NULL,
  before REAL,
  after REAL,
  flag TEXT NOT NULL CHECK (flag IN ('ok', 'watch', 'act')),
  at TEXT NOT NULL,
  engine_version TEXT NOT NULL,
  PRIMARY KEY (ticket_id, metric_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS triggers (
  as_of TEXT NOT NULL,
  kind TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  detail TEXT,
  fired_at TEXT NOT NULL,
  PRIMARY KEY (as_of, kind, scope_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sec_tickers (
  symbol TEXT PRIMARY KEY,
  cik INTEGER NOT NULL,
  title TEXT,
  fetched_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS filings (
  accession TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  cik INTEGER NOT NULL,
  form TEXT NOT NULL,
  filed TEXT NOT NULL,
  report_date TEXT,
  description TEXT,
  url TEXT
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS filings_symbol ON filings (symbol, filed);
CREATE TABLE IF NOT EXISTS fundamentals (
  symbol TEXT NOT NULL,
  concept TEXT NOT NULL,
  start TEXT,
  period_end TEXT NOT NULL,
  fy INTEGER,
  fp TEXT,
  form TEXT,
  filed TEXT,
  value REAL NOT NULL,
  unit TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fundamentals_symbol ON fundamentals (symbol, concept, period_end);
CREATE TABLE IF NOT EXISTS macro_daily (
  series TEXT NOT NULL,
  date TEXT NOT NULL,
  value REAL NOT NULL,
  PRIMARY KEY (series, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS earnings (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  hour TEXT,
  quarter INTEGER,
  year INTEGER,
  eps_estimate REAL,
  eps_actual REAL,
  revenue_estimate REAL,
  revenue_actual REAL,
  PRIMARY KEY (symbol, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS insider_trades (
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  filing_date TEXT,
  txn_date TEXT NOT NULL,
  code TEXT,
  change REAL,
  shares_after REAL,
  price REAL,
  UNIQUE (symbol, name, txn_date, code, change, shares_after)
);
CREATE TABLE IF NOT EXISTS wash_windows (
  as_of TEXT NOT NULL,
  symbol TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('loss_sale', 'recent_buy')),
  date TEXT NOT NULL,
  clears TEXT NOT NULL,
  account TEXT NOT NULL,
  amount REAL,
  PRIMARY KEY (symbol, kind, date, account)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sec_funds (
  symbol TEXT PRIMARY KEY,
  cik INTEGER NOT NULL,
  series_id TEXT NOT NULL,
  class_id TEXT,
  fetched_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS nport_filings (
  accession TEXT PRIMARY KEY,
  cik INTEGER NOT NULL,
  series_id TEXT NOT NULL,
  period TEXT,
  filed TEXT
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fund_holdings (
  fund TEXT NOT NULL,
  as_of TEXT NOT NULL,
  holding TEXT NOT NULL,
  name TEXT,
  cusip TEXT,
  weight REAL NOT NULL,
  asset_cat TEXT,
  country TEXT,
  accession TEXT,
  PRIMARY KEY (fund, holding)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sym_profiles (
  symbol TEXT PRIMARY KEY,
  name TEXT,
  industry TEXT,
  sector TEXT,
  fetched_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS lookthrough (
  as_of TEXT NOT NULL,
  holding TEXT NOT NULL,
  name TEXT,
  weight REAL NOT NULL,
  direct REAL NOT NULL,
  via TEXT NOT NULL,
  PRIMARY KEY (holding)
) WITHOUT ROWID;
"""


def apply(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)

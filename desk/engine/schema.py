import re
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
CREATE TABLE IF NOT EXISTS closes_provisional (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  close REAL NOT NULL,
  prev_close REAL,
  quote_at TEXT NOT NULL,
  stamped_at TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS broker_files (
  id INTEGER PRIMARY KEY,
  sha256 TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  window_start TEXT,
  window_end TEXT,
  rows INTEGER NOT NULL,
  added INTEGER NOT NULL,
  cancelled INTEGER NOT NULL,
  accounts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_txns (
  id TEXT PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES broker_files (id),
  seq INTEGER NOT NULL,
  last4 TEXT NOT NULL,
  account TEXT NOT NULL,
  date TEXT NOT NULL,
  settle TEXT,
  kind TEXT NOT NULL,
  sub TEXT,
  symbol TEXT,
  cusip TEXT,
  sec_type TEXT,
  quantity REAL,
  price REAL,
  amount REAL NOT NULL,
  fees REAL,
  funding TEXT,
  description TEXT
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS broker_txns_date ON broker_txns (date, account);
CREATE TABLE IF NOT EXISTS broker_lots (
  id INTEGER PRIMARY KEY,
  as_of TEXT,
  account TEXT NOT NULL,
  symbol TEXT NOT NULL,
  acquired TEXT,
  shares REAL NOT NULL,
  cost REAL,
  cost_per_share REAL,
  method TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_realized (
  id INTEGER PRIMARY KEY,
  account TEXT NOT NULL,
  symbol TEXT NOT NULL,
  acquired TEXT,
  sold TEXT NOT NULL,
  shares REAL NOT NULL,
  proceeds REAL,
  cost REAL,
  gain REAL,
  term TEXT,
  wash_disallowed REAL NOT NULL DEFAULT 0,
  method TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alpaca_assets (
  symbol TEXT PRIMARY KEY,
  name TEXT,
  exchange TEXT,
  tradable INTEGER NOT NULL,
  fetched_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS alpaca_bars (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  open REAL,
  high REAL,
  low REAL,
  close REAL NOT NULL,
  adj_close REAL,
  volume REAL,
  vwap REAL,
  PRIMARY KEY (symbol, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sec_shares (
  cik INTEGER NOT NULL,
  end TEXT NOT NULL,
  val REAL NOT NULL,
  accn TEXT,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (cik, end)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS public_stocks (
  rank INTEGER PRIMARY KEY,
  cik INTEGER NOT NULL,
  name TEXT NOT NULL,
  float_usd REAL NOT NULL,
  float_at TEXT NOT NULL,
  accn TEXT,
  symbol TEXT,
  source TEXT,
  first_bar TEXT,
  last_bar TEXT,
  state TEXT NOT NULL,
  trading INTEGER NOT NULL DEFAULT 0,
  fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS universe_daily (
  date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  cik INTEGER NOT NULL,
  name TEXT,
  exchange TEXT,
  close REAL NOT NULL,
  shares REAL NOT NULL,
  shares_end TEXT NOT NULL,
  market_cap REAL NOT NULL,
  dollar_volume REAL NOT NULL,
  PRIMARY KEY (date, symbol)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS filings_feed (
  accession TEXT PRIMARY KEY,
  cik INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  form TEXT NOT NULL,
  items TEXT NOT NULL,
  filed_at TEXT NOT NULL,
  filed_date TEXT,
  url TEXT,
  company TEXT,
  sector TEXT,
  materiality INTEGER NOT NULL,
  fetched_at TEXT NOT NULL,
  excerpt TEXT,
  excerpt_tries INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS filings_feed_queue ON filings_feed (materiality, filed_at);
CREATE TABLE IF NOT EXISTS filing_days (
  day TEXT PRIMARY KEY,
  ok INTEGER NOT NULL,
  fetched_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS filing_signals (
  accession TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  filed_at TEXT NOT NULL,
  form TEXT NOT NULL,
  items TEXT NOT NULL,
  scored_at TEXT NOT NULL,
  model TEXT NOT NULL,
  direction INTEGER NOT NULL CHECK (direction BETWEEN -2 AND 2),
  confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  event_type TEXT NOT NULL,
  horizon_days INTEGER NOT NULL,
  rationale TEXT,
  numbers_cited TEXT NOT NULL,
  run_id TEXT
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS insider_buys (
  accession TEXT NOT NULL,
  owner_cik INTEGER NOT NULL,
  issuer_cik INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  trans_date TEXT NOT NULL,
  filed_date TEXT NOT NULL,
  shares REAL NOT NULL,
  usd REAL NOT NULL,
  role TEXT NOT NULL,
  source TEXT NOT NULL,
  PRIMARY KEY (accession, owner_cik)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS insider_buys_symbol ON insider_buys (symbol, filed_date);
CREATE TABLE IF NOT EXISTS insider_quarters (
  quarter TEXT PRIMARY KEY,
  fetched_at TEXT NOT NULL,
  rows INTEGER NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS insider_form4_seen (
  accession TEXT PRIMARY KEY,
  rows INTEGER NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sec_frames (
  frame TEXT PRIMARY KEY,
  fetched_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS alpaca_history (
  symbol TEXT PRIMARY KEY,
  start TEXT NOT NULL,
  bars INTEGER NOT NULL,
  fetched_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS smallcap_months (
  symbol TEXT NOT NULL,
  month TEXT NOT NULL,
  market_cap REAL NOT NULL,
  dollar_volume REAL NOT NULL,
  PRIMARY KEY (symbol, month)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS eps_facts (
  cik INTEGER NOT NULL,
  start TEXT NOT NULL,
  end TEXT NOT NULL,
  val REAL NOT NULL,
  filed TEXT NOT NULL,
  form TEXT NOT NULL,
  accn TEXT,
  PRIMARY KEY (cik, start, end)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS earnings_releases (
  cik INTEGER NOT NULL,
  accepted TEXT NOT NULL,
  PRIMARY KEY (cik, accepted)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS earnings_ciks (
  cik INTEGER PRIMARY KEY,
  symbol TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  facts INTEGER NOT NULL,
  releases INTEGER NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS earnings_events (
  symbol TEXT NOT NULL,
  cik INTEGER NOT NULL,
  period_end TEXT NOT NULL,
  known TEXT NOT NULL,
  source TEXT NOT NULL,
  eps REAL NOT NULL,
  eps_prior REAL NOT NULL,
  price REAL NOT NULL,
  surprise REAL NOT NULL,
  PRIMARY KEY (cik, period_end)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS lane_variants (
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  title TEXT NOT NULL,
  params TEXT NOT NULL,
  hypothesis TEXT,
  registered_at TEXT NOT NULL,
  PRIMARY KEY (id, version)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS discount_signals (
  signal_id TEXT PRIMARY KEY,
  as_of TEXT NOT NULL,
  symbol TEXT NOT NULL,
  name TEXT,
  list TEXT NOT NULL CHECK (list IN ('held', 'watchlist', 'quality')),
  reason TEXT NOT NULL,
  price REAL NOT NULL,
  drop_from_high_pct REAL NOT NULL,
  move_z REAL,
  valuation TEXT NOT NULL,
  numbers TEXT NOT NULL,
  scanned_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS discount_signals_day ON discount_signals (as_of);
CREATE TABLE IF NOT EXISTS discount_cases (
  signal_id TEXT PRIMARY KEY,
  verdict TEXT NOT NULL CHECK (verdict IN ('buy', 'wait', 'avoid')),
  case_text TEXT NOT NULL,
  risks TEXT NOT NULL,
  confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  horizon_days INTEGER NOT NULL CHECK (horizon_days >= 1),
  numbers_cited TEXT NOT NULL,
  model TEXT NOT NULL,
  written_at TEXT NOT NULL,
  run_id TEXT,
  buy_if TEXT
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS discount_scans (
  as_of TEXT PRIMARY KEY,
  ran_at TEXT NOT NULL,
  scanned INTEGER NOT NULL,
  hits INTEGER NOT NULL,
  short_history TEXT
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS period_reviews (
  kind TEXT NOT NULL CHECK (kind IN ('day', 'week', 'month', 'year')),
  start TEXT NOT NULL,
  "end" TEXT NOT NULL,
  as_of TEXT NOT NULL,
  closed INTEGER NOT NULL,
  final INTEGER NOT NULL,
  version INTEGER NOT NULL,
  digest TEXT NOT NULL,
  pack TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  PRIMARY KEY (kind, "end")
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS period_debriefs (
  kind TEXT NOT NULL,
  "end" TEXT NOT NULL,
  pack_digest TEXT NOT NULL,
  body TEXT NOT NULL,
  written_at TEXT NOT NULL,
  model TEXT NOT NULL,
  run_id TEXT,
  PRIMARY KEY (kind, "end")
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS review_runs (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  ran_at TEXT NOT NULL,
  as_of TEXT NOT NULL,
  written INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS catalog_strategies (
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  title TEXT NOT NULL,
  mix TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  retired_at TEXT,
  PRIMARY KEY (id, version)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS paper_legs (
  date TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  symbol TEXT NOT NULL,
  qty REAL NOT NULL,
  client_order_id TEXT,
  filled_qty REAL,
  price REAL,
  status TEXT NOT NULL,
  PRIMARY KEY (date, strategy_id, version, symbol)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS paper_ledger_daily (
  strategy_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  date TEXT NOT NULL,
  cash REAL NOT NULL,
  invested REAL NOT NULL,
  value REAL NOT NULL,
  PRIMARY KEY (strategy_id, version, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS paper_orders (
  client_order_id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
  qty REAL NOT NULL,
  status TEXT NOT NULL,
  filled_qty REAL,
  filled_avg_price REAL,
  filled_at TEXT,
  submitted_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  alpaca_id TEXT,
  message TEXT
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS quotes_live (
  symbol TEXT NOT NULL,
  at TEXT NOT NULL,
  price REAL NOT NULL,
  prev_close REAL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (symbol, fetched_at)
);
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
  say TEXT,
  kind TEXT,
  job TEXT,
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
CREATE TABLE IF NOT EXISTS paper_portfolios (
  strategy_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  title TEXT,
  started TEXT NOT NULL,
  as_of TEXT NOT NULL,
  days INTEGER NOT NULL,
  value REAL,
  return_pct REAL,
  excess_pts REAL,
  status TEXT NOT NULL CHECK (status IN ('paper', 'eligible', 'retired')),
  summary TEXT,
  PRIMARY KEY (strategy_id, version)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS paper_positions (
  strategy_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  shares REAL NOT NULL,
  value REAL,
  PRIMARY KEY (strategy_id, version, symbol)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS paper_trades (
  strategy_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  shares REAL NOT NULL,
  price REAL NOT NULL,
  cost REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_verdicts (
  strategy_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  checkpoint INTEGER NOT NULL,
  as_of TEXT NOT NULL,
  verdict TEXT NOT NULL CHECK (verdict IN ('eligible', 'unproven', 'retired')),
  reason TEXT NOT NULL,
  excess_pts REAL,
  band_pts REAL,
  retire_pts REAL,
  luck REAL,
  tracking_error_pct REAL,
  obs INTEGER NOT NULL,
  events INTEGER,
  family_size INTEGER NOT NULL,
  decided_at TEXT NOT NULL,
  PRIMARY KEY (strategy_id, version, checkpoint)
);
CREATE TABLE IF NOT EXISTS signals (
  signal_id TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  as_of TEXT NOT NULL,
  value REAL,
  base_rate REAL,
  ci_low REAL,
  ci_high REAL,
  n_obs INTEGER,
  note TEXT,
  PRIMARY KEY (signal_id, scope_id, as_of)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS engine_views (
  name TEXT PRIMARY KEY,
  as_of TEXT NOT NULL,
  body TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS factors_daily (
  series TEXT NOT NULL,
  date TEXT NOT NULL,
  value REAL NOT NULL,
  PRIMARY KEY (series, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS french_returns (
  set_name TEXT NOT NULL,
  name TEXT NOT NULL,
  date TEXT NOT NULL,
  ret REAL NOT NULL,
  PRIMARY KEY (set_name, name, date)
) WITHOUT ROWID;
"""


QUOTES_LIVE = re.search(r"CREATE TABLE IF NOT EXISTS quotes_live \(.*?\);", SCHEMA, re.S).group(0)


HEALTH_COLUMNS = ("say", "kind", "job")


def apply(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    rebuild_quotes(conn)
    add_health_columns(conn)
    add_case_columns(conn)


def add_case_columns(conn: sqlite3.Connection) -> None:
    if "buy_if" not in {r[1] for r in conn.execute("PRAGMA table_info(discount_cases)")}:
        conn.execute("ALTER TABLE discount_cases ADD COLUMN buy_if TEXT")


def add_health_columns(conn: sqlite3.Connection) -> None:
    have = {r[1] for r in conn.execute("PRAGMA table_info(data_health)")}
    for name in HEALTH_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE data_health ADD COLUMN {name} TEXT")


def rebuild_quotes(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='quotes_live'").fetchone()
    if row is None or "WITHOUT ROWID" not in row[0].upper():
        return False
    conn.executescript(
        "BEGIN;"
        "DROP INDEX IF EXISTS quotes_live_fetched;"
        "ALTER TABLE quotes_live RENAME TO quotes_live_old;"
        f"{QUOTES_LIVE}"
        "INSERT INTO quotes_live SELECT symbol, at, price, prev_close, source, fetched_at FROM quotes_live_old;"
        "DROP TABLE quotes_live_old;"
        "CREATE INDEX quotes_live_fetched ON quotes_live (fetched_at);"
        "COMMIT;"
    )
    return True

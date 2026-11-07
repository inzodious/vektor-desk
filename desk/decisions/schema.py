SCHEMA = """
CREATE TABLE IF NOT EXISTS profile_versions (
  version INTEGER PRIMARY KEY,
  hash TEXT NOT NULL,
  source TEXT NOT NULL,
  body TEXT NOT NULL,
  warnings TEXT NOT NULL DEFAULT '[]',
  rules_version INTEGER NOT NULL,
  loaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rules_versions (
  version INTEGER PRIMARY KEY,
  hash TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decision_id TEXT
);
CREATE TABLE IF NOT EXISTS profile_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  checked_at TEXT NOT NULL,
  source TEXT NOT NULL,
  error TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  origin TEXT NOT NULL,
  run_id TEXT,
  kind TEXT NOT NULL,
  title TEXT,
  symbol TEXT,
  account TEXT,
  amount_usd REAL,
  shares REAL,
  funding TEXT,
  thesis TEXT,
  bear_case TEXT,
  invalidation TEXT,
  horizon TEXT,
  rule_served TEXT,
  confidence REAL,
  numbers_used TEXT NOT NULL DEFAULT '[]',
  sources TEXT NOT NULL DEFAULT '[]',
  order_ticket TEXT,
  skeptic TEXT,
  expires_at TEXT,
  status TEXT NOT NULL,
  status_reason TEXT,
  snoozed_until TEXT,
  override INTEGER NOT NULL DEFAULT 0,
  override_reason TEXT,
  preflight_status TEXT NOT NULL DEFAULT 'none',
  preflight TEXT,
  preflight_at TEXT,
  tax_impact TEXT,
  profile_version INTEGER,
  rules_version INTEGER,
  decided_at TEXT,
  placed_at TEXT,
  filled_at TEXT,
  fill TEXT,
  activity_id TEXT UNIQUE,
  CHECK (status IN ('proposed', 'snoozed', 'approved', 'placed', 'filled', 'done', 'dismissed', 'passed', 'expired', 'rejected', 'logged')),
  CHECK (preflight_status IN ('none', 'pending', 'clear', 'flagged', 'blocked', 'error'))
);
CREATE INDEX IF NOT EXISTS decisions_status ON decisions (status, created_at);
CREATE INDEX IF NOT EXISTS decisions_origin ON decisions (origin, created_at);
CREATE INDEX IF NOT EXISTS decisions_symbol ON decisions (symbol, created_at);
CREATE TABLE IF NOT EXISTS decision_events (
  seq INTEGER PRIMARY KEY,
  decision_id TEXT NOT NULL REFERENCES decisions (id),
  at TEXT NOT NULL,
  event TEXT NOT NULL,
  reason TEXT,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS decision_events_decision ON decision_events (decision_id, seq);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
  id INTEGER PRIMARY KEY,
  desk TEXT NOT NULL,
  trigger TEXT NOT NULL DEFAULT 'schedule',
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  model TEXT,
  effort TEXT,
  turns INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_tokens INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  cost_estimate REAL NOT NULL DEFAULT 0,
  note TEXT
);
CREATE INDEX IF NOT EXISTS agent_runs_desk ON agent_runs (desk, started_at);
CREATE TABLE IF NOT EXISTS agent_settings (
  desk TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_briefs (
  run_id INTEGER PRIMARY KEY REFERENCES agent_runs (id),
  desk TEXT NOT NULL,
  as_of TEXT,
  digest TEXT NOT NULL,
  profile_version TEXT,
  summary TEXT NOT NULL,
  answer TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_briefs_desk ON agent_briefs (desk, run_id);
CREATE TABLE IF NOT EXISTS agent_dossiers (
  id INTEGER PRIMARY KEY,
  symbol TEXT NOT NULL,
  run_id INTEGER NOT NULL REFERENCES agent_runs (id),
  dossier TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_dossiers_symbol ON agent_dossiers (symbol, id);
CREATE TABLE IF NOT EXISTS agent_holding_tries (
  id INTEGER PRIMARY KEY,
  symbol TEXT NOT NULL,
  status TEXT NOT NULL,
  note TEXT,
  run_id INTEGER,
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS agent_holding_tries_symbol ON agent_holding_tries (symbol, id);
CREATE TABLE IF NOT EXISTS agent_requests (
  id INTEGER PRIMARY KEY,
  desk TEXT NOT NULL,
  question TEXT NOT NULL,
  symbol TEXT,
  run_now INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'console',
  status TEXT NOT NULL DEFAULT 'queued',
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  run_id INTEGER REFERENCES agent_runs (id),
  answer TEXT,
  note TEXT
);
CREATE INDEX IF NOT EXISTS agent_requests_status ON agent_requests (status, run_now, id);
CREATE TABLE IF NOT EXISTS agent_triggers_seen (
  as_of TEXT NOT NULL,
  kind TEXT NOT NULL,
  scope_id TEXT NOT NULL,
  request_id INTEGER REFERENCES agent_requests (id),
  PRIMARY KEY (as_of, kind, scope_id)
);
CREATE TABLE IF NOT EXISTS agent_plan_pins (
  symbol TEXT NOT NULL,
  step_id TEXT NOT NULL,
  step TEXT NOT NULL,
  created_at TEXT NOT NULL,
  delivered_at TEXT,
  PRIMARY KEY (symbol, step_id)
);
"""

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
"""

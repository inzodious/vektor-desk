SCHEMA = """
CREATE TABLE IF NOT EXISTS notify_log (
  seq INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  topic TEXT NOT NULL,
  priority INTEGER NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  click TEXT,
  key TEXT,
  status TEXT NOT NULL,
  error TEXT,
  CHECK (status IN ('sent', 'failed', 'demo', 'off', 'muted'))
);
CREATE INDEX IF NOT EXISTS notify_log_key ON notify_log (key, at);
CREATE INDEX IF NOT EXISTS notify_log_at ON notify_log (at);
CREATE TABLE IF NOT EXISTS notify_topics (
  topic TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);
"""

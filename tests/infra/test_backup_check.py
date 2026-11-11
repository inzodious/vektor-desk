import json
import sqlite3

import pytest

import desk.backup as backup

QUOTES = "CREATE TABLE quotes_live (symbol TEXT NOT NULL, price REAL NOT NULL, source TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (symbol, at)) WITHOUT ROWID"
ALARM = ["NULL value in quotes_live.at", "NULL value in quotes_live.price", "NULL value in quotes_live.source"] * 40


def desk_db(cfg, rows=((("SYNA"), 10.0, "test", "2026-11-10T21:00:00Z"),)):
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.desk_db)
    conn.execute(QUOTES)
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    conn.executemany("INSERT INTO quotes_live VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def says(monkeypatch, lines):
    monkeypatch.setattr(backup, "_report", lambda conn, pragma: list(lines))


def test_the_known_false_alarm_is_accepted_and_recorded(cfg, tmp_path, monkeypatch, capsys):
    desk_db(cfg)
    says(monkeypatch, ALARM)
    done = backup.snapshot(cfg.data_dir, tmp_path / "out")
    assert done[0]["db"] == "desk.db" and done[0]["false_alarm"] == ["quotes_live.at", "quotes_live.price", "quotes_live.source"]
    monkeypatch.setenv("DESK_DATA_DIR", str(cfg.data_dir))
    assert backup.main(["--out", str(tmp_path / "again")]) == 0
    said = json.loads(capsys.readouterr().out)
    assert said["ok"] and "known false alarm" in said["notes"][0] and said["notes"][0].startswith("desk.db: SQLite reported NULLs in quotes_live.at")
    report = backup.verify(tmp_path / "out")
    assert not [p for p in report["problems"] if "integrity" in p] and "quotes_live.price" in report["notes"][0]


def test_a_clean_copy_carries_no_note(cfg, tmp_path):
    desk_db(cfg)
    done = backup.snapshot(cfg.data_dir, tmp_path / "out")
    assert "false_alarm" not in done[0] and backup.verify(tmp_path / "out")["notes"] == []


def test_real_nulls_still_fail_the_backup(cfg, tmp_path):
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.desk_db)
    conn.execute("CREATE TABLE quotes_live (symbol TEXT PRIMARY KEY, price REAL)")
    conn.execute("INSERT INTO quotes_live VALUES ('SYNA', NULL)")
    conn.execute("PRAGMA writable_schema=ON")
    conn.execute("UPDATE sqlite_master SET sql='CREATE TABLE quotes_live (symbol TEXT PRIMARY KEY, price REAL NOT NULL)' WHERE name='quotes_live'")
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.DatabaseError, match="desk.db copy failed its check: NULL value in quotes_live.price"):
        backup.snapshot(cfg.data_dir, tmp_path / "out")


@pytest.mark.parametrize(
    "lines",
    [
        [*ALARM, "row 7 missing from index quotes_idx"],
        ["*** in database main ***", "Page 12 is never used"],
        ["NULL value in quotes_live.at", "NULL value in gone.at"],
        [],
    ],
)
def test_anything_else_in_the_report_still_fails(cfg, tmp_path, monkeypatch, lines):
    desk_db(cfg)
    says(monkeypatch, lines)
    with pytest.raises(sqlite3.DatabaseError, match="copy failed its check"):
        backup.snapshot(cfg.data_dir, tmp_path / "out")


def test_a_report_that_hits_the_line_limit_fails(cfg, tmp_path, monkeypatch):
    desk_db(cfg)
    monkeypatch.setattr(backup, "CHECK_LINES", len(ALARM))
    says(monkeypatch, ALARM)
    with pytest.raises(sqlite3.DatabaseError, match="and 119 more lines"):
        backup.snapshot(cfg.data_dir, tmp_path / "out")

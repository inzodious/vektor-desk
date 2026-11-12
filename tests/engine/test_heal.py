import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from desk import jobrun
from desk.db import connect
from desk.engine import core, heal, schema
from desk.engine.__main__ import run_holdings, run_restate
from desk.engine.backfill import NO_PRICES
from desk.engine.source import open_mirror
from desk.runlock import job_lock
from desk.scheduler import package_jobs
from tests.engine.test_live_shapes import FRI, MON, MON_NIGHT, SAT_NOW, THU, THURSDAY, add_bars, seed_like_the_box

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
KEYS = ("TIINGO_API_KEY", "FINNHUB_API_KEY", "FRED_API_KEY", "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")
NOT_PLAIN = re.compile(r"Fix:|\d{4}-\d{2}-\d{2}|`|[A-Z]{3,}_[A-Z_]{2,}|snapshot|[Mm]irror|N-PORT|data_health|backfill|python -m|\bjob\b")


def keyed(monkeypatch, on=True):
    for key in KEYS:
        monkeypatch.setenv(key, "k") if on else monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DESK_SEC_USER_AGENT", "Desk test@example.com") if on else monkeypatch.delenv("DESK_SEC_USER_AGENT", raising=False)


def checks(cfg, now, store=False):
    mirror = open_mirror(cfg)
    desk = connect(cfg.desk_db)
    try:
        out = core.compute(cfg, mirror, desk, now=now)
        if store:
            core.store(desk, out)
    finally:
        desk.close()
        mirror.close()
    return {h[1]: {"status": h[2], "detail": h[3], "say": h[4], "kind": h[5], "job": h[6]} for h in out.health}


def plan_funds_have_no_price(cfg):
    desk = connect(cfg.desk_db)
    with desk:
        for sym in ("P10001", "Q20002"):
            desk.execute(
                "INSERT OR REPLACE INTO market_symbols (symbol, role, priority, added_at, fetched_at, error) VALUES (?, 'held', 0, ?, ?, ?)",
                (sym, "2026-11-06T00:00:00+00:00", "2026-11-10T02:10:00+00:00", f"{NO_PRICES} for {sym}"),
            )
    desk.close()


def late_funds(cfg, late=("FXAIX", "FTIHX")):
    add_bars(cfg, [(s, d, px) for s, px in THURSDAY.items() for d in (THU, FRI, MON) if not (d == MON and s in late)])
    run_holdings(cfg)


def health_rows(cfg, rows, as_of="2026-11-11"):
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    with desk:
        desk.execute("DELETE FROM data_health")
        desk.executemany(
            "INSERT INTO data_health (as_of, check_name, status, detail, say, kind, job) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(as_of, name, status, f"long {name}", f"Plain {name}.", kind, job) for name, status, kind, job in rows],
        )
    desk.close()


def engine_jobs():
    return package_jobs(["engine", "mirror"])


def beat(cfg, at):
    path = jobrun.alive_file(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(jobrun.stamp(at))


def asked(cfg):
    folder = jobrun.requests_dir(cfg)
    return sorted(p.stem for p in folder.glob("*.json")) if folder.exists() else []


# ---- Sentences ----


def test_a_fund_price_a_day_late_is_one_short_sentence_and_plan_funds_are_never_a_problem(cfg, mirror, monkeypatch):
    seed_like_the_box(mirror)
    keyed(monkeypatch)
    late_funds(cfg)
    plan_funds_have_no_price(cfg)
    closes = checks(cfg, MON_NIGHT)["closes"]
    assert closes["say"] == "Two fund prices for Monday are not out yet. The desk checks every hour."
    assert (closes["status"], closes["kind"], closes["job"]) == ("warn", heal.FIXES, None)
    assert "P10001, Q20002 have no market price anywhere" in closes["detail"] and "FTIHX, FXAIX stop at" in closes["detail"]
    desk = connect(cfg.desk_db)
    with desk:
        desk.execute("INSERT INTO sym_profiles (symbol, name, fetched_at) VALUES ('FXAIX', 'Fidelity 500 Index Fund', '2026-11-01T00:00:00+00:00')")
    desk.close()
    add_bars(cfg, [("FTIHX", MON, THURSDAY["FTIHX"])])
    run_holdings(cfg)
    one = checks(cfg, MON_NIGHT)["closes"]
    assert one["say"] == "The price of Fidelity 500 Index Fund for Monday is not out yet. The desk checks every hour."
    add_bars(cfg, [("FXAIX", MON, THURSDAY["FXAIX"])])
    run_holdings(cfg)
    done = checks(cfg, MON_NIGHT)["closes"]
    assert (done["status"], done["say"], done["kind"], done["job"]) == ("ok", "Every holding has a price for Monday.", None, None)


def test_prices_more_than_a_day_behind_are_asked_for_again_without_a_button(cfg, mirror, monkeypatch):
    seed_like_the_box(mirror)
    keyed(monkeypatch)
    late_funds(cfg)
    plan_funds_have_no_price(cfg)
    desk = connect(cfg.desk_db)
    with desk:
        desk.execute("DELETE FROM price_bars WHERE symbol IN ('FXAIX', 'FTIHX') AND date=?", (FRI,))
    desk.close()
    run_holdings(cfg)
    closes = checks(cfg, MON_NIGHT)["closes"]
    assert closes["say"] == "Two fund prices are more than a day behind. The desk is asking for them again now."
    assert (closes["kind"], closes["job"]) == (heal.FIXES, heal.BACKFILL) and "run Backfill" in closes["detail"]
    keyed(monkeypatch, on=False)
    bare = checks(cfg, MON_NIGHT)["closes"]
    assert (bare["kind"], bare["job"]) == (heal.NEEDS, None) and bare["say"].endswith("the desk needs you to set the Tiingo key in Settings, Data, Keys.")


def test_no_sentence_he_reads_has_a_date_code_a_table_or_a_method_in_it(cfg, mirror, monkeypatch):
    seed_like_the_box(mirror)
    keyed(monkeypatch, on=False)
    run_holdings(cfg)
    bare = checks(cfg, SAT_NOW)
    keyed(monkeypatch)
    late_funds(cfg)
    full = checks(cfg, MON_NIGHT)
    for rows in (bare, full):
        assert len(rows) >= 10
        for name, c in rows.items():
            assert not NOT_PLAIN.search(c["say"]), (name, c["say"])
            assert c["say"].endswith(".") and len(c["say"]) <= 220, (name, c["say"])
            assert (c["kind"] in heal.KINDS) == (c["status"] != "ok") and (c["job"] is None or c["status"] != "ok"), name
    assert {n for n, c in bare.items() if c["kind"] == heal.NEEDS} >= {"market_keys", "shares", "marginal_rate", "closes", "research"}
    assert bare["market_keys"]["say"] == "Six data sources are not set up, so parts of the desk are off. Add them in Settings, Data, Keys."
    assert full["freshness"] == full["freshness"] | {"status": "fail", "kind": heal.BLOCKS, "job": heal.ACCOUNTS}
    assert full["freshness"]["say"] == "Your accounts were last read 61 hours ago, so these numbers are old. The desk is reading them again now."
    assert (full["research"]["kind"], full["research"]["job"]) == (heal.FIXES, heal.RESEARCH)
    assert (full["value"]["status"], full["value"]["kind"], full["value"]["job"]) == ("warn", heal.FIXES, None)
    assert full["value"]["say"].endswith("It clears with the next account read.")


# ---- What counts ----


def test_a_warning_that_clears_by_itself_does_not_colour_the_overall_state():
    ok = {"status": "ok", "kind": None}
    wait = {"status": "warn", "kind": heal.FIXES}
    you = {"status": "warn", "kind": heal.NEEDS}
    bad = {"status": "fail", "kind": heal.BLOCKS}
    assert heal.overall([ok, wait, wait]) == "ok" and heal.overall([ok, wait, you]) == "warn" and heal.overall([wait, you, bad]) == "fail"
    assert heal.overall([{"status": "warn", "kind": None}]) == "warn" and heal.overall([{"status": "fail", "kind": heal.FIXES}]) == "fail"
    assert heal.kind_of("ok", heal.NEEDS) is None and heal.kind_of("fail", None) == heal.BLOCKS and heal.kind_of("warn", "odd") == heal.NEEDS


def test_the_health_endpoint_gives_the_plain_sentence_the_kind_and_what_counts(cfg, app_client):
    health_rows(cfg, [("closes", "warn", heal.FIXES, None), ("value", "warn", heal.FIXES, None), ("freshness", "ok", None, None)])
    client = app_client(packages=["engine"])
    body = client.get("/api/engine/health").json()
    assert body["status"] == "ok" and body["kinds"] == {heal.FIXES: 2, heal.NEEDS: 0, heal.BLOCKS: 0}
    closes = next(c for c in body["checks"] if c["check_name"] == "closes")
    assert closes == {
        "check_name": "closes",
        "status": "warn",
        "detail": "Plain closes.",
        "kind": heal.FIXES,
        "counts": False,
        "job": None,
        "heal": None,
        "diagnosis": "long closes",
    }
    health_rows(cfg, [("closes", "warn", heal.FIXES, None), ("shares", "warn", heal.NEEDS, None)])
    assert client.get("/api/engine/health").json()["status"] == "warn"
    health_rows(cfg, [("closes", "warn", heal.FIXES, None), ("freshness", "fail", heal.BLOCKS, heal.ACCOUNTS)])
    body = client.get("/api/engine/health").json()
    assert body["status"] == "fail" and body["kinds"][heal.BLOCKS] == 1


def test_rows_written_before_this_build_still_read_and_the_table_gains_its_columns(cfg, app_client):
    desk = sqlite3.connect(cfg.desk_db)
    desk.executescript(
        "CREATE TABLE data_health (as_of TEXT NOT NULL, check_name TEXT NOT NULL, status TEXT NOT NULL, detail TEXT, "
        "PRIMARY KEY (as_of, check_name)) WITHOUT ROWID;"
        "INSERT INTO data_health VALUES ('2026-11-11', 'closes', 'warn', 'Closes for FXAIX stop at 2026-11-10.');"
    )
    desk.close()
    body = app_client(packages=["engine"]).get("/api/engine/health").json()
    assert body["status"] == "warn" and body["checks"][0]["detail"] == "Closes for FXAIX stop at 2026-11-10." and body["checks"][0]["kind"] == heal.NEEDS
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    schema.apply(desk)
    assert {r[1] for r in desk.execute("PRAGMA table_info(data_health)")} >= {"detail", "say", "kind", "job"}
    desk.close()
    jobrun.heartbeat(cfg)
    assert heal.run(cfg, now=jobrun.now_utc(), jobs=engine_jobs())["asked"] == [heal.DAILY]


# ---- The desk asks for the job itself ----


def test_every_job_the_desk_may_ask_for_exists_under_that_name():
    known = jobrun.catalogue(engine_jobs())
    assert set(heal.COOLDOWN) <= set(known) and set(heal.FOLLOW) | set(heal.ESCALATE) <= set(heal.COOLDOWN)
    assert all(wait >= timedelta(minutes=30) for wait in heal.COOLDOWN.values())


def test_a_failing_check_gets_its_job_asked_for_once_and_not_again_inside_the_cool_down(cfg):
    rows = [("closes", "warn", heal.FIXES, heal.BACKFILL), ("freshness", "fail", heal.BLOCKS, heal.ACCOUNTS), ("value", "warn", heal.FIXES, None)]
    health_rows(cfg, rows)
    down = heal.run(cfg, now=NOW, jobs=engine_jobs())
    assert down == {"asked": [], "waiting": {heal.BACKFILL: "scheduler_down", heal.ACCOUNTS: "scheduler_down"}} and asked(cfg) == []
    alive = NOW + timedelta(minutes=5)
    beat(cfg, alive)
    first = heal.run(cfg, now=alive, jobs=engine_jobs())
    assert first == {"asked": [heal.BACKFILL, heal.ACCOUNTS], "waiting": {}} and asked(cfg) == [heal.BACKFILL, heal.ACCOUNTS]
    assert json.loads((jobrun.requests_dir(cfg) / "mirror.json").read_text())["client"] == "desk"
    again = heal.run(cfg, now=alive + timedelta(minutes=5), jobs=engine_jobs())
    assert again["asked"] == [] and set(again["waiting"]) == {heal.BACKFILL, heal.ACCOUNTS}
    beat(cfg, alive + timedelta(minutes=61))
    queued = heal.run(cfg, now=alive + timedelta(minutes=61), jobs=engine_jobs())
    assert queued == {"asked": [], "waiting": {heal.BACKFILL: "queued", heal.ACCOUNTS: "queued"}}
    assert [name for name, _ in jobrun.take_requests(cfg)] == [heal.BACKFILL, heal.ACCOUNTS]
    lock = sorted(jobrun.catalogue(engine_jobs())[heal.ACCOUNTS].locks)[0]
    with job_lock(lock, cfg=cfg):
        busy = heal.run(cfg, now=alive + timedelta(minutes=62), jobs=engine_jobs())
    assert busy["asked"] == [heal.BACKFILL] and busy["waiting"] == {heal.ACCOUNTS: "running"}
    state = heal.read_state(cfg)
    assert state[heal.BACKFILL]["attempts"] == 2 and state[heal.ACCOUNTS]["attempts"] == 1 and state[heal.BACKFILL]["checks"] == ["closes"]


def test_after_three_tries_the_desk_slows_down_and_says_so_for_prices_only(cfg, app_client):
    health_rows(cfg, [("closes", "warn", heal.FIXES, heal.BACKFILL), ("lookthrough", "warn", heal.FIXES, heal.LOOKTHROUGH)])
    at = NOW
    for i in range(3):
        beat(cfg, at + timedelta(hours=25 * i))
        assert heal.run(cfg, now=at + timedelta(hours=25 * i), jobs=engine_jobs())["asked"] == [heal.BACKFILL, heal.LOOKTHROUGH]
        jobrun.take_requests(cfg)
    beat(cfg, at + timedelta(hours=52))
    later = heal.run(cfg, now=at + timedelta(hours=52), jobs=engine_jobs())
    assert later["asked"] == [] and set(later["waiting"]) == {heal.BACKFILL, heal.LOOKTHROUGH}
    beat(cfg, at + timedelta(hours=57))
    assert heal.run(cfg, now=at + timedelta(hours=57), jobs=engine_jobs())["asked"] == [heal.BACKFILL]
    jobrun.take_requests(cfg)
    body = app_client(packages=["engine"]).get("/api/engine/health").json()
    closes, look = (next(c for c in body["checks"] if c["check_name"] == n) for n in ("closes", "lookthrough"))
    assert closes["kind"] == heal.NEEDS and closes["counts"] and closes["heal"] == closes["heal"] | {"job": heal.BACKFILL, "attempts": 4, "stuck": True}
    assert closes["detail"] == "Plain closes. The desk has tried 4 times and it has not cleared. Settings, Box shows why."
    assert look["kind"] == heal.FIXES and not look["counts"] and look["detail"] == "Plain lookthrough." and look["heal"]["stuck"]
    assert body["status"] == "warn"


def test_a_blocking_check_the_desk_could_not_fix_says_so_instead_of_saying_it_is_on_it(cfg, app_client):
    health_rows(cfg, [("freshness", "fail", heal.BLOCKS, heal.ACCOUNTS), ("research", "warn", heal.FIXES, heal.RESEARCH)])
    heal._write_state(
        cfg, {heal.ACCOUNTS: {"asked_at": "2026-11-12T12:00:00Z", "attempts": 3}, heal.RESEARCH: {"asked_at": "2026-11-11T12:00:00Z", "attempts": 5}}
    )
    body = app_client(packages=["engine"]).get("/api/engine/health").json()
    fresh, research = (next(c for c in body["checks"] if c["check_name"] == n) for n in ("freshness", "research"))
    assert fresh["kind"] == heal.BLOCKS and fresh["detail"] == "Plain freshness. The desk has tried 3 times and it has not cleared. Settings, Box shows why."
    assert research["kind"] == heal.FIXES and research["detail"] == "Plain research." and not research["counts"]


def test_once_the_fixing_job_has_run_the_numbers_are_asked_for_and_a_clear_check_is_forgotten(cfg):
    health_rows(cfg, [("freshness", "fail", heal.BLOCKS, heal.ACCOUNTS)])
    at = NOW
    beat(cfg, at + timedelta(minutes=10))
    assert heal.run(cfg, now=at, jobs=engine_jobs())["asked"] == [heal.ACCOUNTS]
    jobrun.take_requests(cfg)
    assert heal.run(cfg, now=at + timedelta(minutes=5), jobs=engine_jobs())["asked"] == []
    jobrun.record(
        cfg, heal.ACCOUNTS, {"started": jobrun.stamp(at + timedelta(seconds=10)), "finished": jobrun.stamp(at + timedelta(minutes=6)), "result": "ok"}
    )
    after = heal.run(cfg, now=at + timedelta(minutes=10), jobs=engine_jobs())
    assert after["asked"] == [heal.DAILY] and asked(cfg) == [heal.DAILY]
    jobrun.take_requests(cfg)
    assert heal.run(cfg, now=at + timedelta(minutes=15), jobs=engine_jobs())["asked"] == []
    health_rows(cfg, [("freshness", "ok", None, None)])
    assert heal.run(cfg, now=at + timedelta(minutes=20), jobs=engine_jobs()) == {"asked": [], "waiting": {}} and heal.read_state(cfg) == {}


def test_the_five_minute_catch_up_does_the_asking_and_a_dry_run_asks_for_nothing(cfg, mirror, monkeypatch):
    seed_like_the_box(mirror)
    keyed(monkeypatch)
    run_holdings(cfg)
    assert checks(cfg, MON_NIGHT, store=True)["freshness"]["job"] == heal.ACCOUNTS
    jobrun.heartbeat(cfg)
    monkeypatch.setenv("DESK_ENGINE_DRY_RUN", "1")
    assert "heal" not in run_restate(cfg) and asked(cfg) == []
    monkeypatch.delenv("DESK_ENGINE_DRY_RUN")
    ran = run_restate(cfg)
    assert heal.ACCOUNTS in ran["heal"]["asked"] and heal.ACCOUNTS in asked(cfg)
    quiet = run_restate(cfg)
    assert "heal" not in quiet


@pytest.mark.parametrize("gone", ["no table", "no file"])
def test_with_no_health_yet_nothing_is_asked(cfg, gone):
    if gone == "no table":
        sqlite3.connect(cfg.desk_db).close()
    assert heal.run(cfg, now=NOW, jobs=engine_jobs()) == {"asked": [], "waiting": {}}

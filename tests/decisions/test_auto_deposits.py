from datetime import UTC, date, datetime, timedelta

import pytest

from desk.decisions import alerts as alerting
from desk.decisions import deposits_landed, upcoming_deposits
from desk.decisions.alerts import send_alerts
from desk.decisions.plan import deposit_series
from desk.decisions.profile import main, parse
from desk.decisions.starter import StarterError, deposits_block, switch_to_auto

NOW = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


@pytest.fixture
def captured(monkeypatch):
    sent = []
    monkeypatch.setattr(alerting, "publish", lambda topic, title, body="", priority="default", **kw: sent.append({"title": title, "body": body, **kw}) or True)
    return sent


def _biweekly(mirror, start: date, n: int, *, account="hsa-0200", amounts=(183,), prefix="h"):
    for i in range(n):
        day = start + timedelta(days=14 * i)
        for j, amount in enumerate(amounts):
            mirror(f"{prefix}{i}-{j}", date=day.isoformat(), accountKey=account, kind="deposit", action="CONTRIBUTION", amount=amount)


# ---- Auto mode ----


def test_auto_is_the_default_and_predicts_a_clear_series(cfg, mirror):
    _biweekly(mirror, date(2026, 6, 5), 12)
    mode, series = deposit_series(cfg, now=NOW)
    assert mode == "auto" and [(s["id"], s["cadence"], s["amount_usd"], s["observed"]) for s in series] == [("hsa", "biweekly", 183, 12)]
    items = upcoming_deposits(cfg, days=20, now=NOW)
    assert [(d["date"], d["status"]) for d in items] == [("2026-11-06", "landed"), ("2026-11-20", "expected"), ("2026-12-04", "expected")]
    assert all(d["mode"] == "auto" and d["scheduled"] for d in items)


def test_irregular_money_in_is_never_expected_late_or_missed(cfg, mirror, captured):
    for rid, day, amount in [("a", "2026-05-20", 3000), ("b", "2026-07-02", 3000), ("c", "2026-09-28", 1500), ("d", "2026-11-12", 2800)]:
        mirror(rid, date=day, accountKey="individual-6200", kind="deposit", action="EFT RECEIVED", amount=amount)
    assert deposit_series(cfg, now=NOW) == ("auto", [])
    items = upcoming_deposits(cfg, days=60, now=NOW)
    assert [(d["id"], d["status"], d["scheduled"]) for d in items] == [("money-in-d", "landed", False)]
    assert [d["amount_usd"] for d in deposits_landed(cfg, since="2026-11-10", now=NOW)] == [2800]
    send_alerts(cfg, now=NOW)
    assert not [m for m in captured if "deposit" in m.get("key", "")]


def test_same_day_amounts_combine_into_one_stream(cfg, mirror):
    _biweekly(mirror, date(2026, 6, 5), 12, amounts=(146, 38))
    _, series = deposit_series(cfg, now=NOW)
    assert [(s["cadence"], s["amount_usd"]) for s in series] == [("biweekly", 184)]
    landed = deposits_landed(cfg, since="2026-11-01", now=NOW)
    assert len(landed) == 1 and landed[0]["landed"]["activity_ids"] == ["h11-0", "h11-1"]
    block = deposits_block(cfg, today=NOW.date())
    notes = [line for line in block.splitlines() if line.startswith("# - ")]
    assert len(notes) == len(set(notes)) and "add deposits by hand" not in block
    assert parse(block)[0]["deposits"] == [{"id": "hsa", "account": "hsa-0200", "cadence": "biweekly", "anchor": "2026-11-06", "amount_usd": 184}]


def test_a_stopped_series_goes_quiet(cfg, mirror, captured):
    for i, day in enumerate(["2026-06-03", "2026-07-03", "2026-08-03", "2026-09-03"]):
        mirror(f"m{i}", date=day, accountKey="individual-6200", kind="deposit", action="EFT RECEIVED", amount=3000)
    assert deposit_series(cfg, now=NOW) == ("auto", [])
    assert upcoming_deposits(cfg, days=60, now=NOW) == []
    send_alerts(cfg, now=NOW)
    assert captured == []


def test_late_needs_three_observations_and_reads_gently(cfg, mirror, captured):
    for i, day in enumerate(["2026-08-03", "2026-09-03", "2026-10-05"]):
        mirror(f"m{i}", date=day, accountKey="individual-6200", kind="deposit", action="EFT RECEIVED", amount=3000)
    late = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
    assert [(d["date"], d["status"]) for d in upcoming_deposits(cfg, days=0, now=late)] == [("2026-11-03", "late")]
    send_alerts(cfg, now=late)
    (msg,) = [m for m in captured if m["key"].startswith("deposit-late")]
    assert msg["title"] == "Deposit individual hasn't shown up yet" and "on purpose, there's nothing to do" in msg["body"]
    assert "miss" not in (msg["title"] + msg["body"]).lower()


def test_a_listed_schedule_still_overrides(cfg, mirror):
    _biweekly(mirror, date(2026, 6, 5), 12)
    (cfg.data_dir / "desk.yaml").write_text("deposits: []\n")
    assert deposit_series(cfg, now=NOW) == ("listed", [])
    assert {d["scheduled"] for d in upcoming_deposits(cfg, days=20, now=NOW)} == {False}


def test_profile_api_resolves_auto_for_the_plan_page(cfg, mirror, app_client):
    _biweekly(mirror, date.today() - timedelta(days=14 * 11), 12)
    client = app_client(packages=["decisions"])
    body = client.get("/api/decisions/profile").json()
    assert body["deposits_mode"] == "auto" and [d["id"] for d in body["profile"]["deposits"]] == ["hsa"]
    status = client.get("/api/decisions/profile/status").json()
    assert status["deposits_mode"] == "auto" and status["deposits"] == 1


# ---- Switching an existing file ----


OLD = """# Vektor Desk profile, drafted from the mirror by `python -m desk.decisions.profile init`.
# Drafted 2026-11-07. Check every value, then edit freely: each change becomes a new profile version.
#
# - hsa-0200: biweekly from 12 deposits since 2026-05-11
# - Agents stay off until you set agents.enabled: true

deposits:
- id: hsa
  account: hsa-0200
  cadence: biweekly
  anchor: '2026-11-06'
  amount_usd: 183
# keep this note
tax:
  wash_sale_accounts:
  - hsa-0200
agents:
  enabled: true

# ---- Still at the defaults: uncomment and change to set them ----

# risk_level: 3
"""


def test_switch_to_auto_keeps_a_backup_and_runs_twice_safely(cfg):
    path = cfg.data_dir / "desk.yaml"
    path.write_text(OLD)
    changed, message = switch_to_auto(path)
    assert changed and "desk.yaml.bak" in message
    text = path.read_text()
    assert (cfg.data_dir / "desk.yaml.bak").read_text() == OLD
    data, _ = parse(text)
    assert data["deposits"] == "auto" and data["tax"]["wash_sale_accounts"] == ["hsa-0200"] and data["agents"]["enabled"] is True
    assert "Agents stay off" not in text and "amount_usd: 183" not in text
    assert "# keep this note" in text and "# risk_level: 3" in text and text.startswith(OLD.split("\n#\n")[0])
    assert switch_to_auto(path) == (False, f"{path} already uses deposits: auto. Nothing changed.")
    assert path.read_text() == text and (cfg.data_dir / "desk.yaml.bak").read_text() == OLD


def test_switch_adds_auto_when_the_section_is_missing_and_refuses_no_file(cfg):
    path = cfg.data_dir / "desk.yaml"
    with pytest.raises(StarterError, match="doesn't exist"):
        switch_to_auto(path)
    path.write_text("risk_level: 2\n")
    assert switch_to_auto(path)[0] is True
    assert path.read_text() == "risk_level: 2\n\ndeposits: auto\n"


def test_cli_deposits_auto(cfg, monkeypatch, capsys):
    monkeypatch.setattr("desk.decisions.profile.Config.from_env", lambda: cfg)
    (cfg.data_dir / "desk.yaml").write_text(OLD)
    assert main(["deposits-auto"]) == 0 and "now uses deposits: auto" in capsys.readouterr().out
    assert main(["deposits-auto"]) == 0 and "Nothing changed" in capsys.readouterr().out

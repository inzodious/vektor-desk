from datetime import UTC, date, datetime

import pytest

from desk.decisions import DecisionError, add_event, approve, calendar_events, create_proposal, delete_event, deposits_landed, upcoming_deposits
from desk.decisions.plan import schedule_dates
from desk.decisions.profile import ProfileError, parse

SCHEDULE = """
deposits:
  - id: payday
    account: brokerage
    cadence: biweekly
    anchor: "2026-11-06"
    amount_usd: 500
  - id: hsa
    account: hsa
    cadence: semimonthly
    days: [1, 15]
    amount_usd: 50
"""
NOW = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)


@pytest.fixture
def scheduled(cfg):
    (cfg.data_dir / "desk.yaml").write_text(SCHEDULE)
    return cfg


def test_schedule_dates_shift_weekends():
    biweekly = {"id": "p", "cadence": "biweekly", "anchor": "2026-11-06"}
    assert schedule_dates(biweekly, date(2026, 11, 1), date(2026, 12, 10)) == [date(2026, 11, 6), date(2026, 11, 20), date(2026, 12, 4)]
    monthly = {"id": "m", "cadence": "monthly", "days": [31]}
    assert schedule_dates(monthly, date(2027, 1, 1), date(2027, 3, 31)) == [date(2027, 1, 29), date(2027, 2, 26), date(2027, 3, 31)]
    after = {"id": "s", "cadence": "semimonthly", "days": [1, 15], "weekend": "after", "until": "2026-11-30"}
    assert schedule_dates(after, date(2026, 11, 1), date(2026, 12, 31)) == [date(2026, 11, 2), date(2026, 11, 16)]


@pytest.mark.parametrize(
    "text, message",
    [
        ("deposits:\n  - {id: a, cadence: daily}\n", "cadence must be one of"),
        ("deposits:\n  - {id: a, cadence: biweekly}\n", "needs an anchor"),
        ("deposits:\n  - {id: a, cadence: semimonthly, days: [1]}\n", "must list 2 days"),
        ("deposits:\n  - {id: a, cadence: weekly, anchor: someday}\n", "must be a date"),
        ("deposits:\n  - {id: a, cadence: monthly, days: [1], amount_usd: -3}\n", "positive number"),
        ("deposits:\n  - {id: a, cadence: monthly, days: [1]}\n  - {id: a, cadence: monthly, days: [2]}\n", "used twice"),
    ],
)
def test_deposit_validation(text, message):
    with pytest.raises(ProfileError, match=message):
        parse(text)


def test_upcoming_deposits_mark_landed_late_and_expected(scheduled, mirror):
    mirror("eft", date="2026-11-06", accountKey="brokerage-9", kind="deposit", amount=500)
    mirror("small", date="2026-11-20", accountKey="brokerage-9", kind="deposit", amount=20)
    mirror("hsa", date="2026-11-16", accountKey="hsa-2", kind="deposit", amount=50)
    items = upcoming_deposits(scheduled, days=20, now=NOW)
    got = [(d["id"], d["date"], d["status"]) for d in items]
    assert got == [
        ("payday", "2026-11-06", "landed"),
        ("hsa", "2026-11-13", "landed"),
        ("money-in-small", "2026-11-20", "landed"),
        ("payday", "2026-11-20", "expected"),
        ("hsa", "2026-12-01", "expected"),
        ("payday", "2026-12-04", "expected"),
    ]
    assert items[0]["landed"]["activity_id"] == "eft"
    assert [d["id"] for d in deposits_landed(scheduled, since="2026-11-10", now=NOW)] == ["hsa", "money-in-small"]
    assert [d["scheduled"] for d in items[:3]] == [True, True, False] and {d["mode"] for d in items} == {"listed"}


def test_missed_deposit_reads_late(scheduled, mirror):
    items = upcoming_deposits(scheduled, days=0, now=NOW)
    assert {d["date"]: d["status"] for d in items}["2026-11-06"] == "late"


def test_calendar_merges_fixed_deposits_mine_and_wash(scheduled, preflight, proposal):
    preflight["result"]["value"] = {"status": "clear", "lights": [], "tax": {"wash_clear_date": "2026-12-10"}}
    d = create_proposal(scheduled, proposal(kind="harvest", symbol="ABCD"), "tax", now=NOW)
    approve(scheduled, d["id"], now=NOW)
    mine = add_event(scheduled, "2026-12-15", "Pull the lot export", note="Before any sale")
    events = calendar_events(scheduled, "2026-11-20", "2026-12-31", now=NOW)
    titles = [(e["date"], e["title"]) for e in events]
    assert ("2026-12-01", "Year-end tax window opens") in titles
    assert ("2026-12-31", "Last trading day to realize gains or losses this year") in titles
    assert ("2026-12-10", "ABCD wash-sale window clears") in titles
    assert ("2026-12-15", "Pull the lot export") in titles
    assert ("2026-12-04", "Deposit: payday") in titles
    assert titles == sorted(titles, key=lambda t: t[0])
    assert delete_event(scheduled, mine["id"]) == {"deleted": mine["id"]}
    with pytest.raises(DecisionError):
        delete_event(scheduled, mine["id"])


def test_tax_day_shifts_off_weekends(cfg):
    events = calendar_events(cfg, "2027-04-01", "2027-04-30", now=NOW)
    assert [e["date"] for e in events if "HSA" in e["title"]] == ["2027-04-15"]
    events = calendar_events(cfg, "2028-12-25", "2028-12-31", now=NOW)
    assert [e["date"] for e in events if "Last trading day" in e["title"]] == ["2028-12-29"]


def test_event_validation(cfg):
    with pytest.raises(DecisionError, match="look like"):
        add_event(cfg, "Dec 15", "x")
    with pytest.raises(DecisionError, match="title"):
        add_event(cfg, "2026-12-15", " ")
    with pytest.raises(DecisionError, match="before the start"):
        calendar_events(cfg, "2026-12-31", "2026-12-01")


def test_plan_endpoints(scheduled, app_client, mirror):
    client = app_client(packages=["decisions"])
    assert "deposits" in client.get("/api/decisions/deposits?days=30").json()
    r = client.post("/api/decisions/calendar", json={"date": "2026-12-15", "title": "Review lots"})
    assert r.status_code == 200 and r.json()["source"] == "you"
    events = client.get("/api/decisions/calendar?from=2026-12-01&to=2026-12-31").json()["events"]
    assert any(e["title"] == "Review lots" for e in events)
    assert client.delete(f"/api/decisions/calendar/{r.json()['id']}").status_code == 200
    assert client.post("/api/decisions/calendar", json={"date": "x", "title": "y"}).status_code == 422


def test_cash_in_counts_transfer_coded_money_in_and_drops_source_twins():
    from desk.decisions.plan import cash_in

    rows = [
        ("a", {"date": "2026-11-03", "accountKey": "individual-1", "kind": "deposit", "action": "EFT RECEIVED", "amount": 3000}),
        ("b", {"date": "2026-11-04", "accountKey": "individual-1", "kind": "deposit", "action": "EFT RECEIVED", "amount": 3000, "source": "sync"}),
        ("c", {"date": "2026-11-10", "accountKey": "individual-1", "kind": "transfer", "action": "TRANSFER Electronic Funds", "amount": 500}),
        ("d", {"date": "2026-11-11", "accountKey": "individual-1", "kind": "transfer", "action": "JOURNALED SPAXX", "amount": 900}),
        ("e", {"date": "2026-11-12", "accountKey": "individual-1", "kind": "transfer", "action": "TRANSFER OF ASSETS", "amount": 800, "symbol": "AAAA"}),
        ("f", {"date": "2026-11-13", "accountKey": "individual-1", "kind": "other", "action": "ELECTRONIC FUNDS TRANSFER PAID", "amount": 200}),
        ("g", {"date": "2026-11-14", "accountKey": "individual-1", "kind": "withdrawal", "action": "EFT", "amount": 100}),
        ("h", {"date": "not a date", "accountKey": "individual-1", "kind": "deposit", "amount": 50}),
    ]
    assert [x["activity_id"] for x in cash_in(rows)] == ["a", "c"]

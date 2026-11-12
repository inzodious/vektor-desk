import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

import desk.engine as engine
from desk.db import connect
from desk.engine import SKIPS, alpaca, earnings, filings, insider, lookthrough, paper_exec, public, research, schema, universe
from desk.engine.market import ProviderError
from desk.startrun import fix_for

NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
KEYS = ("DESK_SEC_USER_AGENT", "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "FRED_API_KEY", "FINNHUB_API_KEY")
SETTING_NAME = re.compile(r"[A-Z]{3,}_[A-Z_]{2,}")
NOT_PLAIN = re.compile(r"[A-Z]{3,}_[A-Z_]{2,}|`|\{|python -m|\bjob\b|\buniverse\b")
OTHER_THREADS = ("live.py", "review.py", "__main__.py", "lots.py", "broker.py")


class NoCalls:
    def get(self, *args, **kwargs):
        raise AssertionError("a skipped run must not call out")

    post = get


@pytest.fixture
def desk(cfg, monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    yield conn
    conn.close()


def test_every_skip_sentence_is_plain_and_a_missing_key_points_to_settings():
    assert set(SKIPS) == {engine.NO_SEC, engine.NO_ALPACA, engine.NO_FRED, engine.NO_FINNHUB, engine.NO_SMALL_COMPANIES}
    for code, words in SKIPS.items():
        assert re.fullmatch(r"[a-z_]+", code) and words.endswith(".") and not NOT_PLAIN.search(words), code
        assert engine.skip(code) == {"ok": True, "skipped": words, "skipped_code": code}
    for code in (engine.NO_SEC, engine.NO_ALPACA, engine.NO_FRED, engine.NO_FINNHUB):
        assert SKIPS[code].endswith("in Settings, Data, Keys."), code


def test_the_start_run_still_finds_the_fix_from_the_plain_sentence():
    assert fix_for(SKIPS[engine.NO_ALPACA])["label"] == "Add the Alpaca paper keys"
    assert fix_for(SKIPS[engine.NO_FINNHUB])["label"] == "Add the Finnhub key"


def test_each_statistics_run_that_lacks_a_key_skips_with_its_code_and_calls_nothing(desk, monkeypatch):
    http = NoCalls()
    quiet = {"now": NOW, "sleep": lambda s: None}
    got = {
        "universe": universe.run(desk, http, **quiet),
        "earnings": earnings.run(desk, http, **quiet),
        "filings": filings.run(desk, http, **quiet),
        "insider": insider.run(desk, http, **quiet),
        "public": public.run(desk, http, **quiet),
        "paper": paper_exec.run(desk, http, now=NOW),
        "edgar": research.run_edgar(desk, http, ["AAA"], **quiet),
        "fred": research.run_fred(desk, http, now=NOW),
        "finnhub": research.run_finnhub_research(desk, http, ["AAA"], now=NOW),
        "nport": lookthrough.run_nport(desk, http, ["AAA"], **quiet),
        "profiles": lookthrough.run_profiles(desk, http, ["AAA"], **quiet),
    }
    assert {k: v.get("skipped_code") for k, v in got.items()} == {
        "universe": "no_alpaca_keys",
        "earnings": "no_sec_contact",
        "filings": "no_sec_contact",
        "insider": "no_sec_contact",
        "public": "no_sec_contact",
        "paper": "no_alpaca_keys",
        "edgar": "no_sec_contact",
        "fred": "no_fred_key",
        "finnhub": "no_finnhub_key",
        "nport": "no_sec_contact",
        "profiles": "no_finnhub_key",
    }
    assert all(v["ok"] and v["skipped"] == SKIPS[v["skipped_code"]] for v in got.values())
    monkeypatch.setenv("DESK_SEC_USER_AGENT", "Desk Test desk@example.com")
    assert filings.run(desk, http, **quiet) == engine.skip(engine.NO_SMALL_COMPANIES)
    assert universe.run(desk, http, **quiet)["skipped_code"] == "no_alpaca_keys"


def test_a_missing_key_raised_as_an_error_reads_the_same_plain_sentence(desk):
    with pytest.raises(ProviderError) as e:
        alpaca.fetch_assets(desk, NoCalls(), now=NOW)
    assert str(e.value) == SKIPS[engine.NO_ALPACA]
    with pytest.raises(ProviderError) as e:
        universe.fetch_shares(desk, NoCalls(), now=NOW)
    assert str(e.value) == SKIPS[engine.NO_SEC]


def test_no_skip_or_provider_error_in_the_statistics_files_names_a_setting_key():
    bad = []
    for path in sorted(Path(engine.__file__).parent.rglob("*.py")):
        if path.name in OTHER_THREADS:
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if '"skipped": "' not in line and "ProviderError(" not in line:
                continue
            if any(SETTING_NAME.search(text) for text in re.findall(r'"([^"]*)"', line)):
                bad.append(f"{path.name}:{n}")
    assert bad == []

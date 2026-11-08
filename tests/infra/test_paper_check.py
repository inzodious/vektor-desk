import io
import json
import urllib.error

import pytest

from desk.paper_check import PAPER_URL, NotPaper, check, paper_base

KEYS = {"ALPACA_API_KEY_ID": "id-for-tests", "ALPACA_API_SECRET_KEY": "secret-for-tests"}


def opener(body: dict | None = None, code: int | None = None, seen: list | None = None):
    def open_(req, timeout):
        if seen is not None:
            seen.append(req)
        if code is not None:
            raise urllib.error.HTTPError(req.full_url, code, "no", {}, io.BytesIO(b""))
        return io.BytesIO(json.dumps(body).encode())

    return open_


@pytest.mark.parametrize(
    "url",
    [
        "https://api.alpaca.markets",
        "http://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets.evil.example",
        "https://paper-api.alpaca.markets:8443",
        "https://paper-api.alpaca.markets/v2/../live",
        "https://data.alpaca.markets",
    ],
)
def test_anything_but_the_paper_api_is_refused(url):
    with pytest.raises(NotPaper):
        paper_base(url)


def test_paper_api_is_the_default_and_the_only_base():
    assert paper_base() == PAPER_URL == "https://paper-api.alpaca.markets"
    assert paper_base("https://paper-api.alpaca.markets/v2/") == PAPER_URL


def test_check_reads_the_paper_account_only():
    seen: list = []
    ok, line = check(KEYS, opener({"account_number": "PA1TESTONLY", "status": "ACTIVE"}, seen=seen))
    assert ok and line == "paper account ok, status ACTIVE"
    (req,) = seen
    assert req.full_url == "https://paper-api.alpaca.markets/v2/account" and req.get_method() == "GET"


def test_check_says_what_is_missing_or_wrong():
    ok, line = check({}, opener({}))
    assert not ok and "ALPACA_API_KEY_ID" in line and "setup-truenas.sh set" in line
    ok, line = check({**KEYS, "ALPACA_BASE_URL": "https://api.alpaca.markets"}, opener({}))
    assert not ok and line.startswith("refused")
    ok, line = check(KEYS, opener(code=401))
    assert not ok and "rejected (401)" in line
    ok, line = check(KEYS, opener({"account_number": "123456789", "status": "ACTIVE"}))
    assert not ok and "paper" in line
    assert "secret-for-tests" not in line

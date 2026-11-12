ENGINE_VERSION = "0.1.0"
KEYS_AT = "Settings, Data, Keys"
JOBS_AT = "Settings, Box"
INBOX_AT = "Settings, Data, Inbox"
KEY_WORDS = {
    "TIINGO_API_KEY": "the Tiingo key",
    "FINNHUB_API_KEY": "the Finnhub key",
    "FRED_API_KEY": "the FRED key",
    "DESK_SEC_USER_AGENT": "the SEC contact",
    "ALPACA_API_KEY_ID": "the Alpaca paper key ID",
    "ALPACA_API_SECRET_KEY": "the Alpaca paper secret key",
}


NO_SEC, NO_ALPACA, NO_FRED, NO_FINNHUB, NO_SMALL_COMPANIES = "no_sec_contact", "no_alpaca_keys", "no_fred_key", "no_finnhub_key", "no_small_companies"
SKIPS = {
    NO_SEC: f"The SEC contact is not set. Add it in {KEYS_AT}.",
    NO_ALPACA: f"The Alpaca paper keys are not set. Add them in {KEYS_AT}.",
    NO_FRED: f"The FRED key is not set. Add it in {KEYS_AT}.",
    NO_FINNHUB: f"The Finnhub key is not set. Add it in {KEYS_AT}.",
    NO_SMALL_COMPANIES: "The list of small companies is not built yet. It builds itself on weekday evenings.",
}


def skip(code: str) -> dict:
    return {"ok": True, "skipped": SKIPS[code], "skipped_code": code}


def key_fix(keys: list[str]) -> str:
    words = [KEY_WORDS.get(k, "a key") for k in keys]
    listed = words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"
    return f"set {listed} in {KEYS_AT}."

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


def key_fix(keys: list[str]) -> str:
    words = [KEY_WORDS.get(k, "a key") for k in keys]
    listed = words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"
    return f"set {listed} in {KEYS_AT}."

import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

PAPER_HOST = "paper-api.alpaca.markets"
PAPER_URL = f"https://{PAPER_HOST}"
KEYS = ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY")


class NotPaper(ValueError):
    pass


def paper_base(url: str | None = None) -> str:
    url = (url or os.environ.get("ALPACA_BASE_URL") or PAPER_URL).rstrip("/")
    parts = urlparse(url)
    if parts.scheme != "https" or parts.hostname != PAPER_HOST or parts.port not in (None, 443) or parts.path not in ("", "/v2"):
        raise NotPaper(f"{url} isn't Alpaca's paper API ({PAPER_URL}); only paper trading is allowed")
    return PAPER_URL


def check(env: dict | None = None, opener=urllib.request.urlopen) -> tuple[bool, str]:
    env = os.environ if env is None else env
    missing = [k for k in KEYS if not env.get(k)]
    if missing:
        return False, f"not set: {', '.join(missing)}. Fix: setup-truenas.sh set {missing[0]} (paper keys from the Alpaca Paper Trading dashboard)"
    try:
        base = paper_base(env.get("ALPACA_BASE_URL"))
    except NotPaper as e:
        return False, f"refused: {e}"
    req = urllib.request.Request(  # noqa: S310
        f"{base}/v2/account",
        headers={"APCA-API-KEY-ID": env[KEYS[0]], "APCA-API-SECRET-KEY": env[KEYS[1]], "Accept": "application/json"},
    )
    try:
        with opener(req, timeout=15) as res:
            account = json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"rejected ({e.code}): the keys don't open a paper account. Use the keys from the Paper Trading dashboard"
        return False, f"failed: HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return False, f"failed: {e}"
    number = str(account.get("account_number") or "")
    if not number.startswith("PA"):
        return False, "refused: that account doesn't look like a paper account (number doesn't start with PA)"
    return True, f"paper account ok, status {account.get('status', '?')}"


def main() -> int:
    ok, line = check()
    print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

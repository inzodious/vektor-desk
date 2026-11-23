import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from desk.engine.market import ProviderError

KEY = "RAPIDAPI_KEY"
AV, FMP, YH = "alphavantage", "fmp", "yhfinance"
COMPACT_DAYS = 100
FMP_YEARS = 5
WAIT_S = 65
TRIES = 3
ANSWER_CHARS = 240
STOP_WORDS = ("quota", "daily", "per day", "monthly", "per month")


@dataclass(frozen=True)
class Source:
    name: str
    title: str
    host: str
    per_run: int
    per_minute: int
    per_day: int | None
    per_month: int | None
    full_history: bool
    held_only: bool


SOURCES = (
    Source(AV, "Alpha Vantage", "alpha-vantage.p.rapidapi.com", 25, 5, 400, None, True, False),
    Source(FMP, "FMP", "financial-modeling-prep.p.rapidapi.com", 15, 5, 200, None, False, False),
    Source(YH, "YH Finance", "yahoo-finance15.p.rapidapi.com", 3, 5, None, 80, False, True),
)
BY_NAME = {s.name: s for s in SOURCES}


def key() -> str:
    return os.environ.get(KEY, "").strip()


def _int_env(name: str, default: int | None) -> int | None:
    if default is None:
        return None
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def limits(src: Source) -> dict[str, int | None]:
    tag = src.name.upper()
    return {
        "run": _int_env(f"DESK_{tag}_PER_RUN", src.per_run),
        "day": _int_env(f"DESK_{tag}_DAILY", src.per_day),
        "month": _int_env(f"DESK_{tag}_MONTHLY", src.per_month),
    }


# ---- What a provider said ----


class SlowDown(ProviderError):
    pass


class OutOfCalls(ProviderError):
    pass


class Refused(ProviderError):
    pass


def stops(e: Exception) -> bool:
    return isinstance(e, (OutOfCalls, Refused)) or "did not answer" in str(e)


def answer(res) -> str:
    try:
        body = res.json()
    except (ValueError, AttributeError):
        body = None
    if isinstance(body, dict):
        text = next((str(body[k]) for k in ("message", "Note", "Information", "Error Message", "error") if body.get(k)), "")
    else:
        text = ""
    if not text:
        text = str(getattr(res, "text", "") or "")
    return " ".join(text.split())[:ANSWER_CHARS]


def limited(src: Source, said: str) -> ProviderError:
    words = said.lower()
    if "premium" in words:
        return Refused(f"{src.title} keeps this for paid plans: {said}")
    if any(w in words for w in STOP_WORDS) and "minute" not in words and "second" not in words:
        return OutOfCalls(f"{src.title} is out of calls for now: {said}")
    return SlowDown(f"{src.title} asked to slow down: {said}")


# ---- Calls ----


_last: dict[str, float] = {}


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _pace(src: Source) -> None:
    gap = 60 / max(1, src.per_minute) + 0.5
    since = time.monotonic() - _last.get(src.name, float("-inf"))
    if since < gap:
        _sleep(gap - since)
    _last[src.name] = time.monotonic()


def _get(http, src: Source, path: str, params: dict, api_key: str, symbol: str):
    res = http.get(f"https://{src.host}{path}", params=params, headers={"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": src.host}, timeout=60)
    if res.status_code == 429:
        raise limited(src, answer(res) or "429 Too Many Requests")
    if res.status_code in (401, 403):
        raise Refused(f"{src.title} refused the key ({res.status_code}): {answer(res)}")
    if res.status_code == 404:
        raise ProviderError(f"{src.title} has no daily prices for {symbol}")
    if res.status_code != 200:
        raise ProviderError(f"{src.title} {res.status_code} for {symbol}: {answer(res)}")
    body = res.json()
    if isinstance(body, dict) and src.name == AV:
        for k in ("Note", "Information"):
            if body.get(k):
                raise limited(src, " ".join(str(body[k]).split())[:ANSWER_CHARS])
    return body


def ask(http, src: Source, path: str, params: dict, api_key: str, symbol: str):
    said = ""
    for attempt in range(TRIES):
        _pace(src)
        try:
            return _get(http, src, path, params, api_key, symbol)
        except SlowDown as e:
            said = str(e).split(": ", 1)[-1]
            if attempt + 1 < TRIES:
                _sleep(WAIT_S)
    raise OutOfCalls(f"{src.title} still asked to slow down after {TRIES} tries: {said}")


def _num(value) -> float | None:
    try:
        return None if value in (None, "", "None") else float(value)
    except (TypeError, ValueError):
        return None


def _bar(day: str, o, h, low, c, adj, vol, div=0.0, split=1.0) -> dict | None:
    close = _num(c)
    if close is None:
        return None
    return {
        "date": day,
        "open": _num(o),
        "high": _num(h),
        "low": _num(low),
        "close": close,
        "adj_close": _num(adj),
        "volume": _num(vol),
        "div_cash": _num(div) or 0.0,
        "split_factor": _num(split) or 1.0,
    }


def av_daily(http, symbol: str, api_key: str, start: str, today: date | None = None) -> list[dict]:
    src = BY_NAME[AV]
    today = today or datetime.now(UTC).date()
    size = "compact" if date.fromisoformat(start) >= today - timedelta(days=COMPACT_DAYS - 10) else "full"
    params = {"function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": symbol, "outputsize": size, "datatype": "json"}
    body = ask(http, src, "/query", params, api_key, symbol) or {}
    if "Error Message" in body:
        raise ProviderError(f"{src.title} has no daily prices for {symbol}")
    series = body.get("Time Series (Daily)") or {}
    out = []
    for day, r in sorted(series.items()):
        if day < start:
            continue
        bar = _bar(
            day[:10],
            r.get("1. open"),
            r.get("2. high"),
            r.get("3. low"),
            r.get("4. close"),
            r.get("5. adjusted close"),
            r.get("6. volume"),
            r.get("7. dividend amount"),
            r.get("8. split coefficient"),
        )
        if bar:
            out.append(bar)
    return out


def fmp_daily(http, symbol: str, api_key: str, start: str) -> list[dict]:
    body = ask(http, BY_NAME[FMP], f"/v3/historical-price-full/{symbol}", {"from": start}, api_key, symbol) or {}
    rows = body.get("historical") or [] if isinstance(body, dict) else []
    out = [_bar(str(r.get("date"))[:10], r.get("open"), r.get("high"), r.get("low"), r.get("close"), r.get("adjClose"), r.get("volume")) for r in rows]
    return sorted((b for b in out if b and b["date"] >= start), key=lambda b: b["date"])


def yh_daily(http, symbol: str, api_key: str, start: str) -> list[dict]:
    params = {"symbol": symbol, "interval": "1d", "diffandsplits": "false"}
    body = ask(http, BY_NAME[YH], "/api/v1/markets/stock/history", params, api_key, symbol) or {}
    rows = body.get("body") or {} if isinstance(body, dict) else {}
    out = []
    for stamp, r in rows.items() if isinstance(rows, dict) else []:
        try:
            when = int(r.get("date_utc") or stamp)
        except (TypeError, ValueError):
            continue
        day = datetime.fromtimestamp(when, UTC).date().isoformat()
        bar = _bar(day, r.get("open"), r.get("high"), r.get("low"), r.get("close"), r.get("adjclose"), r.get("volume"))
        if bar and day >= start:
            out.append(bar)
    return sorted(out, key=lambda b: b["date"])


FETCH = {AV: av_daily, FMP: fmp_daily, YH: yh_daily}


# ---- Who can still be asked ----


def note_error(conn: sqlite3.Connection, src: Source, at: str, symbol: str | None, error: str) -> None:
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO provider_errors (provider, at, symbol, error) VALUES (?, ?, ?, ?)",
            (src.name, at, symbol, error[: ANSWER_CHARS + 80]),
        )


def used(conn: sqlite3.Connection, src: Source, now: datetime) -> dict[str, int]:
    day = (now - timedelta(days=1)).isoformat(timespec="seconds")
    month = (now - timedelta(days=30)).isoformat(timespec="seconds")
    q = "SELECT count(*) FROM api_calls WHERE provider=? AND at >= ?"
    return {"run": 0, "day": conn.execute(q, (src.name, day)).fetchone()[0], "month": conn.execute(q, (src.name, month)).fetchone()[0]}


class Backups:
    def __init__(self, conn: sqlite3.Connection, http, now: datetime, api_key: str | None = None):
        self.conn, self.http, self.now = conn, http, now
        self.key = key() if api_key is None else api_key
        self.caps = {s.name: limits(s) for s in SOURCES}
        self.used = {s.name: used(conn, s, now) for s in SOURCES} if self.key else {}
        self.stopped: set[str] = set()
        self.filled: dict[str, list[str]] = {}

    def open(self, src: Source) -> bool:
        if not self.key or src.name in self.stopped:
            return False
        cap, use = self.caps[src.name], self.used[src.name]
        return all(cap[k] is None or use[k] < cap[k] for k in ("run", "day", "month"))

    def fits(self, src: Source, start: str, held: bool, new: bool) -> bool:
        if src.held_only and not held:
            return False
        if new and not src.full_history:
            return False
        return src.full_history or date.fromisoformat(start) >= self.now.date() - timedelta(days=365 * FMP_YEARS - 30)

    def fetch(self, symbol: str, start: str, *, held: bool, new: bool) -> tuple[list[dict], str | None]:
        for src in SOURCES:
            if not self.fits(src, start, held, new) or not self.open(src):
                continue
            stamp = self.now.isoformat(timespec="seconds")
            try:
                bars, error = FETCH[src.name](self.http, symbol, self.key, start), None
            except ProviderError as e:
                bars, error, stop = [], str(e), stops(e)
            except (OSError, ValueError):
                bars, error, stop = [], f"{src.title} did not answer for {symbol}", True
            else:
                stop = False
            with self.conn:
                self.conn.execute("INSERT INTO api_calls (provider, at, symbol, ok) VALUES (?, ?, ?, ?)", (src.name, stamp, symbol, int(error is None)))
            for k in ("run", "day", "month"):
                self.used[src.name][k] += 1
            if error:
                note_error(self.conn, src, stamp, symbol, error)
            if stop:
                self.stopped.add(src.name)
            if bars:
                self.filled.setdefault(src.title, []).append(symbol)
                return bars, src.title
        return [], None

    def usage(self) -> dict:
        return {s.name: {"used": self.used.get(s.name), "limits": self.caps[s.name]} for s in SOURCES} if self.key else {}


def state(conn: sqlite3.Connection | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    ready = conn is not None and conn.execute("SELECT 1 FROM sqlite_master WHERE name='provider_errors'").fetchone() is not None
    out = {"key_set": bool(key()), "providers": []}
    for src in SOURCES:
        row = {"name": src.name, "title": src.title, "per_minute": src.per_minute, "limits": limits(src), "used": None, "last_error": None}
        if ready:
            row["used"] = {k: v for k, v in used(conn, src, now).items() if k != "run"}
            last = conn.execute("SELECT at, symbol, error FROM provider_errors WHERE provider=?", (src.name,)).fetchone()
            row["last_error"] = {"at": last[0], "symbol": last[1], "error": last[2]} if last else None
        out["providers"].append(row)
    return out

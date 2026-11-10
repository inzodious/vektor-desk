import io
import re
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta

from desk.engine.market import ProviderError

BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.French/ftp/{name}"
FACTOR_FILES = {
    "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip": {"Mkt-RF": "mkt_rf", "SMB": "smb", "HML": "hml", "RMW": "rmw", "CMA": "cma", "RF": "rf"},
    "F-F_Momentum_Factor_daily_CSV.zip": {"Mom": "mom"},
    "F-F_Research_Data_Factors_CSV.zip": {"Mkt-RF": "mkt_rf_m", "RF": "rf_m"},
}
PORTFOLIO_FILES = {
    "industry_12": "12_Industry_Portfolios_daily_CSV.zip",
    "industry_49": "49_Industry_Portfolios_daily_CSV.zip",
    "size_deciles": "Portfolios_Formed_on_ME_daily_CSV.zip",
    "momentum_deciles": "10_Portfolios_Prior_12_2_Daily_CSV.zip",
}
DECILES = ("Lo 10", "Dec 2", "Dec 3", "Dec 4", "Dec 5", "Dec 6", "Dec 7", "Dec 8", "Dec 9", "Hi 10")
REFRESH_DAYS = 25
MISSING = (-99.99, -999.0)


# ---- Parsing ----


def first_block(text: str) -> tuple[list[str], list[tuple[str, list[float | None]]]]:
    header: list[str] | None = None
    rows: list[tuple[str, list[float | None], str]] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if header is None:
            if len(cells) > 1 and cells[0] == "" and any(cells[1:]):
                header = cells[1:]
            continue
        if not cells or not re.fullmatch(r"\d{8}|\d{6}", cells[0]) or (rows and len(cells[0]) != len(rows[0][2])):
            if rows:
                break
            continue
        values: list[float | None] = []
        for c in cells[1 : len(header) + 1]:
            try:
                v = float(c)
            except ValueError:
                v = None
            values.append(None if v is None or v in MISSING else v)
        d = cells[0]
        rows.append((f"{d[:4]}-{d[4:6]}-{d[6:] or '01'}", values, d))
    return header or [], [(d, v) for d, v, _ in rows]


def unzip_csv(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        name = next((n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))), None)
        if name is None:
            raise ProviderError("French library zip has no CSV")
        if z.getinfo(name).file_size > 200_000_000:
            raise ProviderError("French library CSV is unexpectedly large")
        return z.read(name).decode("latin-1")


def pick_columns(set_name: str, header: list[str]) -> list[int]:
    if set_name in ("size_deciles", "momentum_deciles"):
        named = [i for i, h in enumerate(header) if h in DECILES]
        return named if len(named) == 10 else list(range(max(0, len(header) - 10), len(header)))
    return list(range(len(header)))


# ---- Fetch ----


def _fresh(conn: sqlite3.Connection, name: str, now: datetime, have: str | None = None) -> bool:
    if have is not None and conn.execute(have).fetchone() is None:
        return False
    cut = (now - timedelta(days=REFRESH_DAYS)).isoformat(timespec="seconds")
    q = "SELECT 1 FROM api_calls WHERE provider='french' AND symbol=? AND ok=1 AND at >= ? LIMIT 1"
    return conn.execute(q, (name, cut)).fetchone() is not None


def _download(http, name: str) -> str:
    res = http.get(BASE.format(name=name), timeout=120)
    if res.status_code != 200:
        raise ProviderError(f"French library {res.status_code} for {name}")
    return unzip_csv(res.content)


def run(conn: sqlite3.Connection, http, *, now: datetime | None = None, sets: tuple[str, ...] = tuple(PORTFOLIO_FILES)) -> dict:
    now = now or datetime.now(UTC)
    stamp = now.isoformat(timespec="seconds")
    done, errors = [], []
    for name, columns in FACTOR_FILES.items():
        wanted = ", ".join(f"'{series}'" for series in columns.values())
        if _fresh(conn, name, now, f"SELECT 1 FROM factors_daily WHERE series IN ({wanted}) LIMIT 1"):
            continue
        try:
            header, rows = first_block(_download(http, name))
        except (ProviderError, zipfile.BadZipFile, OSError) as e:
            errors.append(f"{name}: {e}")
            continue
        out = []
        for col, series in columns.items():
            if col not in header:
                errors.append(f"{name}: no {col} column")
                continue
            i = header.index(col)
            out += [(series, d, vals[i]) for d, vals in rows if i < len(vals) and vals[i] is not None]
        with conn:
            conn.executemany("INSERT OR REPLACE INTO factors_daily VALUES (?, ?, ?)", out)
            conn.execute("INSERT INTO api_calls (provider, at, symbol, ok) VALUES ('french', ?, ?, 1)", (stamp, name))
        done.append(name)
    for set_name in sets:
        name = PORTFOLIO_FILES[set_name]
        if _fresh(conn, name, now, f"SELECT 1 FROM french_returns WHERE set_name='{set_name}' LIMIT 1"):
            continue
        try:
            header, rows = first_block(_download(http, name))
        except (ProviderError, zipfile.BadZipFile, OSError) as e:
            errors.append(f"{name}: {e}")
            continue
        cols = pick_columns(set_name, header)
        out = ((set_name, header[i], d, vals[i]) for d, vals in rows for i in cols if i < len(vals) and vals[i] is not None)
        with conn:
            conn.execute("DELETE FROM french_returns WHERE set_name=?", (set_name,))
            conn.executemany("INSERT INTO french_returns VALUES (?, ?, ?, ?)", out)
            conn.execute("INSERT INTO api_calls (provider, at, symbol, ok) VALUES ('french', ?, ?, 1)", (stamp, name))
        done.append(name)
    return {"ok": not errors, "files": done, "errors": errors}

import csv
import hashlib
import io
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from desk.config import Config

MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
CASH_SYMBOLS = {"SPAXX", "FDRXX", "FZFXX", "SPRXX", "FCASH", "CORE", "FZDXX"}

COLUMNS = {
    "account_number": ("account number", "account #", "acct number"),
    "account_name": ("account name", "account"),
    "symbol": ("symbol", "ticker"),
    "description": ("description", "security description", "security name"),
    "acquired": ("date acquired", "acquired", "acquisition date", "open date", "purchase date"),
    "sold": ("date sold", "sold", "closing date", "close date", "sale date"),
    "shares": ("quantity", "shares", "qty"),
    "cost": ("cost basis", "cost basis total", "total cost", "cost basis ($)", "adjusted cost basis"),
    "cost_per_share": ("cost basis per share", "cost per share", "unit cost", "average cost basis", "cost basis/share"),
    "value": ("current value", "market value", "value"),
    "proceeds": ("proceeds", "total proceeds", "sale proceeds"),
    "gain": ("gain/loss", "total gain/loss", "total gain/loss dollar", "gain/loss ($)", "realized gain/loss"),
    "st_gain": ("short-term gain/loss", "short term gain/loss", "st gain/loss"),
    "lt_gain": ("long-term gain/loss", "long term gain/loss", "lt gain/loss"),
    "term": ("term", "holding period", "short/long", "term (short/long)"),
    "wash": ("wash sale loss disallowed", "disallowed loss", "wash sale disallowed", "wash sale"),
}

NEEDED = {"lots": ("symbol", "acquired", "shares"), "realized": ("symbol", "sold", "shares")}


class LotFileError(ValueError):
    pass


@dataclass
class LotFile:
    kind: str
    as_of: str | None
    rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---- Parsing ----


def money(raw) -> float | None:
    s = str(raw if raw is not None else "").strip()
    if not s or s in ("--", "-") or s.lower() in ("n/a", "na"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if s[:1] in ("-", "−"):
        neg, s = True, s[1:]
    s = re.sub(r"[+$,%\s]", "", s)
    if not s:
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def parse_date(raw) -> str | None:
    s = str(raw or "").strip()
    if not s or s.lower() in ("various", "--", "n/a"):
        return None
    if m := re.match(r"^(\d{4})-(\d{2})-(\d{2})", s):
        return f"{m[1]}-{m[2]}-{m[3]}"
    if m := re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", s):
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return f"{year:04d}-{int(m[1]):02d}-{int(m[2]):02d}"
    if m := re.match(r"^([A-Za-z]{3})[- ](\d{1,2})[-, ]+(\d{4})$", s):
        mon = MONTHS.get(m[1].lower())
        return f"{int(m[3]):04d}-{mon:02d}-{int(m[2]):02d}" if mon else None
    return None


def downloaded_at(line: str) -> str | None:
    m = re.search(r"Date downloaded\s+(.+?)(?:\s+\d{1,2}:\d{2}.*)?$", line, re.I)
    return parse_date(m[1].strip().strip('"')) if m else None


def account_kind(name: str) -> str:
    n = (name or "").lower()
    if "health savings" in n or re.search(r"\bhsa\b", n):
        return "hsa"
    if "401" in n:
        return "401k"
    if "roth" in n:
        return "roth"
    if re.search(r"\bira\b", n):
        return "ira"
    if "individual" in n or "brokerage" in n:
        return "individual"
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-") or "account"


def account_key(name: str, number: str) -> str:
    digits = re.sub(r"\W", "", number or "")
    tail = re.search(r"(\d{4})\D*\)?\s*$", name or "")
    last4 = digits[-4:] if digits else (tail[1] if tail else "")
    clean = re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip()
    kind = account_kind(clean)
    return f"{kind}-{last4}" if last4 else kind


def _header(row: list[str]) -> dict[str, int]:
    norm = [re.sub(r"\s+", " ", str(h).replace("﻿", "")).strip().lower() for h in row]
    idx = {}
    for key, names in COLUMNS.items():
        for i, h in enumerate(norm):
            if h in names:
                idx[key] = i
                break
    return idx


def _cell(r: list[str], idx: dict[str, int], key: str) -> str:
    return r[idx[key]].strip() if key in idx and idx[key] < len(r) else ""


def term_of(raw: str, acquired: str | None, sold: str | None, as_of: str | None) -> str | None:
    t = (raw or "").strip().lower()
    if t.startswith("short"):
        return "short"
    if t.startswith("long"):
        return "long"
    end = sold or as_of
    if acquired and end:
        a, e = date.fromisoformat(acquired), date.fromisoformat(end)
        try:
            anniversary = a.replace(year=a.year + 1)
        except ValueError:
            anniversary = a.replace(year=a.year + 1, day=28)
        return "long" if e > anniversary else "short"
    return None


def parse_lot_file(text: str, *, fallback_as_of: str | None = None) -> LotFile:
    rows = list(csv.reader(io.StringIO(text.replace("﻿", ""))))
    start = next((i for i, r in enumerate(rows) if len(_header(r)) >= 3 and "symbol" in _header(r)), None)
    if start is None:
        raise LotFileError("No header row with Symbol, Quantity and a date column was found. Export lot detail from Fidelity's cost basis view.")
    idx = _header(rows[start])
    kind = "realized" if "sold" in idx else "lots"
    missing = [c for c in NEEDED[kind] if c not in idx]
    if missing:
        raise LotFileError(f"This file is missing the {', '.join(missing)} column(s). Headers seen: {', '.join(rows[start])}.")
    as_of = next((d for r in rows for d in [downloaded_at(" ".join(r))] if d), None) or fallback_as_of
    out = LotFile(kind=kind, as_of=as_of)
    account = ("", "")
    for n, r in enumerate(rows[start + 1 :], start + 2):
        if len(r) < 3:
            continue
        name, number = _cell(r, idx, "account_name"), _cell(r, idx, "account_number")
        if name or number:
            account = (name, number)
        symbol = _cell(r, idx, "symbol").rstrip("*").upper()
        shares = money(_cell(r, idx, "shares"))
        if not symbol or shares is None or symbol in CASH_SYMBOLS or symbol.startswith("PENDING"):
            continue
        acquired = parse_date(_cell(r, idx, "acquired"))
        sold = parse_date(_cell(r, idx, "sold")) if kind == "realized" else None
        cost = money(_cell(r, idx, "cost"))
        per = money(_cell(r, idx, "cost_per_share"))
        if cost is None and per is not None:
            cost = round(per * shares, 2)
        if per is None and cost is not None and shares:
            per = round(cost / shares, 6)
        if kind == "lots" and acquired is None:
            out.warnings.append(f"Line {n}: {symbol} has no acquired date; it can't be used for wash-sale or term checks.")
        st, lt, gain = money(_cell(r, idx, "st_gain")), money(_cell(r, idx, "lt_gain")), money(_cell(r, idx, "gain"))
        term = term_of(_cell(r, idx, "term"), acquired, sold, as_of)
        if st is not None or lt is not None:
            gain = (st or 0.0) + (lt or 0.0)
            term = term or ("long" if (lt or 0) and not (st or 0) else "short")
        row = {
            "account": account_key(*account),
            "symbol": symbol,
            "acquired": acquired,
            "shares": shares,
            "cost": cost,
            "cost_per_share": per,
            "term": term,
        }
        if kind == "lots":
            row["value"] = money(_cell(r, idx, "value"))
        else:
            proceeds = money(_cell(r, idx, "proceeds"))
            row |= {
                "sold": sold,
                "proceeds": proceeds,
                "gain": gain if gain is not None else (round(proceeds - cost, 2) if proceeds is not None and cost is not None else None),
                "wash_disallowed": money(_cell(r, idx, "wash")) or 0.0,
            }
        out.rows.append(row)
    if not out.rows:
        raise LotFileError("The file had a header but no lot rows.")
    return out


# ---- Import from the inbox ----


def lot_inbox(cfg: Config) -> Path:
    return cfg.inbox / "fidelity"


def import_file(conn: sqlite3.Connection, path: Path) -> dict:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if conn.execute("SELECT 1 FROM lot_files WHERE sha256=?", (digest,)).fetchone():
        return {"file": path.name, "skipped": "already imported"}
    mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()
    parsed = parse_lot_file(raw.decode("utf-8-sig", errors="replace"), fallback_as_of=mtime)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with conn:
        file_id = conn.execute(
            "INSERT INTO lot_files (sha256, name, kind, as_of, imported_at, rows, warnings) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (digest, path.name, parsed.kind, parsed.as_of, now, len(parsed.rows), "\n".join(parsed.warnings) or None),
        ).lastrowid
        if parsed.kind == "lots":
            conn.executemany(
                "INSERT INTO lots (file_id, as_of, account, symbol, acquired, shares, cost, cost_per_share, value, term) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (file_id, parsed.as_of, r["account"], r["symbol"], r["acquired"], r["shares"], r["cost"], r["cost_per_share"], r["value"], r["term"])
                    for r in parsed.rows
                ],
            )
        else:
            conn.executemany(
                "INSERT OR IGNORE INTO realized_lots (file_id, account, symbol, acquired, sold, shares, proceeds, cost, gain, term, wash_disallowed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        file_id,
                        r["account"],
                        r["symbol"],
                        r["acquired"],
                        r["sold"],
                        r["shares"],
                        r["proceeds"],
                        r["cost"],
                        r["gain"],
                        r["term"],
                        r["wash_disallowed"],
                    )
                    for r in parsed.rows
                ],
            )
    return {"file": path.name, "kind": parsed.kind, "as_of": parsed.as_of, "rows": len(parsed.rows), "warnings": parsed.warnings}


def import_inbox(cfg: Config, conn: sqlite3.Connection) -> dict:
    folder = lot_inbox(cfg)
    done, errors = [], []
    for path in sorted(folder.glob("*.csv")) if folder.is_dir() else []:
        try:
            done.append(import_file(conn, path))
        except (LotFileError, UnicodeError, OSError) as e:
            errors.append({"file": path.name, "error": str(e)})
    return {"ok": not errors, "imported": [d for d in done if "rows" in d], "skipped": [d for d in done if "skipped" in d], "errors": errors}


def current_lots(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT l.* FROM lots l
           JOIN (SELECT account, max(f.as_of || printf('%010d', f.id)) AS pick FROM lots x JOIN lot_files f ON f.id = x.file_id GROUP BY account) p
             ON p.account = l.account
           JOIN lot_files f ON f.id = l.file_id AND f.as_of || printf('%010d', f.id) = p.pick
           ORDER BY l.account, l.symbol, l.acquired"""
    ).fetchall()
    return [dict(r) for r in rows]

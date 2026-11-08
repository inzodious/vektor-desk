import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from desk.config import Config
from desk.engine.lots import CASH_SYMBOLS as LOT_CASH
from desk.engine.lots import account_kind, lot_inbox
from desk.engine.source import current_rows
from desk.engine.tax import WASH_DAYS, held_long

try:
    EASTERN = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    EASTERN = UTC

CASH_SYMBOLS = LOT_CASH | {"CASH"}
SOURCE = "broker"
SUB_CODES = {
    "BY": "buy",
    "SL": "sell",
    "RN": "reinvest",
    "VP": "dividend",
    "DP": "deposit",
    "WD": "withdrawal",
    "TX": "tax",
    "OI": "interest",
    "RS": "split",
    "DS": "distribution",
    "OC": "other",
}
SUB_NAMES = {
    "buy": "buy",
    "sell": "sell",
    "dividend reinvest": "reinvest",
    "dividend paid": "dividend",
    "deposit": "deposit",
    "withdrawal": "withdrawal",
    "taxes": "tax",
    "other interest": "interest",
    "reverse split": "split",
    "distribution/split spin-off": "distribution",
    "other cash": "other",
}
SHARE_KINDS = {"buy", "sell", "reinvest", "split", "distribution"}
OUTFLOW_KINDS = {"buy", "reinvest", "withdrawal", "tax", "margin_interest"}
MARGIN_INTEREST = re.compile(r"MARGIN INTEREST", re.I)
CONTRIBUTION = re.compile(r"\bCONTR(IB(UTION)?)?\b|CONTRIBUTION", re.I)
JOURNAL = re.compile(r"JOURNAL|TRANSFERRED (FROM|TO)|REALLOCATION", re.I)
IN_LIEU = re.compile(r"IN LIEU", re.I)
SPLIT_FROM = re.compile(r"R/S FROM|SPLIT FROM", re.I)
SPLIT_TO = re.compile(r"R/S TO|SPLIT TO", re.I)
CUSIPISH = re.compile(r"^(?=.*\d)[0-9A-Z]{8}[0-9]$")
TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
LONG_DIGITS = re.compile(r"\d{6,}")
MATCH_DAYS = 3
MUTUAL = re.compile(r"^[A-Z]{4}X$")
ORDER = {"split": 0, "distribution": 1, "buy": 2, "reinvest": 2, "sell": 3, "in_lieu": 4}


class BrokerFileError(ValueError):
    pass


# ---- Parsing ----


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        s = str(v).replace(",", "").replace("$", "").strip()
        return float(s) if s else None
    except ValueError:
        return None


def _day(epoch) -> str | None:
    n = _num(epoch)
    if n is None:
        return None
    if n > 1e11:
        n /= 1000
    return datetime.fromtimestamp(n, EASTERN).date().isoformat()


def last4(acct) -> str:
    digits = re.sub(r"\D", "", str(acct or ""))
    return digits[-4:] if digits else "0000"


def _paren(text: str) -> str | None:
    tokens = [t.strip().upper() for t in re.findall(r"\(([^()]+)\)", text or "")]
    tokens = [t for t in tokens if t not in ("CASH", "MARGIN", "SHORT") and " " not in t]
    return tokens[-1] if tokens else None


def _clean(text: str) -> str:
    return LONG_DIGITS.sub(lambda m: "#" * len(m[0]), " ".join(str(text or "").split()))[:200]


def _kind(t: dict, text: str) -> str:
    cat = t.get("catDetail") or {}
    kind = SUB_CODES.get(str(cat.get("txnSubCatCode") or "").upper()) or SUB_NAMES.get(str(cat.get("txnSubCatDesc") or "").strip().lower(), "other")
    if kind == "other":
        if MARGIN_INTEREST.search(text):
            return "margin_interest"
        if CONTRIBUTION.search(text):
            return "deposit"
        if JOURNAL.search(text):
            return "journal"
    if kind == "interest" and IN_LIEU.search(text):
        return "in_lieu"
    if kind == "interest" and MARGIN_INTEREST.search(text):
        return "margin_interest"
    return kind


def _amount(t: dict, kind: str) -> float:
    amt = t.get("amtDetail") or {}
    net = _num(amt.get("net"))
    if net is None:
        net = _num(amt.get("principal")) or 0.0
    if kind in ("split", "distribution"):
        return 0.0
    code = str(((t.get("brokerageDetail") or {}).get("additionalDetail") or {}).get("depositWithdrawalCode") or "").upper()
    if code == "D":
        return abs(net)
    if code == "W":
        return -abs(net)
    if net < 0:
        return net
    return -abs(net) if kind in OUTFLOW_KINDS else abs(net)


def _quantity(t: dict, kind: str, text: str) -> float | None:
    if kind not in SHARE_KINDS:
        return None
    q = _num(t.get("quantity"))
    if q is None:
        return None
    if kind == "sell":
        return -abs(q)
    if kind in ("buy", "reinvest", "distribution"):
        return abs(q)
    if SPLIT_TO.search(text):
        return -abs(q)
    if SPLIT_FROM.search(text):
        return abs(q)
    return q or None


def parse(raw: dict) -> tuple[list[dict], dict]:
    if not isinstance(raw, dict) or not isinstance(raw.get("transactions"), list):
        raise BrokerFileError("This JSON has no transactions list. Export activity and orders history from Fidelity.")
    out, cancelled = [], 0
    for seq, t in enumerate(raw["transactions"]):
        if not isinstance(t, dict):
            continue
        brk = t.get("brokerageDetail") or {}
        if brk.get("isCancelled"):
            cancelled += 1
            continue
        day = _day((t.get("dateDetail") or {}).get("tradedDate") or t.get("date"))
        if not day:
            continue
        text = " ".join(str(t.get(k) or "") for k in ("description", "shortDesc"))
        kind = _kind(t, text)
        sec = t.get("securityDetail") or {}
        sym = str(sec.get("symbol") or "").strip().upper()
        cusip = str(sec.get("cusip") or "").strip().upper() or None
        sec_type = str(sec.get("typeCodeDesc") or "") or None
        amt = t.get("amtDetail") or {}
        fees = (_num(amt.get("commission")) or 0.0) + (_num(amt.get("fees")) or 0.0)
        out.append(
            {
                "seq": seq,
                "last4": last4(t.get("acctNum")),
                "date": day,
                "settle": _day((t.get("dateDetail") or {}).get("stlmntDate")),
                "kind": kind,
                "sub": str((t.get("catDetail") or {}).get("txnSubCatDesc") or "") or None,
                "symbol": sym if sym and TICKER.match(sym) and not CUSIPISH.match(sym) else None,
                "hint": _paren(str(t.get("description") or "")),
                "cusip": cusip if cusip and cusip.strip("0") else None,
                "sec_type": sec_type,
                "quantity": _quantity(t, kind, text),
                "price": _num(amt.get("price")) if kind in SHARE_KINDS - {"split", "distribution"} else None,
                "amount": round(_amount(t, kind), 2),
                "fees": round(fees, 2) if kind in ("buy", "sell") else 0.0,
                "funding": str(brk.get("tradeTypeCodeDesc") or "").lower() or None,
                "description": _clean(str(t.get("description") or t.get("shortDesc") or "")),
                "txn": str(t.get("txnNum") or ""),
                "text": text,
            }
        )
    _resolve(out)
    window = _window(raw, out)
    return out, {"cancelled": cancelled, "start": window[0], "end": window[1]}


def _resolve(rows: list[dict]) -> None:
    by_cusip = {r["cusip"]: r["symbol"] for r in rows if r["cusip"] and r["symbol"]}
    for r in rows:
        if r["symbol"]:
            continue
        hint = r["hint"] if r["hint"] and not CUSIPISH.match(r["hint"]) and TICKER.match(r["hint"]) else None
        r["symbol"] = by_cusip.get(r["cusip"]) or hint
    for r in rows:
        if r["symbol"] or r["kind"] not in ("split", "in_lieu"):
            continue
        twin = next((x for x in rows if x is not r and x["symbol"] and x["kind"] == "split" and x["last4"] == r["last4"] and x["date"] == r["date"]), None)
        r["symbol"] = twin["symbol"] if twin else (r["cusip"] or r["hint"])
    for r in rows:
        if r["symbol"] in CASH_SYMBOLS and r["kind"] in ("dividend", "interest"):
            r["symbol"] = None


def _window(raw: dict, rows: list[dict]) -> tuple[str | None, str | None]:
    starts, ends = [], []
    for f in raw.get("fetchLog") or []:
        m = re.findall(r"\d{4}-\d{2}-\d{2}", str((f or {}).get("range") or ""))
        if len(m) == 2:
            starts.append(m[0])
            ends.append(m[1])
    days = [r["date"] for r in rows]
    if not starts and not days:
        return None, None
    return min(starts + days), max(ends + days)


def row_id(r: dict) -> str:
    key = "|".join(str(r[k]) for k in ("last4", "txn", "date", "sub", "symbol", "cusip", "quantity", "amount", "description"))
    return hashlib.sha256(key.encode()).hexdigest()[:24]


# ---- Accounts ----


def mirror_keys(rows) -> dict[str, str]:
    found: dict[str, str] = {}
    for key in sorted({k for k in rows if k}):
        m = re.search(r"(\d{4})\D*$", key)
        if m and m[1] not in found:
            found[m[1]] = key
    return found


def keys_from_mirror(mirror: sqlite3.Connection | None) -> dict[str, str]:
    if mirror is None:
        return {}
    seen = set()
    for s in current_rows(mirror, "snapshots"):
        accts = s.get("accounts")
        seen.update(accts.keys() if isinstance(accts, dict) else (a.get("key") for a in accts or [] if isinstance(a, dict)))
    for tbl in ("positions", "activity"):
        seen.update(str(r.get("accountKey") or "") for r in current_rows(mirror, tbl))
    return mirror_keys(seen)


def guess_account(tail: str, rows: list[dict]) -> str:
    mine = [r for r in rows if r["last4"] == tail]
    kind = "hsa" if any("HSA" in r["text"].upper() or "HEALTH SAVINGS" in r["text"].upper() for r in mine) else "individual"
    return f"{account_kind(kind)}-{tail}"


# ---- Import ----


def import_file(conn: sqlite3.Connection, path: Path, keys: dict[str, str] | None = None) -> dict:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if conn.execute("SELECT 1 FROM broker_files WHERE sha256=?", (digest,)).fetchone():
        return {"file": path.name, "skipped": "already imported"}
    try:
        body = json.loads(raw.decode("utf-8-sig"))
    except ValueError as e:
        raise BrokerFileError(f"Not valid JSON: {e}") from e
    rows, info = parse(body)
    keys = keys or {}
    accounts = {t: keys.get(t) or guess_account(t, rows) for t in sorted({r["last4"] for r in rows})}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with conn:
        file_id = conn.execute(
            "INSERT INTO broker_files (sha256, name, imported_at, window_start, window_end, rows, added, cancelled, accounts) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (digest, path.name, now, info["start"], info["end"], len(rows), info["cancelled"], json.dumps(sorted(accounts.values()))),
        ).lastrowid
        before = conn.execute("SELECT count(*) FROM broker_txns").fetchone()[0]
        conn.executemany(
            "INSERT OR IGNORE INTO broker_txns (id, file_id, seq, last4, account, date, settle, kind, sub, symbol, cusip, sec_type, quantity, price, amount, "
            "fees, funding, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row_id(r),
                    file_id,
                    r["seq"],
                    r["last4"],
                    accounts[r["last4"]],
                    r["date"],
                    r["settle"],
                    r["kind"],
                    r["sub"],
                    r["symbol"],
                    r["cusip"],
                    r["sec_type"],
                    r["quantity"],
                    r["price"],
                    r["amount"],
                    r["fees"],
                    r["funding"],
                    r["description"],
                )
                for r in rows
            ],
        )
        added = conn.execute("SELECT count(*) FROM broker_txns").fetchone()[0] - before
        conn.execute("UPDATE broker_files SET added=? WHERE id=?", (added, file_id))
    return {
        "file": path.name,
        "rows": len(rows),
        "added": added,
        "cancelled": info["cancelled"],
        "start": info["start"],
        "end": info["end"],
        "accounts": sorted(accounts.values()),
    }


def import_inbox(cfg: Config, conn: sqlite3.Connection, mirror: sqlite3.Connection | None = None) -> dict:
    folder = lot_inbox(cfg)
    done, errors = [], []
    keys = keys_from_mirror(mirror)
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            done.append(import_file(conn, path, keys))
        except (BrokerFileError, UnicodeError, OSError) as e:
            errors.append({"file": path.name, "error": str(e)})
    if keys:
        remap(conn, keys)
    return {"ok": not errors, "imported": [d for d in done if "rows" in d], "skipped": [d for d in done if "skipped" in d], "errors": errors}


def remap(conn: sqlite3.Connection, keys: dict[str, str]) -> None:
    with conn:
        for tail, key in keys.items():
            conn.execute("UPDATE broker_txns SET account=? WHERE last4=? AND account<>?", (key, tail, key))


# ---- Read as activity ----


@dataclass
class History:
    rows: list[dict] = field(default_factory=list)
    cover: dict[str, tuple[str, str]] = field(default_factory=dict)
    mutual: set[str] = field(default_factory=set)
    matched: int = 0
    kept: list[dict] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)


def has_history(conn: sqlite3.Connection) -> bool:
    if conn.execute("SELECT 1 FROM main.sqlite_master WHERE name='broker_txns'").fetchone() is None:
        return False
    return conn.execute("SELECT 1 FROM broker_txns LIMIT 1").fetchone() is not None


def _as_activity(r: dict) -> dict:
    symbol = r["symbol"]
    core = bool(symbol and symbol in CASH_SYMBOLS)
    return {
        "key": f"{SOURCE}:{r['id']}",
        "date": r["date"],
        "settle": r["settle"],
        "accountKey": r["account"],
        "kind": r["kind"],
        "action": r["description"],
        "description": r["description"],
        "symbol": symbol,
        "quantity": r["quantity"],
        "price": r["price"],
        "fees": r["fees"],
        "amount": r["amount"],
        "core": core,
        "funding": r["funding"],
        "secType": r["sec_type"],
        "source": SOURCE,
    }


def load(conn: sqlite3.Connection, keys: dict[str, str] | None = None) -> History:
    h = History()
    if not has_history(conn):
        return h
    keys = keys or {}
    txns = [dict(r) for r in conn.execute("SELECT * FROM broker_txns ORDER BY date, file_id, seq")]
    for t in txns:
        t["account"] = keys.get(t["last4"]) or t["account"]
        if keys and t["last4"] not in keys and t["account"] not in h.unmapped:
            h.unmapped.append(t["account"])
    files = [dict(r) for r in conn.execute("SELECT window_start, window_end, accounts FROM broker_files")]
    spans: dict[str, list[str]] = {}
    for t in txns:
        lo, hi = spans.setdefault(t["account"], [t["date"], t["date"]])
        spans[t["account"]] = [min(lo, t["date"]), max(hi, t["date"])]
    for f in files:
        tails = {re.sub(r"\D", "", a)[-4:] for a in json.loads(f["accounts"] or "[]")}
        for t in txns:
            if t["last4"] in tails and f["window_start"] and f["window_end"]:
                lo, hi = spans[t["account"]]
                spans[t["account"]] = [min(lo, f["window_start"]), max(hi, f["window_end"])]
    h.cover = {a: (lo, hi) for a, (lo, hi) in spans.items()}
    h.mutual = {t["symbol"] for t in txns if t["symbol"] and t["sec_type"] == "Mutual Fund" and t["symbol"] not in CASH_SYMBOLS}
    _pair_journals(txns)
    h.rows = [_as_activity(t) for t in txns if t["kind"] != "journal"]
    return h


def _pair_journals(txns: list[dict]) -> None:
    journals = [t for t in txns if t["kind"] == "journal" and t["amount"]]
    for t in journals:
        if t["kind"] != "journal" or t["amount"] <= 0:
            continue
        day = date.fromisoformat(t["date"])
        twin = next(
            (
                x
                for x in journals
                if x["kind"] == "journal"
                and x["account"] != t["account"]
                and round(x["amount"] + t["amount"], 2) == 0
                and abs((date.fromisoformat(x["date"]) - day).days) <= MATCH_DAYS
            ),
            None,
        )
        if twin:
            t["kind"], twin["kind"] = "deposit", "withdrawal"
            t["description"] = f"Transfer between accounts: {t['description']}"
            twin["description"] = f"Transfer between accounts: {twin['description']}"


def _match_symbol(r: dict) -> str:
    s = str(r.get("symbol") or "").upper()
    return "" if r.get("core") or s in CASH_SYMBOLS else s


def merge(mirror_rows: list[dict], h: History) -> list[dict]:
    pool: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for b in h.rows:
        pool[(b["accountKey"], _match_symbol(b))].append(b)
    used: set[str] = set()
    out = list(h.rows)
    h.matched, h.kept = 0, []
    for r in mirror_rows:
        acct = str(r.get("accountKey") or "")
        d = str(r.get("date") or "")[:10]
        span = h.cover.get(acct)
        if not span or not (span[0] <= d <= span[1]):
            out.append(r)
            continue
        hit = _match(r, d, pool.get((acct, _match_symbol(r)), []), used)
        if hit is not None:
            used.add(hit["key"])
            h.matched += 1
            continue
        out.append(r)
        if not (r.get("core") or str(r.get("symbol") or "").upper() in CASH_SYMBOLS):
            h.kept.append(r)
    out.sort(key=lambda r: str(r.get("date") or ""))
    return out


def _match(r: dict, d: str, candidates: list[dict], used: set[str]) -> dict | None:
    amount = _num(r.get("amount")) or 0.0
    try:
        day = date.fromisoformat(d)
    except ValueError:
        return None
    best, gap = None, MATCH_DAYS + 1
    for b in candidates:
        if b["key"] in used:
            continue
        diff = abs((date.fromisoformat(b["date"]) - day).days)
        if diff > MATCH_DAYS or (amount > 0) != (b["amount"] > 0) or (amount < 0) != (b["amount"] < 0):
            continue
        if abs(abs(amount) - abs(b["amount"])) > max(0.02, 0.005 * abs(amount)):
            continue
        if diff < gap:
            best, gap = b, diff
    return best


def history(mirror: sqlite3.Connection | None, desk: sqlite3.Connection) -> tuple[list[dict], History]:
    mirror_rows = list(current_rows(mirror, "activity")) if mirror is not None else []
    h = load(desk, keys_from_mirror(mirror))
    if not h.rows:
        return mirror_rows, h
    return merge(mirror_rows, h), h


def activity(mirror: sqlite3.Connection | None, desk: sqlite3.Connection) -> list[dict]:
    return history(mirror, desk)[0]


# ---- For desk.decisions ----


def decision_rows(conn: sqlite3.Connection, since: str | None = None) -> list[tuple[str, dict]]:
    attached = conn.execute("SELECT 1 FROM pragma_database_list WHERE name='mirror'").fetchone() is not None
    mirror_rows: list[tuple[str, dict]] = []
    seen_keys: set[str] = set()
    if attached:
        for r in conn.execute("SELECT id, tbl, json FROM mirror.rows WHERE tbl IN ('activity', 'snapshots', 'positions')"):
            try:
                a = json.loads(r["json"])
            except (TypeError, ValueError):
                continue
            if not isinstance(a, dict):
                continue
            if r["tbl"] == "snapshots":
                accts = a.get("accounts")
                seen_keys.update(accts.keys() if isinstance(accts, dict) else ())
                continue
            seen_keys.add(str(a.get("accountKey") or ""))
            if r["tbl"] == "activity":
                mirror_rows.append((r["id"], a))
    h = load(conn, mirror_keys(seen_keys))
    ids = {id(a): rid for rid, a in mirror_rows}
    merged = merge([a for _, a in mirror_rows], h) if h.rows else [a for _, a in mirror_rows]
    out = [(ids.get(id(a)) or a["key"], a) for a in merged]
    return [(rid, a) for rid, a in out if since is None or str(a.get("date") or "") >= since]


# ---- Lots from history ----


@dataclass
class Book:
    lots: list[dict] = field(default_factory=list)
    realized: list[dict] = field(default_factory=list)
    notes: dict[tuple[str, str], str] = field(default_factory=dict)
    derived: int = 0
    skipped: int = 0


def method_of(symbol: str, mutual: set[str]) -> str:
    return "average" if symbol in mutual or MUTUAL.match(symbol or "") else "fifo"


def _clears(day: str) -> tuple[str, str]:
    d = date.fromisoformat(day)
    return (d - timedelta(days=WASH_DAYS)).isoformat(), (d + timedelta(days=WASH_DAYS)).isoformat()


def build_book(rows: list[dict], h: History, price=None) -> Book:
    book = Book()
    lots: dict[tuple[str, str], list[dict]] = defaultdict(list)
    buys: list[dict] = []
    covered = [r for r in rows if str(r.get("accountKey") or "") in h.cover]
    covered.sort(key=lambda r: (str(r.get("date") or "")[:10], ORDER.get(r.get("kind"), 9), 0 if (_num(r.get("quantity")) or 0) < 0 else 1))
    days: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in covered:
        if r.get("kind") == "split":
            days[(str(r["accountKey"]), str(r["date"])[:10])].append(r)
    done_splits: set[tuple[str, str]] = set()
    for r in covered:
        kind = r.get("kind")
        acct, day = str(r["accountKey"]), str(r.get("date") or "")[:10]
        sym = str(r.get("symbol") or "").upper()
        if kind not in ORDER or not sym or sym in CASH_SYMBOLS or r.get("core"):
            continue
        qty = _num(r.get("quantity"))
        amount = _num(r.get("amount")) or 0.0
        if kind in ("buy", "sell", "reinvest") and not qty:
            px = price(sym, day) if price and amount else None
            if not px:
                book.skipped += 1
                continue
            qty = -amount / px
            book.derived += 1
        if kind == "split":
            if (acct, day) not in done_splits:
                done_splits.add((acct, day))
                _split(lots, days[(acct, day)], book)
            continue
        if kind == "distribution":
            _distribution(lots, acct, sym, day, qty or 0.0, book)
        elif kind in ("buy", "reinvest") and qty > 0:
            cost = -amount if amount < 0 else qty * (_num(r.get("price")) or 0.0)
            lot = {"acquired": day, "shares": qty, "cost": cost}
            lots[(acct, sym)].append(lot)
            buys.append({"account": acct, "symbol": sym, "date": day, "shares": qty, "lot": lot, "left": qty})
        elif kind in ("sell", "buy", "reinvest") and qty < 0:
            _sell(lots, acct, sym, day, -qty, amount, method_of(sym, h.mutual), book, h)
        elif kind == "in_lieu" and amount > 0:
            held = lots.get((acct, sym)) or []
            first = held[0]["acquired"] if held else None
            book.realized.append(_realized(acct, sym, first, day, 0.0, amount, 0.0, method_of(sym, h.mutual)))
    _wash(book, buys)
    for (acct, sym), held in sorted(lots.items()):
        method = method_of(sym, h.mutual)
        for lot in held:
            if lot["shares"] <= 1e-6:
                continue
            book.lots.append(
                {
                    "account": acct,
                    "symbol": sym,
                    "acquired": lot["acquired"],
                    "shares": round(lot["shares"], 6),
                    "cost": round(lot["cost"], 2),
                    "cost_per_share": round(lot["cost"] / lot["shares"], 6),
                    "value": None,
                    "term": None,
                    "method": method,
                    "quality": "modelled",
                }
            )
    return book


def _realized(acct, sym, acquired, sold, shares, proceeds, cost, method) -> dict:
    gain = None if cost is None else round(proceeds - cost, 2)
    long = held_long(acquired, sold) if acquired else None
    return {
        "account": acct,
        "symbol": sym,
        "acquired": acquired,
        "sold": sold,
        "shares": round(shares, 6),
        "proceeds": round(proceeds, 2),
        "cost": None if cost is None else round(cost, 2),
        "gain": gain,
        "term": None if long is None else ("long" if long else "short"),
        "wash_disallowed": 0.0,
        "method": method,
        "quality": "modelled",
    }


def _sell(lots, acct, sym, day, qty, proceeds, method, book, h) -> None:
    held = lots[(acct, sym)]
    if method == "average" and held:
        shares = sum(lot["shares"] for lot in held)
        avg = sum(lot["cost"] for lot in held) / shares if shares else 0.0
        for lot in held:
            lot["cost"] = lot["shares"] * avg
    left = qty
    while left > 1e-6 and held:
        lot = held[0]
        take = min(lot["shares"], left)
        part = lot["cost"] * take / lot["shares"]
        book.realized.append(_realized(acct, sym, lot["acquired"], day, take, proceeds * take / qty, part, method))
        lot["shares"] -= take
        lot["cost"] -= part
        left -= take
        if lot["shares"] <= 1e-6:
            held.pop(0)
    if left > 1e-6:
        book.realized.append(_realized(acct, sym, None, day, left, proceeds * left / qty, None, method))
        start = h.cover.get(acct, ("?", "?"))[0]
        book.notes[(acct, sym)] = f"sold {left:g} more shares than the history holds, so they were bought before {start}"


def _scale(held: list[dict], ratio: float) -> None:
    for lot in held:
        lot["shares"] *= ratio


def _split(lots, rows, book) -> None:
    old = [r for r in rows if (_num(r.get("quantity")) or 0) < 0]
    new = [r for r in rows if (_num(r.get("quantity")) or 0) > 0]
    for o, n in zip(old, new, strict=False):
        src = (str(o["accountKey"]), str(o.get("symbol") or "").upper())
        dst = (str(n["accountKey"]), str(n.get("symbol") or "").upper())
        ratio = _num(n["quantity"]) / -_num(o["quantity"])
        held = lots.pop(src, [])
        _scale(held, ratio)
        lots[dst] = sorted(lots.get(dst, []) + held, key=lambda lot: lot["acquired"])
    for r in old[len(new) :] + new[len(old) :]:
        book.notes[(str(r["accountKey"]), str(r.get("symbol") or "").upper())] = f"a split on {str(r['date'])[:10]} had only one side in the history"


def _distribution(lots, acct, sym, day, qty, book) -> None:
    held = lots.get((acct, sym)) or []
    shares = sum(lot["shares"] for lot in held)
    if shares > 1e-6:
        _scale(held, (shares + qty) / shares)
        return
    lots[(acct, sym)].append({"acquired": day, "shares": qty, "cost": 0.0})
    book.notes[(acct, sym)] = f"{qty:g} shares arrived as a distribution on {day} with no basis in the history; they carry $0 cost"


def _wash(book: Book, buys: list[dict]) -> None:
    for r in sorted(book.realized, key=lambda x: x["sold"]):
        if r["gain"] is None or r["gain"] >= 0 or not r["shares"]:
            continue
        lo, hi = _clears(r["sold"])
        need = r["shares"]
        for b in buys:
            if need <= 1e-9:
                break
            if b["symbol"] != r["symbol"] or not (lo <= b["date"] <= hi) or b["left"] <= 1e-9:
                continue
            if b["account"] == r["account"] and b["date"] == r["acquired"]:
                continue
            take = min(need, b["left"])
            amount = -r["gain"] * take / r["shares"]
            r["wash_disallowed"] = round(r["wash_disallowed"] + amount, 2)
            b["left"] -= take
            need -= take
            if b["lot"]["shares"] > 1e-6:
                b["lot"]["cost"] += amount * min(1.0, b["lot"]["shares"] / b["shares"])


# ---- Store ----


def store(conn: sqlite3.Connection, book: Book, as_of: str) -> None:
    conn.execute("DELETE FROM broker_lots")
    conn.executemany(
        "INSERT INTO broker_lots (as_of, account, symbol, acquired, shares, cost, cost_per_share, method) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(as_of, x["account"], x["symbol"], x["acquired"], x["shares"], x["cost"], x["cost_per_share"], x["method"]) for x in book.lots],
    )
    conn.execute("DELETE FROM broker_realized")
    conn.executemany(
        "INSERT INTO broker_realized (account, symbol, acquired, sold, shares, proceeds, cost, gain, term, wash_disallowed, method) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                x["account"],
                x["symbol"],
                x["acquired"],
                x["sold"],
                x["shares"],
                x["proceeds"],
                x["cost"],
                x["gain"],
                x["term"],
                x["wash_disallowed"],
                x["method"],
            )
            for x in book.realized
        ],
    )


# ---- Summary ----


def summary(h: History) -> dict:
    first = min((lo for lo, _ in h.cover.values()), default=None)
    last = max((hi for _, hi in h.cover.values()), default=None)
    return {"rows": len(h.rows), "accounts": sorted(h.cover), "start": first, "end": last, "matched": h.matched, "kept": len(h.kept)}

import logging
import re
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import requests

from desk.config import Config
from desk.db import desk_conn
from desk.notify.schema import SCHEMA

log = logging.getLogger("desk.notify")

# ---- Topics and limits ----

PREFIX = "desk-"
TOPICS = {
    "alerts": "Rule breaches, Preflight blocks, trigger hits, wash-sale windows",
    "research": "Research ready, daily brief, desk proposals waiting",
    "ops": "Stale or failing mirror, Claude token renewal, deploy and backup trouble",
}
PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}
TITLE_MAX = 80
BODY_MAX = 280
DEDUPE_HOURS = 20.0
TIMEOUT = 5
AMOUNT = re.compile(r"[-+]?\$\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmMbB]\b)?")


def _now() -> datetime:
    return datetime.now(UTC)


def clean(text: str, limit: int) -> str:
    text = " ".join(AMOUNT.sub("$…", text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def topic_name(topic: str) -> str:
    return PREFIX + topic


def subscribe_url(cfg: Config, topic: str) -> str:
    return f"{cfg.public_url}:8443/{topic_name(topic)}"


def _click(cfg: Config, click: str | None) -> str | None:
    if not click:
        return None
    if click.startswith("/"):
        return cfg.public_url + click
    return click if click.startswith(cfg.public_url + "/") or click == cfg.public_url else None


# ---- Log ----


@contextmanager
def _db(cfg: Config) -> Iterator[sqlite3.Connection]:
    conn = desk_conn(cfg, mirror=False)
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _recent_key(cfg: Config, key: str, since: datetime) -> bool:
    try:
        with _db(cfg) as conn:
            row = conn.execute(
                "SELECT 1 FROM notify_log WHERE key = ? AND at >= ? AND status IN ('sent', 'demo') LIMIT 1",
                (key, since.isoformat(timespec="seconds")),
            ).fetchone()
        return row is not None
    except sqlite3.Error as e:
        log.warning("notify: couldn't check %s: %s", key, e)
        return False


def _record(cfg: Config, entry: dict) -> None:
    try:
        with _db(cfg) as conn:
            conn.execute(
                "INSERT INTO notify_log (at, topic, priority, title, body, click, key, status, error)"
                " VALUES (:at, :topic, :priority, :title, :body, :click, :key, :status, :error)",
                entry,
            )
    except sqlite3.Error as e:
        log.warning("notify: couldn't log %s: %s", entry["title"], e)


def muted(cfg: Config) -> set[str]:
    try:
        with _db(cfg) as conn:
            return {r["topic"] for r in conn.execute("SELECT topic FROM notify_topics WHERE enabled = 0")}
    except sqlite3.Error as e:
        log.warning("notify: couldn't read topic switches: %s", e)
        return set()


def set_enabled(cfg: Config, topic: str, enabled: bool) -> None:
    if topic not in TOPICS:
        raise ValueError(f"unknown topic {topic!r}")
    with _db(cfg) as conn:
        conn.execute(
            "INSERT INTO notify_topics (topic, enabled, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (topic) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at",
            (topic, int(enabled), _now().isoformat(timespec="seconds")),
        )


def recent(cfg: Config, limit: int = 30, topic: str | None = None) -> list[dict]:
    sql = "SELECT seq, at, topic, priority, title, body, click, status, error FROM notify_log"
    args: tuple = ()
    if topic:
        sql += " WHERE topic = ?"
        args = (topic,)
    with _db(cfg) as conn:
        rows = conn.execute(sql + " ORDER BY seq DESC LIMIT ?", (*args, limit)).fetchall()
    return [dict(r) for r in rows]


# ---- Publish ----


def publish(
    topic: str,
    title: str,
    body: str = "",
    priority: str = "default",
    *,
    tags: Iterable[str] = (),
    click: str | None = None,
    key: str | None = None,
    dedupe_hours: float = DEDUPE_HOURS,
    cfg: Config | None = None,
    session: requests.Session | None = None,
) -> bool:
    if topic not in TOPICS:
        raise ValueError(f"unknown topic {topic!r}; use one of {', '.join(TOPICS)}")
    if priority not in PRIORITIES:
        raise ValueError(f"unknown priority {priority!r}; use one of {', '.join(PRIORITIES)}")
    cfg = cfg or Config.from_env()
    now = _now()
    if key and dedupe_hours > 0 and _recent_key(cfg, key, now - timedelta(hours=dedupe_hours)):
        return False
    entry = {
        "at": now.isoformat(timespec="seconds"),
        "topic": topic,
        "priority": PRIORITIES[priority],
        "title": clean(title, TITLE_MAX) or "Vektor Desk",
        "body": clean(body, BODY_MAX),
        "click": _click(cfg, click),
        "key": key,
        "status": "sent",
        "error": None,
    }
    if topic in muted(cfg):
        entry["status"] = "muted"
    elif cfg.demo:
        entry["status"] = "demo"
    elif not cfg.ntfy_url:
        entry["status"] = "off"
    else:
        message = {
            "topic": topic_name(topic),
            "title": entry["title"],
            "message": entry["body"] or entry["title"],
            "priority": entry["priority"],
            "tags": [t for t in tags if re.fullmatch(r"[a-z0-9_]{1,32}", t)][:4],
        }
        if entry["click"]:
            message["click"] = entry["click"]
        try:
            res = (session or requests).post(cfg.ntfy_url + "/", json=message, timeout=TIMEOUT)
            if res.status_code >= 300:
                raise requests.HTTPError(f"ntfy answered {res.status_code}")
        except requests.RequestException as e:
            entry["status"] = "failed"
            entry["error"] = str(e)[:300]
            log.warning("notify: %s didn't send: %s", entry["title"], entry["error"])
    _record(cfg, entry)
    return entry["status"] in ("sent", "demo")

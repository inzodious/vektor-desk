import json
from datetime import UTC, datetime, timedelta

from desk.config import Config
from desk.db import connect
from desk.engine.french import PORTFOLIO_FILES
from desk.engine.lab.data import PUBLIC_ROLE, SCREEN_KIND, NotReady, data_path, ledger_path
from desk.engine.lab.library import TRANSFORMS, catalog
from desk.engine.lab.rulebook import RULES

__all__ = ["NotReady", "desk_view", "eligible", "features", "grammar", "pending_reviews", "rules", "strategies", "universe_ready"]

REVIEW_DAYS = 14
SPEC_FIELDS = (
    "title",
    "hypothesis",
    "predicted_effect",
    "universe",
    "signals",
    "entry",
    "exit",
    "rebalance",
    "sizing",
    "params",
    "success_criteria",
    "horizons",
)


def grammar() -> dict:
    return {
        "universe": {
            "fund_list": "symbols: funds or ETFs, or set: sector_etfs | core_etfs | benchmarks | plan_mix (the plan at its target weights). "
            '{"type": "fund_list", "set": "sector_etfs"}',
            "screen": "single stocks from the public stock list: the largest US companies by public float at a fixed past date, companies that "
            "were later bought or failed included; never picked from what the owner holds. min_history_days, min_price. Tests start the January "
            'after the list date; under 90% of the list priced, a pass is research only. {"type": "screen", "min_history_days": 300, "min_price": 5}',
            "small_caps": 'point-in-time US small caps from insider-filing names since 2016; min_price (default 2); benchmark IWM. {"type": "small_caps"}',
            "french": "Ken French research portfolios, no survivorship bias, daily from 1963 on the factor calendar. set: "
            + " | ".join(PORTFOLIO_FILES)
            + '. {"type": "french", "set": "industry_12"}. members: ["hi"] keeps only the portfolios whose name starts that way. '
            "Benchmark defaults to FF.MKT; a pass is research only, never paper",
        },
        "filters": '[{"metric_id": "ma_gap", "window": "200d", "min": 0}]: a name is only eligible while each raw value sits inside min and max. '
        'Add "symbol": "SPY" to read the value from that fund instead, a market-wide switch that sends the whole strategy to cash',
        "signals": "metric_id from features, window like 63d, 6m or 1y (or {param}d), transform: " + ", ".join(TRANSFORMS),
        "entry": '{"top_n": 3 or "param:top_n", "min_signal": 0} (min_signal applies to the first signal\'s raw value), or "top 3 by rank"',
        "exit": '"rebalance", or {"hold_rank": 5} to keep a holding while it ranks in the top 5',
        "rebalance": "weekly, monthly or quarterly; signals at the close, trades at the next open",
        "sizing": 'equal, inverse_vol (63-day), rank, or a fixed mix {"weights": {"SPY": 60, "AGG": 40}} (funds only; needs no signal). '
        'In the object form, "vol_target": 0.15 scales the holdings down into cash while their 63-day volatility runs above 15% a year',
        "params": '{"top_n": {"min": 2, "max": 5, "default": 3}} or a list of allowed values; grid values must sit inside',
        "costs": "set by the lab: 5 bps funds and French portfolios, 15 bps stocks, 25 bps thin stocks",
        "factor_check": "automatic: alpha after the six French factors on the walk-forward record; alpha t of 2 or more passes",
        "rule": {
            "request": '{"request": "rule", "id": "band-test", "rule": "rebalance_band", "params": {"band_pts": [3, 5, 10]}, "horizons": [5, 10]}',
            "rules": {k: list(v) for k, v in RULES.items()},
            "optional": "mix (funds, defaults to the plan), deposit_monthly (default 1000), start_value (default 10000), account, date_range",
            "notes": "margin and paydown need rate_pct as one number (paydown also debit_pct, the starting debit as a share of the account); "
            " every rule runs against deposits split pro rata with no selling; grid cap 12",
        },
    }


READY_TABLES = {"small_caps": "smallcap", "french": "french", "fund_list": "bars", "screen": "bars"}


def universe_ready(cfg: Config, kind: str) -> bool:
    table = READY_TABLES.get(kind)
    path = data_path(cfg)
    if table is None or not path.exists():
        return False
    conn = connect(path, readonly=True)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is None:
            return False
        if kind == SCREEN_KIND:
            return conn.execute("SELECT 1 FROM symbols WHERE role=? LIMIT 1", (PUBLIC_ROLE,)).fetchone() is not None
        return conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def features(cfg: Config) -> list[dict]:
    return catalog()


def _ledger(cfg: Config):
    path = ledger_path(cfg)
    if not path.exists():
        return None
    return connect(path, readonly=True)


def strategies(cfg: Config) -> list[dict]:
    conn = _ledger(cfg)
    if conn is None:
        return _lanes(cfg)
    try:
        rows = [
            dict(r)
            for r in conn.execute("SELECT id, version, title, status, registered_at, spec_hash, parent_id, spec FROM strategies ORDER BY registered_at DESC")
        ]
        counts = {(r[0], r[1]): r[2] for r in conn.execute("SELECT strategy_id, version, count(*) FROM strategy_trials GROUP BY strategy_id, version")}
    finally:
        conn.close()
    from desk.engine.lab.shelf import IDS

    paper = _paper(cfg)
    for r in rows:
        r["hypothesis"] = _raw(r.pop("spec")).get("hypothesis")
        r["trials"] = counts.get((r["id"], r["version"]), 0)
        p = paper.get((r["id"], r["version"]))
        r["kind"] = "strategy"
        r["library"] = r["id"] in IDS
        if p:
            r["paper"] = p
            r["status"] = p["status"] if p["status"] != "paper" else r["status"]
    return _lanes(cfg) + rows


def _lanes(cfg: Config) -> list[dict]:
    from desk.engine import lane

    if not cfg.desk_db.exists():
        return []
    conn = connect(cfg.desk_db, readonly=True)
    try:
        specs = lane.variants(conn)
    finally:
        conn.close()
    paper = _paper(cfg)
    out = []
    for v in specs:
        p = paper.get((v.id, v.version))
        if p is None and not v.registered_at:
            continue
        row = {"id": v.id, "version": v.version, "title": v.title, "kind": "lane", "status": p["status"] if p else "waiting", "registered_at": v.registered_at}
        row |= {"hypothesis": v.hypothesis, "params": v.params(), "rule": v.rule(), "trials": 0}
        if p:
            row["paper"] = p
        out.append(row)
    return out


def _raw(text: str | None) -> dict:
    try:
        body = json.loads(text or "{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def frozen_spec(row) -> dict | None:
    if row is None:
        return None
    raw = _raw(row["spec"])
    return {k: raw.get(k) for k in SPEC_FIELDS} | {"title": row["title"] or raw.get("title"), "written_at": row["written_at"], "model": row["model"]}


def _paper(cfg: Config) -> dict:
    if not cfg.desk_db.exists():
        return {}
    conn = connect(cfg.desk_db, readonly=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='paper_portfolios'").fetchone():
            return {}
        return {(r["strategy_id"], r["version"]): dict(r) for r in conn.execute("SELECT * FROM paper_portfolios")}
    finally:
        conn.close()


def rules(cfg: Config) -> list[dict]:
    conn = _ledger(cfg)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT strategy_id, version, max(result_at) AS result_at, body FROM lab_results WHERE kind='rule' "
            "GROUP BY strategy_id, version ORDER BY result_at DESC"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        body = json.loads(r["body"])
        out.append(
            {
                "id": r["strategy_id"],
                "version": r["version"],
                "rule": body.get("rule"),
                "verdict": body.get("verdict"),
                "best": body.get("best"),
                "result_at": r["result_at"],
            }
        )
    return out


def desk_view(cfg: Config, strategy_id: str) -> dict:
    conn = _ledger(cfg)
    if conn is None:
        raise NotReady("The lab has not run anything yet.")
    try:
        results = [
            json.loads(r["body"])
            for r in conn.execute("SELECT body FROM lab_results WHERE strategy_id=? ORDER BY version DESC, result_at DESC", (strategy_id,))
        ]
        row = conn.execute("SELECT * FROM strategies WHERE id=? ORDER BY version DESC LIMIT 1", (strategy_id,)).fetchone()
    finally:
        conn.close()
    if not results:
        return {"strategy_id": strategy_id, "status": None, "folds": [], "tear_sheet": None, "note": "No lab results for this id."}
    latest_version = results[0]["version"]
    mine = [r for r in results if r["version"] == latest_version]
    rule = next((r for r in mine if r["kind"] == "rule"), None)
    if rule and not row:
        rejected = next((r for r in mine if r["kind"] == "rejected" and r["result_at"] > rule["result_at"]), None)
        return {
            "strategy_id": strategy_id,
            "version": latest_version,
            "kind": "rule",
            "status": rule["verdict"],
            "rule": {k: v for k, v in rule.items() if k not in ("strategy_id", "version", "kind")},
            "rejected": rejected["problems"] if rejected else None,
            "grammar": grammar(),
        }
    exp = next((r for r in mine if r["kind"] == "experiment"), None)
    fin = next((r for r in mine if r["kind"] == "finalize"), None)
    rejected = next((r for r in mine if r["kind"] == "rejected"), None)
    view = {
        "strategy_id": strategy_id,
        "version": latest_version,
        "status": row["status"] if row and row["version"] == latest_version else "rejected",
        "spec_hash": row["spec_hash"] if row else None,
        "spec": frozen_spec(row) if row and row["version"] == latest_version else None,
        "folds": exp["folds"] if exp else [],
        "kind": "strategy",
        "tear_sheet": {
            k: exp.get(k) for k in ("windows", "variants", "trials_family", "walk_forward", "horizons", "deflated_sharpe", "pbo", "factor_check", "caveats")
        }
        if exp
        else None,
        "analyses": exp.get("analyses") if exp else {},
        "rejected": rejected["problems"] if rejected and (not exp or rejected["result_at"] > exp["result_at"]) else None,
        "grammar": grammar(),
    }
    if fin:
        view["final"] = {k: fin.get(k) for k in ("verdict", "bars", "params", "holdout", "post_cutoff", "paper_start", "factor_check", "note")}
    paper = _paper(cfg).get((strategy_id, latest_version))
    if paper:
        view["paper"] = paper
    return view


def pending_reviews(cfg: Config, now: datetime | None = None) -> list[dict]:
    conn = _ledger(cfg)
    if conn is None:
        return []
    cut = ((now or datetime.now(UTC)) - timedelta(days=REVIEW_DAYS)).isoformat(timespec="seconds")
    try:
        rows = conn.execute(
            "SELECT strategy_id, version, kind, max(result_at) AS result_at FROM lab_results WHERE result_at >= ? "
            "GROUP BY strategy_id, version, kind ORDER BY result_at",
            (cut,),
        ).fetchall()
    finally:
        conn.close()
    from desk.engine.lab.shelf import IDS

    return [dict(r) for r in rows if r["strategy_id"] not in IDS]


def eligible(cfg: Config) -> list[dict]:
    out = []
    for (sid, version), p in sorted(_paper(cfg).items()):
        if p["status"] == "eligible":
            verdict = (_raw(p["summary"]).get("gate") or {}).get("verdict") or {}
            luck = f" The chance that lead is luck is {verdict['luck']:.0%}." if verdict.get("luck") is not None else ""
            out.append(
                {
                    "strategy_id": sid,
                    "version": version,
                    "title": p["title"],
                    "summary": f"Passed the lab and its day-{verdict.get('checkpoint') or p['days']} paper checkpoint, "
                    f"{p['excess_pts']:+.2f} points against its benchmark.{luck}",
                }
            )
    return out

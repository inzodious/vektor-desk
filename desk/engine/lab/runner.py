import hashlib
import json
import multiprocessing
import os
import sqlite3
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from desk.config import Config
from desk.db import connect
from desk.engine import gate
from desk.engine.lab import factors, rulebook, simcache, stats
from desk.engine.lab.data import FRENCH_KIND, SMALL_CAPS, LabData, data_path, lab_build, lab_dir, ledger_path, load
from desk.engine.lab.sim import simulate
from desk.engine.lab.simcache import Cache, Run
from desk.engine.lab.spec import HELD_SET, Spec, SpecError, Variant, local_only, parse, resolve, variants

HOLDOUT_YEARS = 2
DEFAULT_CUTOFF = "2026-06-30"
POST_CUTOFF_MIN_DAYS = 63
DSR_BAR = 0.95
PBO_BAR = 0.2
COVERAGE_MAX_MISSING = 0.05
LEDGER = """
CREATE TABLE IF NOT EXISTS strategies (
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  spec_hash TEXT NOT NULL,
  parent_id TEXT,
  title TEXT,
  status TEXT NOT NULL CHECK (status IN ('lab', 'paper', 'research', 'failed', 'inconclusive')),
  registered_at TEXT NOT NULL,
  model TEXT,
  written_at TEXT,
  spec TEXT NOT NULL,
  PRIMARY KEY (id, version)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS strategy_trials (
  id INTEGER PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  params TEXT NOT NULL,
  window TEXT NOT NULL,
  kind TEXT NOT NULL,
  metrics TEXT NOT NULL,
  run_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS strategy_trials_sid ON strategy_trials (strategy_id, version);
CREATE TABLE IF NOT EXISTS lab_results (
  strategy_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('experiment', 'finalize', 'rejected', 'rule')),
  result_at TEXT NOT NULL,
  body TEXT NOT NULL,
  PRIMARY KEY (strategy_id, version, kind, result_at)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS queue_done (
  file TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  done_at TEXT NOT NULL
) WITHOUT ROWID;
"""


MIGRATE = {"strategies": "'research'", "lab_results": "'rule'"}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, marker in MIGRATE.items():
        row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if row is None or marker in row[0]:
            continue
        with conn:
            conn.execute(f"ALTER TABLE {table} RENAME TO old_{table}")
    conn.executescript(LEDGER)
    for table in MIGRATE:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (f"old_{table}",)).fetchone():
            with conn:
                conn.execute(f"INSERT INTO {table} SELECT * FROM old_{table}")
                conn.execute(f"DROP TABLE old_{table}")


def ledger(cfg: Config) -> sqlite3.Connection:
    conn = connect(ledger_path(cfg))
    _migrate(conn)
    return conn


def _stamp(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def _shift(day: str, years: float) -> str:
    d = date.fromisoformat(day)
    if float(years).is_integer():
        try:
            return d.replace(year=d.year + int(years)).isoformat()
        except ValueError:
            return d.replace(year=d.year + int(years), day=28).isoformat()
    return (d + timedelta(days=round(365.25 * years))).isoformat()


def cutoff_for(model: str) -> str:
    try:
        table = json.loads(os.environ.get("DESK_LAB_MODEL_CUTOFFS", "") or "{}")
    except ValueError:
        table = {}
    return str(table.get(model) or table.get("default") or DEFAULT_CUTOFF)


def _record(conn, spec: Spec, kind: str, body: dict, now: datetime) -> dict:
    body = {"strategy_id": spec.id, "version": spec.version, "kind": kind, "result_at": _stamp(now), **body}
    with conn:
        conn.execute("INSERT OR REPLACE INTO lab_results VALUES (?, ?, ?, ?, ?)", (spec.id, spec.version, kind, body["result_at"], json.dumps(body)))
    return body


def _reject(conn, raw: dict, problems: list[str], now: datetime) -> dict:
    sid, version = str(raw.get("id") or raw.get("strategy_id") or "unknown"), int(raw.get("version") or 1)
    body = {"strategy_id": sid, "version": version, "kind": "rejected", "result_at": _stamp(now), "problems": problems, "lab_build": lab_build()}
    with conn:
        conn.execute("INSERT OR REPLACE INTO lab_results VALUES (?, ?, 'rejected', ?, ?)", (sid, version, body["result_at"], json.dumps(body)))
    return body


def _trial(conn, spec: Spec, v: Variant, window: str, kind: str, metrics: dict, now: datetime):
    row = (spec.id, spec.version, v.key, window, kind, json.dumps(metrics))
    same = "SELECT 1 FROM strategy_trials WHERE strategy_id=? AND version=? AND params=? AND window=? AND kind=? AND metrics=?"
    if conn.execute(same, row).fetchone():
        return
    conn.execute("INSERT INTO strategy_trials (strategy_id, version, params, window, kind, metrics, run_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (*row, _stamp(now)))


def family_ids(conn, strategy_id: str) -> list[str]:
    parents = {r["id"]: r["parent_id"] for r in conn.execute("SELECT id, parent_id FROM strategies")}
    parents.setdefault(strategy_id, None)

    def root(sid):
        seen = set()
        while parents.get(sid) and sid not in seen:
            seen.add(sid)
            sid = parents[sid]
        return sid

    def group(sid):
        return gate.family(sid) or gate.family(root(sid)) or root(sid)

    mine = group(strategy_id)
    return sorted(sid for sid in parents if group(sid) == mine)


def family_parent(conn, strategy_id: str) -> str | None:
    key = gate.family(strategy_id)
    if key is None:
        return None
    rows = conn.execute("SELECT id FROM strategies WHERE id != ? ORDER BY registered_at, id", (strategy_id,)).fetchall()
    return next((r["id"] for r in rows if gate.family(r["id"]) == key), None)


def _family_full(conn, strategy_id: str) -> list[float | None]:
    ids = family_ids(conn, strategy_id)
    marks = ",".join("?" * len(ids))
    seen: dict[tuple, float | None] = {}
    q = f"SELECT strategy_id, version, params, metrics FROM strategy_trials WHERE strategy_id IN ({marks}) AND kind='full' ORDER BY id"
    for r in conn.execute(q, ids):
        seen[(r["strategy_id"], r["version"], r["params"])] = json.loads(r["metrics"]).get("sharpe")
    return list(seen.values())


def family_trials(conn, strategy_id: str) -> int:
    return len(_family_full(conn, strategy_id))


def family_sharpe_var(conn, strategy_id: str) -> float:
    daily = [s / 252**0.5 for s in _family_full(conn, strategy_id) if s is not None]
    return stats._sd(daily) ** 2 if len(daily) > 1 else 0.0


# ---- Walk-forward ----


def windows(data: LabData, date_range: dict, kind: str | None = None) -> dict:
    cal, last = data.calendar_for(kind), data.end_for(kind)
    if not cal:
        raise SpecError(["there is no data for this universe yet"])
    holdout = _shift(last, -HOLDOUT_YEARS)
    start = max(str(date_range.get("start") or cal[0]), cal[0])
    end = min(str(date_range.get("end") or last), (date.fromisoformat(holdout) - timedelta(days=1)).isoformat())
    span = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25 if end > start else 0
    if span >= 4:
        train, test = 3.0, 1.0
    elif span >= 2.5:
        train, test = 2.0, 0.5
    else:
        raise SpecError([f"the walk-forward range {start} to {end} is {span:.1f} years; it needs 2.5 or more before the two-year holdout"])
    folds, t0 = [], start
    while _shift(t0, train) < end:
        test_start = _shift(t0, train)
        folds.append({"train": (t0, test_start), "test": (test_start, min(_shift(test_start, test), end))})
        t0 = _shift(t0, test)
    return {"start": start, "end": end, "holdout_start": holdout, "folds": folds, "clipped": str(date_range.get("end") or end) > end}


_DATA: LabData | None = None
_SPEC: Spec | None = None


def _job(args):
    params, start, end, cost_mult = args
    v = resolve(_SPEC, params)
    res = simulate(_DATA, _SPEC, v, start, end, cost_mult=cost_mult)
    return Run(params, stats.summary(res), stats.rets(res.values), stats.rets(res.bench), res.days)


def _compute(data, spec, jobs: list[tuple]) -> list[Run]:
    global _DATA, _SPEC
    _DATA, _SPEC = data, spec
    workers = max(1, int(os.environ.get("DESK_LAB_WORKERS", "1") or 1))
    if workers > 1 and len(jobs) > 4 and "fork" in multiprocessing.get_all_start_methods():
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork")) as pool:
            return list(pool.map(_job, jobs, chunksize=4))
    return [_job(j) for j in jobs]


def _run_many(cfg, data, spec, jobs: list[tuple], cache: Cache | None = None) -> list[Run]:
    if cache is None:
        return _compute(data, spec, jobs)
    keys = [cache.key(spec.hash, j) for j in jobs]
    have = cache.get(keys)
    todo = [(k, j) for k, j in zip(keys, jobs, strict=True) if k not in have]
    cache.hits, cache.misses = cache.hits + len(jobs) - len(todo), cache.misses + len(todo)
    if todo:
        runs = _compute(data, spec, [j for _, j in todo])
        cache.put([simcache.row(k, j, run) for (k, j), run in zip(todo, runs, strict=True)])
        have |= {k: run for (k, _), run in zip(todo, runs, strict=True)}
    return [have[k] for k in keys]


def _ok(spec: Spec, summary: dict) -> bool:
    cap = spec.constraints.get("max_turnover")
    return cap is None or (summary.get("turnover_per_year") or 0) <= float(cap)


def _best(spec: Spec, results: list[tuple]) -> dict | None:
    allowed = [r for r in results if _ok(spec, r.summary) and r.summary.get("sharpe") is not None]
    if not allowed:
        return None
    return max(allowed, key=lambda r: (r.summary["sharpe"], json.dumps(r.params, sort_keys=True))).params


def _stitch(pieces: list[Run]) -> tuple[list[str], list[float], list[float | None]]:
    if not pieces:
        return [], [], []
    days, vals, bench = [pieces[0].days[0]], [1.0], [1.0]
    for run in pieces:
        for d, x, y in zip(run.days[1:], run.rets, run.bench, strict=True):
            days.append(d)
            vals.append(vals[-1] * (1 + (x or 0.0)))
            bench.append(bench[-1] * (1 + y) if y is not None and bench[-1] is not None else None)
    return days, vals, bench


def run_experiment(cfg: Config | None, conn, data: LabData, request: dict, *, now: datetime, cache: Cache | None = None) -> dict:
    raw = request.get("spec") or {}
    try:
        spec = parse(raw, data, model=str(request.get("model") or ""))
        known = conn.execute("SELECT spec_hash, status FROM strategies WHERE id=? AND version=?", (spec.id, spec.version)).fetchone()
        if known and known["spec_hash"] != spec.hash:
            raise SpecError([f"{spec.id} v{spec.version} is registered with a different spec; a change needs a new version"])
        if known and known["status"] != "lab":
            raise SpecError([f"{spec.id} v{spec.version} is finalized ({known['status']}); a change needs a new version"])
        grid_variants = variants(spec, request.get("grid"), int(request.get("trial_budget") or 200), int(request.get("seed") or 0))
        asked = dict(request.get("date_range") or {})
        if spec.start:
            asked["start"] = max(str(asked.get("start") or ""), spec.start)
        win = windows(data, asked, spec.universe.get("kind"))
    except SpecError as e:
        return _reject(conn, raw, e.problems, now)
    if not known:
        with conn:
            conn.execute(
                "INSERT INTO strategies VALUES (?, ?, ?, ?, ?, 'lab', ?, ?, ?, ?)",
                (
                    spec.id,
                    spec.version,
                    spec.hash,
                    spec.parent_id or family_parent(conn, spec.id),
                    spec.title,
                    _stamp(now),
                    spec.model,
                    request.get("written_at"),
                    json.dumps(raw),
                ),
            )
    params = [v.params for v in grid_variants]
    folds, pieces, chosen = [], [], []
    for f in win["folds"]:
        train = _run_many(cfg, data, spec, [(p, *f["train"], 1.0) for p in params], cache)
        pick = _best(spec, train)
        with conn:
            for run in train:
                _trial(conn, spec, resolve(spec, run.params), f"{f['train'][0]}..{f['train'][1]}", "train", run.summary, now)
        window = {"train_window": list(f["train"]), "test_window": list(f["test"])}
        if pick is None:
            folds.append(window | {"params": None, "note": "No variant met the constraints on this training window."})
            continue
        (test,) = _run_many(cfg, data, spec, [(pick, *f["test"], 1.0)], cache)
        with conn:
            _trial(conn, spec, resolve(spec, pick), f"{f['test'][0]}..{f['test'][1]}", "test", test.summary, now)
        train_sum = next(run.summary for run in train if run.params == pick)
        folds.append(window | {"params": pick, "train_sharpe": train_sum.get("sharpe"), "test": test.summary})
        pieces.append(test)
        chosen.append(json.dumps(pick, sort_keys=True))
    full = _run_many(cfg, data, spec, [(p, win["start"], win["end"], 1.0) for p in params], cache)
    with conn:
        for run in full:
            _trial(conn, spec, resolve(spec, run.params), f"{win['start']}..{win['end']}", "full", run.summary, now)
    oos_days, oos_vals, oos_bench = _stitch(pieces)
    oos_r = [x for x in stats.rets(oos_vals) if x is not None]
    trials = family_trials(conn, spec.id)
    srs = [s for s in (stats.sharpe_daily([x for x in run.rets if x is not None]) for run in full) if s is not None]
    var_sr = max(stats._sd(srs) ** 2 if len(srs) > 1 else 0.0, family_sharpe_var(conn, spec.id))
    skew, kurt = stats.moments(oos_r)
    sr = stats.sharpe_daily(oos_r)
    dsr = stats.deflated_sharpe(sr, max(trials, len(params)), var_sr, len(oos_r), skew, kurt) if sr is not None else None
    pbo = stats.pbo([[x or 0.0 for x in run.rets] for run in full])
    deploy = json.loads(chosen[-1]) if chosen else None
    favorite = json.loads(Counter(chosen).most_common(1)[0][0]) if chosen else None
    horizons = _horizons(spec, oos_days, oos_vals, oos_bench, favorite, data, win)
    factor = factors.regress(oos_days, oos_vals, data.factors)
    body = {
        "status": "ok",
        "spec_hash": spec.hash,
        "windows": {"start": win["start"], "end": win["end"], "holdout_start": win["holdout_start"], "clipped_to_holdout": win["clipped"]},
        "variants": len(params),
        "trials_family": trials,
        "folds": folds,
        "walk_forward": _oos_summary(oos_vals, oos_bench, oos_days),
        "horizons": horizons,
        "deflated_sharpe": round(dsr, 4) if dsr is not None else None,
        "pbo": round(pbo, 4) if pbo is not None else None,
        "noise": gate.measure(oos_vals, oos_bench, max(trials, len(params))) if len(oos_vals) > 2 else None,
        "deploy_params": deploy,
        "factor_check": factor,
        "analyses": _analyses(cfg, data, spec, request.get("analyses") or [], full, favorite, win, factor, cache),
        "caveats": spec.caveats + _caveats(spec, factor),
    } | ({"library_rev": int(request["library_rev"])} if request.get("library_rev") else {})
    return _record(conn, spec, "experiment", body, now)


def _oos_summary(vals, bench, days) -> dict:
    if len(vals) < 2:
        return {"days": 0}
    r = [x for x in stats.rets(vals) if x is not None]
    s_c = stats.cagr(vals, days)
    b_ok = [b for b in bench if b is not None]
    b_c = stats.cagr(b_ok, days[: len(b_ok)]) if len(b_ok) == len(days) else None
    sd = stats._sd(r)
    return {
        "start": days[0],
        "end": days[-1],
        "days": len(days),
        "ann_return_pct": stats._pct(s_c),
        "excess_pts": stats._pct(s_c - b_c) if s_c is not None and b_c is not None else None,
        "sharpe": round(stats._mean(r) / sd * 252**0.5, 4) if sd else None,
        "mdd_pct": stats._pct(stats.drawdown(vals)),
    }


def _horizons(spec, oos_days, oos_vals, oos_bench, favorite, data, win) -> list[dict]:
    out = []
    for years in spec.horizons:
        d = stats.start_months(oos_days, oos_vals, oos_bench, years) if oos_days else {"starts": 0}
        if d["starts"]:
            out.append(d | {"basis": "walk_forward"})
            continue
        if favorite is not None:
            res = simulate(data, spec, resolve(spec, favorite), win["start"], win["end"])
            d = stats.start_months(res.days, res.values, res.bench, years)
            if d["starts"]:
                out.append(d | {"basis": "in_sample"})
                continue
        out.append({"years": years, "starts": 0, "basis": None, "note": f"Fewer than {years} years of data before the holdout."})
    return out


def _caveats(spec: Spec, factor: dict) -> list[str]:
    out = ["Unrealized gains at the end of a window are not taxed, and the benchmark is untaxed."]
    if factor.get("status") != "ok":
        out.append("The factor check could not run, so it is not part of the verdict: " + str(factor.get("note") or "no factor data."))
    elif factor.get("label") == "factor_in_disguise":
        out.append(f"After the factors there is no alpha; the return is {', '.join(factor['tilts'])} exposure, which a cheap factor fund also buys.")
    if spec.horizons and 3 in spec.horizons:
        out.append("A 3-year horizon is mostly noise.")
    return out


def _analyses(cfg, data, spec, wanted, full, favorite, win, factor, cache=None) -> dict:
    out = {}
    if "param_sensitivity" in wanted:
        table = {}
        for run in full:
            for k, val in run.params.items():
                table.setdefault(k, {}).setdefault(json.dumps(val), []).append(run.summary.get("sharpe") or 0.0)
        out["param_sensitivity"] = {k: {val: round(stats._mean(xs), 4) for val, xs in vals.items()} for k, vals in table.items()}
    if favorite is not None and "turnover_cost" in wanted:
        rows = _run_many(cfg, data, spec, [(favorite, win["start"], win["end"], m) for m in (1.0, 2.0, 4.0)], cache)
        out["turnover_cost"] = [
            {"cost_x": m, "excess_vs_bench_pts": run.summary.get("excess_vs_bench_pts")} for m, run in zip((1.0, 2.0, 4.0), rows, strict=True)
        ]
    if favorite is not None and "regime_split" in wanted:
        res = simulate(data, spec, resolve(spec, favorite), win["start"], win["end"])
        out["regime_split"] = _regimes(data, res)
    if "factor_regression" in wanted:
        out["factor_regression"] = factor
    return out


def _regimes(data, res) -> dict:
    r, b = stats.rets(res.values), stats.rets(res.bench)
    rates = [data.macro_at("DGS3MO", d) for d in res.days[1:]]
    known = sorted(x for x in rates if x is not None)
    median = known[len(known) // 2] if known else None
    groups: dict[str, list[tuple[float, float]]] = {}
    for i, (x, y) in enumerate(zip(r, b, strict=True)):
        if x is None or y is None:
            continue
        lo = max(0, i - 252)
        trail = res.bench[i] / res.bench[lo] - 1 if res.bench[i] and res.bench[lo] else None
        if trail is not None:
            groups.setdefault("bull" if trail > 0 else "bear", []).append((x, y))
        if median is not None and rates[i] is not None:
            groups.setdefault("high_rates" if rates[i] > median else "low_rates", []).append((x, y))
    out = {}
    for name, pairs in groups.items():
        s = stats._mean([p[0] for p in pairs]) * 252
        bm = stats._mean([p[1] for p in pairs]) * 252
        out[name] = {"days": len(pairs), "ann_return_pct": round(s * 100, 4), "excess_pts": round((s - bm) * 100, 4)}
    return out


# ---- Finalize ----


def finalize(cfg: Config, conn, data: LabData, request: dict, *, now: datetime) -> dict:
    sid, version = str(request.get("strategy_id") or ""), int(request.get("version") or 0)
    row = conn.execute("SELECT * FROM strategies WHERE id=? AND version=?", (sid, version)).fetchone()
    raw = {"id": sid, "version": version}
    if row is None:
        return _reject(conn, raw, [f"{sid} v{version} was never run; send an experiment first"], now)
    if row["status"] != "lab":
        return _reject(conn, raw, [f"{sid} v{version} is already finalized ({row['status']})"], now)
    exp = conn.execute(
        "SELECT body FROM lab_results WHERE strategy_id=? AND version=? AND kind='experiment' ORDER BY result_at DESC LIMIT 1", (sid, version)
    ).fetchone()
    if exp is None:
        return _reject(conn, raw, [f"{sid} v{version} has no experiment result yet"], now)
    exp = json.loads(exp["body"])
    spec = parse(json.loads(row["spec"]), data, model=row["model"] or "")
    if not exp.get("deploy_params"):
        body = {"verdict": "fail", "bars": {}, "note": "No variant met the constraints in any fold."}
        _close(conn, spec, "failed")
        return _record(conn, spec, "finalize", body, now)
    v = resolve(spec, exp["deploy_params"])
    last = data.end_for(spec.universe.get("kind"))
    hold = simulate(data, spec, v, exp["windows"]["holdout_start"], last)
    holdout = stats.summary(hold)
    cutoff = cutoff_for(spec.model)
    post = None
    if cutoff < last:
        res = simulate(data, spec, v, max(cutoff, exp["windows"]["start"]), last)
        post = stats.summary(res) if len(res.days) >= POST_CUTOFF_MIN_DAYS else {"days": len(res.days), "note": "Too short to read yet."}
    with conn:
        _trial(conn, spec, v, f"{exp['windows']['holdout_start']}..{last}", "holdout", holdout, now)
    bars = _bars(spec, exp, holdout)
    survivorship = None
    if spec.universe.get("kind") == SMALL_CAPS:
        stress = stats.summary(simulate(data, spec, v, exp["windows"]["holdout_start"], last, delist_haircut=1.0))
        drift = any(m.startswith("earnings.") for m, _, _ in spec.signals)
        survivorship = _survivorship(data.coverage("earnings_coverage" if drift else "insider_coverage"), stress, "earnings" if drift else "insider-cluster")
        bars["delist_total_loss"] = survivorship["stress_excess_pts"] > 0 if survivorship["stress_excess_pts"] is not None else None
        bars["price_coverage"] = survivorship["coverage_ok"]
    factor_ran = bars["factor"] is not None
    computed = [x for k, x in bars.items() if k != "factor" or factor_ran]
    verdict = "fail" if any(x is False for x in computed) else ("pass" if computed and all(x is True for x in computed) else "inconclusive")
    research = spec.universe.get("kind") == FRENCH_KIND or spec.universe.get("set") == HELD_SET
    status = {"pass": "research" if research else "paper", "fail": "failed", "inconclusive": "inconclusive"}[verdict]
    _close(conn, spec, status)
    body = {
        "verdict": verdict,
        "bars": bars,
        "params": exp["deploy_params"],
        "walk_forward": exp.get("walk_forward"),
        "holdout": holdout,
        "post_cutoff": {"cutoff": cutoff, **(post or {"days": 0, "note": "The data ends before the model's training cutoff."})},
        "paper_start": last if verdict == "pass" and not research else None,
        "factor_check": exp.get("factor_check"),
        "survivorship": survivorship,
        "caveats": exp.get("caveats", []) + ([survivorship["note"]] if survivorship else []),
    }
    return _record(conn, spec, "finalize", body, now)


def _survivorship(cov: dict | None, stress: dict, label: str = "insider-cluster") -> dict:
    x = stress.get("excess_vs_bench_pts")
    if not cov or not cov.get("clusters"):
        return {"coverage_ok": None, "stress_excess_pts": x, "note": f"No price-coverage count for {label} names yet, so the verdict waits for it."}
    missing = cov["unpriced"] + cov["pending"]
    share = missing / cov["clusters"]
    ok = None if cov["pending"] or share > COVERAGE_MAX_MISSING else True
    note = (
        f"{cov['unpriced']} of {cov['clusters']} {label} names have no price after the event (likely delisted) and {cov['pending']} "
        f"are still loading; they are left out, which can flatter results. {cov['ended_within_a_year']} priced names stopped trading within a year "
        f"of their first event. "
    )
    if x is None:
        note += "The total-loss stress could not be measured."
    else:
        note += f"With every delisting as a total loss the holdout {'beats' if x > 0 else 'trails'} the benchmark by {abs(x):.2f} points a year."
    return cov | {"missing_share": round(share, 4), "coverage_ok": ok, "stress_excess_pts": x, "note": note}


def _close(conn, spec: Spec, status: str):
    with conn:
        conn.execute("UPDATE strategies SET status=? WHERE id=? AND version=?", (status, spec.id, spec.version))


def _bars(spec: Spec, exp: dict, holdout: dict) -> dict:
    wf = exp.get("walk_forward") or {}
    longest = next((h for h in sorted(exp.get("horizons") or [], key=lambda h: -h["years"]) if h.get("starts")), None)
    bars = {
        "excess_interval": (longest["p5_pts"] > 0) if longest else None,
        "deflated_sharpe": (exp["deflated_sharpe"] > DSR_BAR) if exp.get("deflated_sharpe") is not None else None,
        "pbo": (exp["pbo"] < PBO_BAR) if exp.get("pbo") is not None else None,
        "factor": factors.bar(exp.get("factor_check")),
    }
    wf_x, h_x = wf.get("excess_pts"), holdout.get("excess_vs_bench_pts")
    bars["holdout"] = None if wf_x is None or h_x is None else bool(wf_x > 0 and h_x > 0 and h_x >= wf_x / 2)
    crit = spec.success_criteria
    if "excess_vs_plan_pts" in crit and wf_x is not None:
        bars["criteria_excess"] = wf_x >= float(crit["excess_vs_plan_pts"])
    if "max_drawdown_pct" in crit and wf.get("mdd_pct") is not None:
        bars["criteria_drawdown"] = wf["mdd_pct"] >= -abs(float(crit["max_drawdown_pct"]))
    if "min_trades" in crit:
        trades = sum((f.get("test") or {}).get("trades", 0) for f in exp.get("folds", []))
        bars["criteria_trades"] = trades >= int(crit["min_trades"])
    return bars


# ---- Simulations as a job (pure: lab data + request in, rows out) ----


EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def sims(path: Path, request: dict) -> dict:
    data = load(path)
    snapshot = simcache.snapshot_hash(path)
    out = {"kind": simcache.KIND, "key": simcache.job_key(snapshot, request), "snapshot": snapshot, "request": request, "rows": []}
    if request.get("request") != "experiment" or local_only(request.get("spec")):
        return out | {"status": "nothing_to_simulate"}
    scratch = sqlite3.connect(":memory:")
    scratch.row_factory = sqlite3.Row
    scratch.executescript(LEDGER)
    cache = Cache(snapshot)
    try:
        body = run_experiment(None, scratch, data, request, now=EPOCH, cache=cache)
    finally:
        scratch.close()
    rows, days = [], 0
    for r in cache.rows():
        days += len(r["days"])
        if days > simcache.MAX_DAYS or len(rows) >= simcache.MAX_ROWS:
            return out | {"status": body["kind"], "rows": rows, "partial": True}
        rows.append(r)
    return out | {"status": body["kind"], "rows": rows}


def ingest(cfg: Config, data: LabData, cache: Cache) -> list[dict]:
    done = []
    for path in simcache.staged(cfg):
        result = simcache.read_staged(path)
        row = {"file": path.name, **_ingest_one(data, cache, result)}
        if result is not None and isinstance(result.get("request"), dict):
            row["job"] = simcache.job_key(cache.snapshot, result["request"])
        done.append(row)
        path.unlink(missing_ok=True)
    return done


def _ingest_one(data: LabData, cache: Cache, result: dict | None) -> dict:
    if result is None or not isinstance(result.get("rows"), list) or not isinstance(result.get("request"), dict):
        return {"status": "unreadable"}
    if result.get("snapshot") != cache.snapshot:
        return {"status": "stale", "note": "Made from lab data that has since been replaced."}
    request = result["request"]
    try:
        spec = parse(request.get("spec") or {}, data, model=str(request.get("model") or ""))
    except SpecError as e:
        return {"status": "rejected", "note": "; ".join(e.problems)[:300]}
    rows = result["rows"][: simcache.MAX_ROWS]
    for body in rows:
        why = simcache.problems(body, cache.snapshot, spec.hash)
        if why:
            return {"status": "rejected", "note": why}
    spot = sorted(rows, key=lambda r: hashlib.sha256((cache.snapshot + r["key"]).encode()).hexdigest())[: simcache.SPOT_CHECKS]
    again = _compute(data, spec, [(r["params"], r["start"], r["end"], r["cost_mult"]) for r in spot])
    for body, run in zip(spot, again, strict=True):
        if simcache.row(body["key"], (body["params"], body["start"], body["end"], body["cost_mult"]), run) != body:
            return {"status": "mismatch", "note": "A recomputed row differs, so none of the rows were kept."}
    return {"status": "stored", "rows": len(rows), "new": cache.put(rows)}


# ---- Queue ----


def process_queue(cfg: Config, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    folder = lab_dir(cfg) / "queue"
    if not folder.exists():
        return {"ok": True, "done": []}
    if not data_path(cfg).exists():
        load(data_path(cfg))
    conn = ledger(cfg)
    done, cache, held, staged = [], None, [], []
    try:
        waiting = [p for p in sorted(folder.glob("*.json")) if not conn.execute("SELECT 1 FROM queue_done WHERE file=?", (p.name,)).fetchone()]
        if not waiting and not simcache.staged(cfg):
            return {"ok": True, "done": []}
        cache = simcache.open_cache(cfg, simcache.snapshot_hash(data_path(cfg)), now=now)
        offers = simcache.open_offers(cfg, cache.snapshot, now, cache.last_answer())
        seen = simcache.worker_seen(cfg, now)

        def owed(path: Path) -> bool:
            key = offers.get(path.name)
            return not cache.answered(key) if key else seen and simcache.just_queued(path, now)

        if waiting and not simcache.staged(cfg) and owed(waiting[0]):
            return {"ok": True, "done": [], "waiting_for_worker": [p.name for p in waiting]}
        data = load(data_path(cfg))
        staged = ingest(cfg, data, cache)
        for s in staged:
            if s.get("job"):
                cache.answer(s.pop("job"))
        if staged:
            offers = simcache.open_offers(cfg, cache.snapshot, now, cache.last_answer())
        for path in waiting:
            if owed(path):
                held = [p.name for p in waiting[waiting.index(path) :]]
                break
            try:
                request = json.loads(path.read_text())
            except (OSError, ValueError):
                status = "unreadable"
            else:
                kind = request.get("request")
                if kind == "experiment":
                    status = run_experiment(cfg, conn, data, request, now=now, cache=cache)["kind"]
                elif kind == "finalize":
                    status = finalize(cfg, conn, data, request, now=now)["kind"]
                elif kind == "rule":
                    status = rulebook.run(conn, data, request, now=now)["kind"]
                else:
                    status = "unknown_request"
            with conn:
                conn.execute("INSERT OR REPLACE INTO queue_done VALUES (?, ?, ?)", (path.name, status, _stamp(now)))
            done.append({"file": path.name, "status": status})
    finally:
        conn.close()
        if cache is not None:
            cache.close()
    out = {"ok": True, "done": done}
    if staged:
        out["sims"] = staged
    if cache.hits or cache.misses:
        out["cache"] = {"hits": cache.hits, "computed": cache.misses}
    if held:
        out["waiting_for_worker"] = held
    return out

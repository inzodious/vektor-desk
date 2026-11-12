import io
import json
import random
import sqlite3
import zipfile
from datetime import UTC, datetime

import pytest

from desk.db import connect
from desk.engine import french, lab, schema
from desk.engine.jobs import JOBS
from desk.engine.lab import data as lab_data
from desk.engine.lab import factors
from desk.engine.lab.data import EXPORT_SCHEMA, FRENCH_MARKET, data_path, ledger_path, load
from desk.engine.lab.runner import ledger, process_queue
from desk.engine.lab.spec import SpecError, parse
from tests.engine.test_lab import NOW, queue, weekdays

INDUSTRIES = ("NoDur", "Durbl", "Manuf", "Enrgy", "Chems", "BusEq", "Telcm", "Utils", "Shops", "Hlth", "Money", "Other")
FACTOR_CSV = """This file was created by CMPT_ME_BEME_OP_INV_RETS_DAILY using the 202509 CRSP database.
The Tbill return is the simple daily rate that, over the number of trading days
in the month, compounds to 1-month TBill rate from Ibbotson and Associates Inc.

,Mkt-RF,SMB,HML,RMW,CMA,RF
19630701,   -0.67,    0.00,   -0.32,   -0.01,    0.15,    0.012
19630702,    0.79,   -0.27,    0.27,   -0.07,   -0.19,    0.012
19630703,    0.63,   -0.17,   -0.09,    0.17,   -0.33,    0.012
"""
MOM_CSV = """This file was created using the 202509 CRSP database.

,Mom
19630701,   -0.23
19630702,    0.44
19630703,  -99.99
"""
MONTHLY_CSV = """This file was created by CMPT_ME_BEME_RETS using the 202509 CRSP database.

,Mkt-RF,SMB,HML,RF
192607,    2.89,   -2.55,   -2.39,    0.22
192608,    2.64,   -1.14,    3.81,    0.25

 Annual Factors: January-December
,Mkt-RF,SMB,HML,RF
  1927,   29.47,   -2.04,   -4.30,    3.12
"""
SIZE_CSV = """This file was created by CMPT_ME_RETS_DAILY.

  Value Weight Returns -- Daily
,<= 0,Lo 30,Med 40,Hi 30,Lo 20,Qnt 2,Qnt 3,Qnt 4,Hi 20,Lo 10,Dec 2,Dec 3,Dec 4,Dec 5,Dec 6,Dec 7,Dec 8,Dec 9,Hi 10
19630701,-99.99,0.1,0.2,0.3,0.1,0.2,0.3,0.4,0.5,1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0,10.0
19630702,-99.99,0.1,0.2,0.3,0.1,0.2,0.3,0.4,0.5,1.5,2.5,3.5,4.5,5.5,6.5,7.5,8.5,9.5,10.5

  Equal Weight Returns -- Daily
,<= 0,Lo 30,Med 40,Hi 30,Lo 20,Qnt 2,Qnt 3,Qnt 4,Hi 20,Lo 10,Dec 2,Dec 3,Dec 4,Dec 5,Dec 6,Dec 7,Dec 8,Dec 9,Hi 10
19630701,-99.99,9,9,9,9,9,9,9,9,9,9,9,9,9,9,9,9,9,9
"""
INDUSTRY_CSV = (
    """This file was created by CMPT_IND_RETS_DAILY.

  Average Value Weighted Returns -- Daily
,"""
    + ",".join(INDUSTRIES)
    + """
19630701,"""
    + ",".join(["0.5"] * 12)
    + """
19630702,"""
    + ",".join(["-0.25"] * 12)
    + """

  Average Equal Weighted Returns -- Daily
,"""
    + ",".join(INDUSTRIES)
    + """
19630701,"""
    + ",".join(["9"] * 12)
    + "\n"
)


def zipped(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


class Res:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


class Http:
    def __init__(self):
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        files = {
            "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip": FACTOR_CSV,
            "F-F_Momentum_Factor_daily_CSV.zip": MOM_CSV,
            "12_Industry_Portfolios_daily_CSV.zip": INDUSTRY_CSV,
            "Portfolios_Formed_on_ME_daily_CSV.zip": SIZE_CSV,
            "Portfolios_Formed_on_BE-ME_Daily_CSV.zip": SIZE_CSV,
            "Portfolios_Formed_on_OP_Daily_CSV.zip": SIZE_CSV,
            "Portfolios_Formed_on_INV_Daily_CSV.zip": SIZE_CSV,
            "F-F_Research_Data_Factors_CSV.zip": MONTHLY_CSV,
        }
        name = url.rsplit("/", 1)[-1]
        if name in files:
            return Res(200, zipped(name.replace(".zip", ".csv"), files[name]))
        if name == "49_Industry_Portfolios_daily_CSV.zip":
            return Res(200, b"not a zip")
        return Res(404)


# ---- Fetch ----


def test_first_block_reads_only_value_weighted_rows():
    header, rows = french.first_block(SIZE_CSV)
    assert header[0] == "<= 0" and len(rows) == 2 and rows[0][0] == "1963-07-01" and rows[0][1][0] is None
    cols = french.pick_columns("size_deciles", header)
    assert [header[i] for i in cols] == list(french.DECILES)
    assert french.pick_columns("momentum_deciles", ["a", "b"] + [f"x{i}" for i in range(10)]) == list(range(2, 12))
    for name in ("value_deciles", "profitability_deciles", "investment_deciles"):
        assert [header[i] for i in french.pick_columns(name, header)] == list(french.DECILES) and french.PORTFOLIO_FILES[name].endswith("_Daily_CSV.zip")


def test_french_job_fills_factors_and_portfolios_and_waits_a_month(desk_db):
    http = Http()
    now = datetime(2026, 11, 2, 8, 30, tzinfo=UTC)
    result = french.run(desk_db, http, now=now)
    assert not result["ok"] and any("49_Industry" in e for e in result["errors"])
    factors_ = {r[0]: r[1] for r in desk_db.execute("SELECT series, count(*) FROM factors_daily GROUP BY series")}
    assert factors_ == {"mkt_rf": 3, "smb": 3, "hml": 3, "rmw": 3, "cma": 3, "rf": 3, "mom": 2, "mkt_rf_m": 2, "rf_m": 2}
    assert desk_db.execute("SELECT date, value FROM factors_daily WHERE series='rf_m' ORDER BY date").fetchall()[0][:] == ("1926-07-01", 0.22)
    size = desk_db.execute("SELECT name, ret FROM french_returns WHERE set_name='size_deciles' AND date='1963-07-02' ORDER BY ret").fetchall()
    assert [r[0] for r in size] == list(french.DECILES) and size[0][1] == 1.5
    assert desk_db.execute("SELECT count(*) FROM french_returns WHERE set_name='industry_12'").fetchone()[0] == 24
    calls = len(http.calls)
    french.run(desk_db, http, now=now)
    assert len(http.calls) == calls + 2
    assert all("Momentum" not in c and "5_Factors" not in c for c in http.calls[calls:])
    calls = len(http.calls)
    with desk_db:
        desk_db.execute("DELETE FROM french_returns WHERE set_name='size_deciles'")
        desk_db.execute("DELETE FROM factors_daily WHERE series='mom'")
    french.run(desk_db, http, now=now)
    fetched = [c for c in http.calls[calls:] if "49_Industry" not in c and "Prior_12_2" not in c]
    assert len(fetched) == 2 and any("Momentum" in c for c in fetched) and any("Formed_on_ME" in c for c in fetched)
    assert desk_db.execute("SELECT count(*) FROM french_returns WHERE set_name='size_deciles'").fetchone()[0] > 0
    assert {"schedule": "30 0 * * *", "command": "python -m desk.engine french", "overnight": 100} in JOBS


# ---- Lab data ----


def french_lab(cfg, start="2004-01-01", end="2024-12-31", seed_=5, alpha_industry="BusEq"):
    rng = random.Random(seed_)
    days = weekdays(start, end)
    path = data_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(EXPORT_SCHEMA)
    fac, fr = [], []
    for d in days:
        f = {"mkt_rf": rng.gauss(0.03, 1.0), "smb": rng.gauss(0, 0.5), "hml": rng.gauss(0, 0.5), "rmw": rng.gauss(0, 0.3)}
        f |= {"cma": rng.gauss(0, 0.3), "mom": rng.gauss(0.02, 0.7), "rf": 0.008}
        fac += [(k, d, v) for k, v in f.items()]
        for j, name in enumerate(INDUSTRIES):
            beta = 0.7 + j * 0.05
            r = f["rf"] + beta * f["mkt_rf"] + rng.gauss(0, 0.6)
            if name == alpha_industry:
                r += 0.03
            fr.append(("industry_12", name, d, r))
    conn.executemany("INSERT INTO factors VALUES (?, ?, ?)", fac)
    conn.executemany("INSERT INTO french VALUES (?, ?, ?, ?)", fr)
    conn.execute("INSERT INTO settings VALUES ('marginal_rate_pct', '24')")
    conn.commit()
    conn.close()
    return days


def test_export_carries_factors_and_french_in_rollback_journal(cfg):
    desk = connect(cfg.desk_db)
    schema.apply(desk)
    with desk:
        desk.executemany("INSERT INTO price_bars (symbol, date, open, close, adj_close) VALUES ('SPY', ?, 99, 100, 100)", [("2024-01-02",), ("2024-01-03",)])
        facts = [("mkt_rf", "2024-01-02", 1.0), ("rf", "2024-01-02", 0.02), ("mkt_rf", "2024-01-03", -2.0)]
        desk.executemany("INSERT INTO factors_daily VALUES (?, ?, ?)", facts)
        desk.executemany("INSERT INTO french_returns VALUES ('industry_12', ?, ?, ?)", [("Hlth", "2024-01-02", 1.0), ("Hlth", "2024-01-03", 2.0)])
    result = lab_data.export(cfg, desk, {}, {})
    desk.close()
    assert result["french_rows"] == 2
    raw = sqlite3.connect(data_path(cfg))
    assert raw.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal"
    raw.close()
    data = load(data_path(cfg))
    assert data.calendar == ["2024-01-02", "2024-01-03"] and "FF.industry_12.Hlth" not in data.series
    assert data.series[FRENCH_MARKET].adj == pytest.approx([101.02, 101.02 * 0.98])
    assert data.french("industry_12") == ["FF.industry_12.Hlth"] and data.series["FF.industry_12.Hlth"].adj[-1] == pytest.approx(103.02)
    assert data.french("size_deciles") == [] and data.kinds["FF.industry_12.Hlth"] == "french"


def test_french_portfolios_share_one_calendar(cfg):
    french_lab(cfg, start="2023-01-02", end="2023-03-31")
    data = load(data_path(cfg))
    syms = data.french("industry_12")
    assert len(syms) == 12 and data.series[syms[0]].dates is data.series[syms[1]].dates
    assert data.calendar_for("french")[0] == "2023-01-02" and data.end_for("french") == "2023-03-31"


# ---- Factor check ----


def test_factor_regression_recovers_loadings_and_flags_disguise():
    rng = random.Random(3)
    days = weekdays("2015-01-01", "2019-12-31")
    fac = {k: {} for k in (*factors.FACTORS, "rf")}
    for d in days:
        for k in factors.FACTORS:
            fac[k][d] = rng.gauss(0, 1.0)
        fac["rf"][d] = 0.01

    def path(alpha, mom):
        vals = [100.0]
        for d in days[1:]:
            r = fac["rf"][d] + alpha + 0.9 * fac["mkt_rf"][d] + mom * fac["mom"][d] + rng.gauss(0, 0.3)
            vals.append(vals[-1] * (1 + r / 100))
        return vals

    disguised = factors.regress(days, path(0.0, 0.6), fac)
    assert disguised["status"] == "ok" and disguised["label"] == "factor_in_disguise" and disguised["tilts"] == ["mom"]
    assert disguised["loadings"]["mkt_rf"]["beta"] == pytest.approx(0.9, abs=0.05) and disguised["loadings"]["mom"]["beta"] == pytest.approx(0.6, abs=0.05)
    assert factors.bar(disguised) is False
    real = factors.regress(days, path(0.08, 0.0), fac)
    assert real["label"] == "alpha" and real["alpha_t"] >= 2 and real["alpha_ann_pct"] == pytest.approx(20.16, rel=0.25) and factors.bar(real) is True
    assert factors.regress(days[:100], path(0.0, 0.0)[:100], fac)["status"] == "not_available"
    assert factors.regress(days, path(0.0, 0.0), {})["status"] == "not_available" and factors.bar(None) is None


def test_inverse_and_singular():
    inv = factors.inverse([[4.0, 7.0], [2.0, 6.0]])
    assert inv[0] == pytest.approx([0.6, -0.7]) and inv[1] == pytest.approx([-0.2, 0.4])
    assert factors.inverse([[1.0, 2.0], [2.0, 4.0]]) is None


# ---- French universe ----

FRENCH_SPEC = {
    "id": "industry-momentum",
    "version": 1,
    "title": "Industry momentum",
    "universe": {"type": "french", "set": "industry_12"},
    "signals": [{"metric_id": "ret", "window": "{lookback}d", "transform": "rank"}],
    "entry": {"top_n": "param:top_n"},
    "exit": "rebalance",
    "rebalance": "monthly",
    "params": {"top_n": {"min": 1, "max": 4, "default": 3}, "lookback": {"min": 21, "max": 252, "default": 126}},
    "horizons": [5],
}


def test_french_spec_parses_and_needs_data(cfg):
    french_lab(cfg, start="2023-01-02", end="2023-03-31")
    data = load(data_path(cfg))
    spec = parse(FRENCH_SPEC, data)
    assert spec.universe == {"kind": "french", "set": "industry_12"} and spec.benchmark == FRENCH_MARKET
    assert any("not funds you can buy" in c for c in spec.caveats)
    with pytest.raises(SpecError) as e:
        parse(FRENCH_SPEC | {"universe": {"type": "french", "set": "momentum_deciles"}}, data)
    assert "not in the lab yet" in str(e.value)
    with pytest.raises(SpecError):
        parse(FRENCH_SPEC | {"universe": {"type": "french", "set": "stocks"}}, data)


def test_french_experiment_runs_factor_check_and_stays_research(cfg):
    french_lab(cfg)
    queue(
        cfg,
        {"request": "experiment", "spec": FRENCH_SPEC, "grid": {"top_n": [1, 3], "lookback": [126]}, "analyses": ["factor_regression"], "model": "m"},
        "001-exp.json",
    )
    queue(cfg, {"request": "finalize", "strategy_id": "industry-momentum", "version": 1}, "002-fin.json")
    done = process_queue(cfg, now=NOW)["done"]
    assert [d["status"] for d in done] == ["experiment", "finalize"]
    view = lab.desk_view(cfg, "industry-momentum")
    check = view["tear_sheet"]["factor_check"]
    assert check["status"] == "ok" and set(check["loadings"]) == set(factors.FACTORS)
    assert view["analyses"]["factor_regression"] == check and view["tear_sheet"]["windows"]["holdout_start"] == "2022-12-31"
    assert view["final"]["bars"]["factor"] is factors.bar(check)
    assert view["status"] in ("research", "failed", "inconclusive") and view["final"]["paper_start"] is None


# ---- Ledger ----


def test_old_ledger_migrates_to_new_statuses(cfg):
    path = ledger_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(path)
    old.executescript("""
CREATE TABLE strategies (id TEXT NOT NULL, version INTEGER NOT NULL, spec_hash TEXT NOT NULL, parent_id TEXT, title TEXT,
  status TEXT NOT NULL CHECK (status IN ('lab', 'paper', 'failed', 'inconclusive')), registered_at TEXT NOT NULL, model TEXT, written_at TEXT,
  spec TEXT NOT NULL, PRIMARY KEY (id, version)) WITHOUT ROWID;
CREATE TABLE lab_results (strategy_id TEXT NOT NULL, version INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('experiment', 'finalize', 'rejected')),
  result_at TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (strategy_id, version, kind, result_at)) WITHOUT ROWID;
INSERT INTO strategies VALUES ('a', 1, 'h', NULL, 'A', 'lab', '2026-01-01', NULL, NULL, '{}');
INSERT INTO lab_results VALUES ('a', 1, 'experiment', '2026-01-01', '{}');
""")
    old.close()
    conn = ledger(cfg)
    with conn:
        conn.execute("UPDATE strategies SET status='research'")
        conn.execute("INSERT INTO lab_results VALUES ('r', 1, 'rule', '2026-01-02', ?)", (json.dumps({}),))
    assert conn.execute("SELECT count(*) FROM lab_results").fetchone()[0] == 2
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'old_%'").fetchone()
    conn.close()
    ledger(cfg).close()

import random
from datetime import date, timedelta

import pytest

from desk.db import connect
from desk.engine import gate, schema

START = "2026-01-05"


def path(days: int, edge: float, te: float, seed: int, start: str = START):
    rng = random.Random(seed)
    d0 = date.fromisoformat(start)
    out_days, values, bench = [start], [1000.0], [1.0]
    for i in range(1, days + 1):
        d = d0 + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        b = rng.gauss(0.0003, 0.01)
        gap = rng.gauss(edge / 252, te / 252**0.5)
        out_days.append(d.isoformat())
        bench.append(bench[-1] * (1 + b))
        values.append(values[-1] * (1 + b + gap))
    return out_days, values, bench


def desk(cfg):
    conn = connect(cfg.desk_db)
    schema.apply(conn)
    return conn


# ---- Noise band ----


def test_measure_reads_excess_against_its_own_noise():
    values = [100.0, 104.0, 103.0, 109.0, 112.0]
    bench = [1.0, 1.01, 1.02, 1.03, 1.04]
    m = gate.measure(values, bench)
    assert m["obs"] == 4 and m["excess_pts"] == pytest.approx(8.0)
    assert m["score"] == pytest.approx(m["excess_pts"] / m["noise_pts"], abs=1e-3)
    assert m["band_pts"] == pytest.approx(1.2816 * m["noise_pts"], rel=1e-3) and m["retire_pts"] == pytest.approx(-m["band_pts"])
    assert 0 < m["luck"] < 0.5 and m["luck"] == m["luck_alone"]
    assert gate.measure([100.0, 101.0], [1.0, 1.0]) is None
    flat = gate.measure([100.0, 100.0, 100.0], [1.0, 1.0, 1.0])
    assert flat["luck"] is None and gate.judge(flat | {"obs": 200}) == ("unproven", "short_record")


def test_a_hair_under_an_index_twin_is_not_a_verdict():
    _, _, bench = path(182, 0.0, 0.08, 9)
    twin = [1000.0] + [1000.0 * b * 0.997 for b in bench[1:]]
    m = gate.measure(twin, bench)
    assert m["retire_pts"] == -gate.MIN_BAND_PTS and m["band_pts"] == gate.MIN_BAND_PTS
    assert gate.judge(m) == ("unproven", "noise")


def test_a_crowded_family_needs_a_wider_band():
    _, values, bench = path(182, 0.2, 0.15, 3)
    alone, crowd = gate.measure(values, bench), gate.measure(values, bench, family_size=12)
    assert crowd["band_pts"] > alone["band_pts"] * 1.5 and crowd["retire_pts"] == alone["retire_pts"]
    assert crowd["luck"] > alone["luck"] and crowd["luck_alone"] == alone["luck"]


def test_judge_names_why():
    base = {"obs": 120, "band_pts": 10.0, "retire_pts": -10.0}
    assert gate.judge(base | {"excess_pts": 2.0}) == ("unproven", "noise")
    assert gate.judge(base | {"excess_pts": -0.1}) == ("unproven", "noise")
    assert gate.judge(base | {"excess_pts": -10.5}) == ("retired", "behind")
    assert gate.judge(base | {"excess_pts": 12.0}) == ("eligible", "ahead")
    assert gate.judge(base | {"excess_pts": 12.0}, events=12) == ("unproven", "events")
    assert gate.judge(base | {"excess_pts": 12.0}, events=30, bars=False) == ("unproven", "bars")
    assert gate.judge(base | {"excess_pts": 12.0, "obs": 40}) == ("unproven", "short_record")
    assert gate.judge(None) == ("unproven", "short_record")


def test_checkpoints_are_day_182_then_every_91():
    assert gate.checkpoints(181) == [] and gate.checkpoints(182) == [182] and gate.checkpoints(370) == [182, 273, 364]
    assert gate.next_checkpoint(10) == 182 and gate.next_checkpoint(182) == 273 and gate.next_checkpoint(272) == 273
    assert gate.family("insider-clusters-3") == "insider" and gate.family("filings-fast") == "filings"
    assert gate.family("sector-momentum") is None and gate.family("drift") is None


# ---- F1: a coin flip no longer passes ----


def test_no_edge_rarely_passes_and_a_loser_almost_never(cfg):
    def share(edge, te):
        verdicts = [gate.judge(gate.measure(*path(182, edge, te, seed)[1:]))[0] for seed in range(400)]
        return verdicts.count("eligible") / 400, verdicts.count("retired") / 400

    flat_pass, flat_out = share(0.0, 0.15)
    assert flat_pass < 0.16 and flat_out < 0.16
    lose_pass, lose_out = share(-0.05, 0.08)
    assert lose_pass < 0.08 and lose_out > lose_pass
    win_pass, win_out = share(0.30, 0.08)
    assert win_pass > 0.85 and win_out < 0.01


# ---- F2: a verdict is stored once ----


def test_a_verdict_is_stored_at_the_checkpoint_and_does_not_flip(cfg):
    conn = desk(cfg)
    days, values, bench = path(200, 0.5, 0.08, 5)
    first = gate.settle(conn, "s", 1, START, days, values, bench)
    assert first["status"] == "eligible" and first["gate"]["verdict"]["checkpoint"] == 182 and first["gate"]["verdict"]["reason"] == "ahead"
    assert first["gate"]["verdict"]["as_of"] == "2026-07-06" and first["gate"]["next_checkpoint"] == {"day": 273, "on": "2026-10-05"}
    crashed = values[:-1] + [values[-1] * 0.5]
    again = gate.settle(conn, "s", 1, START, days, crashed, bench)
    assert again["status"] == "eligible" and again["gate"]["verdict"] == first["gate"]["verdict"]
    assert again["gate"]["luck"] > first["gate"]["luck"]
    assert conn.execute("SELECT count(*) FROM paper_verdicts").fetchone()[0] == 1
    conn.close()


def test_the_verdict_uses_only_the_days_up_to_its_checkpoint(cfg):
    conn = desk(cfg)
    days, values, bench = path(182, 0.5, 0.08, 5)
    late_days, late_values, late_bench = path(240, 0.5, 0.08, 5)
    on_time = gate.settle(conn, "a", 1, START, days, values, bench)["gate"]["verdict"]
    late = gate.settle(conn, "b", 1, START, late_days, late_values[: len(values)] + [1.0] * (len(late_values) - len(values)), late_bench)["gate"]["verdict"]
    assert on_time == late
    conn.close()


def test_one_bad_day_under_the_benchmark_does_not_retire(cfg):
    conn = desk(cfg)
    days, values, bench = path(182, 0.0, 0.08, 9)
    level = [v / values[-1] * 1000.0 * bench[-1] for v in values[:-1]] + [1000.0 * bench[-1] * 0.999]
    level = [1000.0] + level[1:]
    out = gate.settle(conn, "mix", 1, START, days, level, bench)
    assert out["gate"]["verdict"]["excess_pts"] < 0
    assert out["status"] == "paper" and out["gate"]["verdict"]["verdict"] == "unproven" and out["gate"]["verdict"]["reason"] == "noise"
    conn.close()


def test_later_checkpoints_can_demote_and_a_retire_is_final(cfg):
    conn = desk(cfg)
    days, values, bench = path(300, 0.5, 0.08, 5)
    cut = next(i for i, d in enumerate(days) if d > "2026-07-06")
    sunk = values[:cut] + [v * 0.75 for v in values[cut:]]
    assert gate.settle(conn, "s", 1, START, days[:cut], sunk[:cut], bench[:cut])["status"] == "eligible"
    later = gate.settle(conn, "s", 1, START, days, sunk, bench)
    assert later["status"] == "paper" and later["gate"]["checkpoints"] == 2 and later["gate"]["verdict"]["checkpoint"] == 273
    days, values, bench = path(400, -0.6, 0.08, 6)
    cut = next(i for i, d in enumerate(days) if d > "2026-07-06")
    lost = gate.settle(conn, "bad", 1, START, days[:cut], values[:cut], bench[:cut])
    assert lost["status"] == "retired" and lost["gate"]["next_checkpoint"] is None and lost["gate"]["verdict"]["reason"] == "behind"
    recovered = values[:cut] + [v * 3 for v in values[cut:]]
    final = gate.settle(conn, "bad", 1, START, days, recovered, bench)
    assert final["status"] == "retired" and final["gate"]["checkpoints"] == 1
    conn.close()


def test_passing_needs_enough_events_and_the_backtest_bars(cfg):
    conn = desk(cfg)
    days, values, bench = path(182, 0.5, 0.08, 5)
    few = gate.settle(conn, "few", 1, START, days, values, bench, events=lambda cut: 12)
    assert few["status"] == "paper" and few["gate"]["verdict"]["reason"] == "events" and few["gate"]["min_events"] == 30
    unbacked = gate.settle(conn, "raw", 1, START, days, values, bench, events=lambda cut: 40, bars=False)
    assert unbacked["status"] == "paper" and unbacked["gate"]["verdict"]["reason"] == "bars"
    full = gate.settle(conn, "ok", 1, START, days, values, bench, events=lambda cut: 40, bars=True)
    assert full["status"] == "eligible" and full["gate"]["verdict"]["events"] == 40
    conn.close()

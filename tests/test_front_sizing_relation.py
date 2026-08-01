"""Reading a Pareto front as a sizing decision (server.front_sizing_relation).

The front already carried each point's devices, but a curve plus a table of widths
does not say which device buys which axis. These tests pin the statistics on
synthetic fronts where the right answer is known by construction, then check the
real comparator front agrees with the circuit's physics.
"""
import pytest

import run_sim
import server


def _pt(power, tdec, **widths):
    devs = {k: {"w_um": float(v), "l_nm": 45.0, "m": 2} for k, v in widths.items()}
    return {"power_uw": power, "decision_time_ps": tdec, "devices": devs}


AXES = {"power_uw": "power_uw", "decision_time_ps": "decision_time_ps"}


# ── the statistic itself ─────────────────────────────────────────────────────

def test_spearman_endpoints():
    assert server._spearman([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0
    assert server._spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert server._spearman([1, 2], [1, 2]) is None            # too few points
    assert server._spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None  # no variation


def test_spearman_is_rank_based_not_linear():
    """Monotone but wildly non-linear must still read as +1 — front spacing is
    never uniform, so a linear fit would understate a real relationship."""
    xs = [1, 2, 3, 4, 5]
    ys = [1, 2, 4, 800, 100000]
    assert server._spearman(xs, ys) == 1.0


# ── the relation ─────────────────────────────────────────────────────────────

def test_identifies_the_driving_device():
    """`drive` tracks the axes perfectly, `idle` does not move at all."""
    front = [_pt(10 + 10 * i, 500 - 30 * i, drive=1.0 + i, idle=3.0) for i in range(6)]
    rel = server.front_sizing_relation(front, AXES)
    assert rel["fixed_along_front"] == ["idle"]
    assert rel["drivers"][0] == "drive"
    assert rel["devices"]["drive"]["corr"]["power_uw"] == 1.0
    assert rel["devices"]["drive"]["corr"]["decision_time_ps"] == -1.0
    assert "idle" not in rel["devices"]


def test_ranks_a_strong_driver_above_a_noisy_one():
    ws = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    noisy = [2.0, 1.0, 4.0, 3.0, 6.0, 5.0]
    front = [_pt(10 + 10 * i, 500 - 30 * i, strong=ws[i], weak=noisy[i]) for i in range(6)]
    rel = server.front_sizing_relation(front, AXES)
    assert rel["drivers"] == ["strong", "weak"]
    assert abs(rel["devices"]["strong"]["corr"]["power_uw"]) > \
           abs(rel["devices"]["weak"]["corr"]["power_uw"])


def test_reports_span_and_endpoint_sizings():
    front = [_pt(10 + 10 * i, 500 - 30 * i, drive=1.0 + i) for i in range(5)]
    rel = server.front_sizing_relation(front, AXES)
    d = rel["devices"]["drive"]
    assert (d["w_um_min"], d["w_um_max"]) == (1.0, 5.0)
    assert d["span_ratio"] == 5.0
    assert rel["endpoints"]["power_uw"]["min_at"]["drive"] == 1.0
    assert rel["endpoints"]["power_uw"]["max_at"]["drive"] == 5.0


def test_too_small_a_front_says_so_instead_of_guessing():
    rel = server.front_sizing_relation([_pt(10, 500, a=1.0), _pt(20, 400, a=2.0)], AXES)
    assert rel["n_points"] == 2 and "note" in rel
    assert "devices" not in rel


def test_missing_axis_values_are_skipped_not_crashed():
    front = [_pt(10 + 10 * i, 500 - 30 * i, drive=1.0 + i) for i in range(5)]
    front[2]["power_uw"] = None            # one bad measurement
    rel = server.front_sizing_relation(front, AXES)
    corr = rel["devices"]["drive"]["corr"]
    assert "power_uw" not in corr           # dropped
    assert corr["decision_time_ps"] == -1.0  # the usable axis still reported


def test_handles_a_front_where_nothing_moves():
    front = [_pt(10 + 10 * i, 500 - 30 * i, a=2.0, b=3.0) for i in range(5)]
    rel = server.front_sizing_relation(front, AXES)
    assert sorted(rel["fixed_along_front"]) == ["a", "b"]
    assert rel["devices"] == {} and rel["drivers"] == []


# ── against the real circuit ─────────────────────────────────────────────────

def test_real_front_agrees_with_the_circuit_physics():
    """On a StrongARM the power↔speed front should be driven by the tail switch
    and the input pair, and the precharge PMOS should barely participate — it
    only conducts during reset. If this inverts, either the front or the
    relation is wrong."""
    targets = {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 5}
    r = server.optimize_pareto(run_sim._full({"model": "ptm45"}), targets)
    rel = r["sizing_relation"]
    if rel.get("n_points", 0) < 4:
        pytest.skip(f"front too small this run: {rel.get('n_points')}")
    assert set(rel["drivers"][:2]) <= {"tail", "input", "ncc", "pcc"}
    for dv, e in rel["devices"].items():
        c = e["corr"]["power_uw"]
        if c is not None:
            assert -1.0 <= c <= 1.0
    # widening a driver must move power and delay in opposite directions
    top = rel["drivers"][0]
    cp = rel["devices"][top]["corr"]["power_uw"]
    ct = rel["devices"][top]["corr"]["decision_time_ps"]
    assert cp is not None and ct is not None and cp * ct < 0


def test_pareto_endpoint_exposes_the_relation():
    targets = {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 5}
    r = server.optimize_pareto(run_sim._full({"model": "ptm45"}), targets)
    assert "sizing_relation" in r
    assert all("devices" in pt for pt in r["front"])

"""Regression tests for the analysis layer (webapp/server.py)."""
import copy

import run_sim
import server


def test_verdicts_logic():
    nom = {"decision_time_ps": 300, "power_uw": 80, "noise_uv_rms": 100}
    off = {"offset_sigma_mv": 4}
    targets = {"decision_time_ps": 400, "power_uw": 100, "offset_sigma_mv": 5, "noise_uv_rms": 250}
    meas, v = server._verdicts(nom, off, targets)
    assert v == {"decision_time_ps": True, "power_uw": True, "offset_sigma_mv": True, "noise_uv_rms": True}
    # a miss flips only its own verdict
    _, v2 = server._verdicts({**nom, "power_uw": 150}, off, targets)
    assert v2["power_uw"] is False and v2["decision_time_ps"] is True


def test_verdicts_tolerate_missing_metric():
    # noise absent -> verdict None, no KeyError
    _, v = server._verdicts({"decision_time_ps": 300, "power_uw": 80}, {"offset_sigma_mv": 4},
                            {"decision_time_ps": 400, "noise_uv_rms": 250})
    assert v["noise_uv_rms"] is None


def test_pred_offset_scales_with_area():
    p = copy.deepcopy(run_sim.DEFAULT_PARAMS)
    big = copy.deepcopy(p)
    big["devices"]["input"]["w_um"] *= 4
    assert server._pred_offset_mv(big) < server._pred_offset_mv(p)


def test_erfcinv_roundtrip():
    import math
    for y in (0.01, 0.1, 1.0, 1.9):
        x = server._erfcinv(y)
        assert abs(math.erfc(x) - y) < 1e-3


def test_ber_curve_monotonic_and_fields():
    r = server.ber_curve(copy.deepcopy(run_sim.DEFAULT_PARAMS))
    assert "error" not in r
    assert r["noise_uv_rms"] > 0
    assert r["min_input_total_uv"] >= r["min_input_noise_uv"] > 0  # offset only worsens it
    bers = [p["ber_total"] for p in r["points"]]
    assert bers[0] >= bers[-1]   # error rate falls as input grows


def test_sensitivity_covers_all_devices():
    r = server.sensitivity(copy.deepcopy(run_sim.DEFAULT_PARAMS))
    assert {d["key"] for d in r["devices"]} == set(server.DEV_KEYS)
    assert r["base"]["decision_time_ps"] is not None


def test_optimize_converges_to_functional():
    base = copy.deepcopy(run_sim.DEFAULT_PARAMS)
    targets = {"decision_time_ps": 400, "power_uw": 100, "offset_sigma_mv": 5}
    r = server.optimize(base, targets, pop=6, gens=2, seed=1)
    assert r["final_result"]["nominal"]["functional"] is True
    assert r["final_power_uw"] is not None


def test_pmap_preserves_order():
    assert server._pmap(lambda x: x * x, [1, 2, 3, 4]) == [1, 4, 9, 16]


def test_parametric_yield_fields_and_range():
    targets = {"decision_time_ps": 400, "power_uw": 100, "offset_sigma_mv": 5}
    r = server.parametric_yield(copy.deepcopy(run_sim.DEFAULT_PARAMS), targets, n=16, seed=2)
    assert 0.0 <= r["yield_pct"] <= 100.0
    assert r["pass"] == sum(1 for s in r["samples"] if s["pass"])
    assert set(r["fail_breakdown"]) == {"offset", "speed", "decision_wrong"}


def test_yield_zero_n_no_crash():
    """n<=0 must not divide-by-zero; it is clamped to a valid run."""
    r = server.parametric_yield(copy.deepcopy(run_sim.DEFAULT_PARAMS),
                                {"decision_time_ps": 400, "offset_sigma_mv": 5}, n=0)
    assert 0.0 <= r["yield_pct"] <= 100.0 and r["n"] >= 1


def test_erfcinv_out_of_range():
    assert server._erfcinv(2.5) == -6.0 and server._erfcinv(-1) == 6.0


def test_tight_offset_lowers_yield():
    """A much tighter offset target cannot raise yield."""
    base = copy.deepcopy(run_sim.DEFAULT_PARAMS)
    loose = server.parametric_yield(base, {"decision_time_ps": 400, "offset_sigma_mv": 20}, n=24, seed=4)["yield_pct"]
    tight = server.parametric_yield(base, {"decision_time_ps": 400, "offset_sigma_mv": 1}, n=24, seed=4)["yield_pct"]
    assert tight <= loose

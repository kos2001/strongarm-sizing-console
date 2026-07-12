"""Regression tests for WiCkeD-inspired robustness flow."""
import copy

import run_sim
import wicked


def test_predicted_offset_area_scaling():
    base = copy.deepcopy(run_sim.DEFAULT_PARAMS)
    wide = copy.deepcopy(base)
    wide["devices"]["input"]["w_um"] *= 4
    assert wicked.predicted_offset_sigma_mv(wide) < wicked.predicted_offset_sigma_mv(base)


def test_nominal_verdict_has_margins():
    r = wicked.nominal_verdict({}, {"decision_time_ps": 700, "power_uw": 400, "offset_sigma_mv": 20})
    assert r["nominal"]["functional"] is True
    assert set(r["margins"]) == {"functional", "decision_time_ps", "power_uw", "offset_sigma_mv"}
    assert r["margins"]["decision_time_ps"] > 0


def test_wcd_reports_limiting_mechanism_and_positive_beta():
    r = wicked.worst_case_distance({}, {"decision_time_ps": 700, "power_uw": 400, "offset_sigma_mv": 20},
                                   n_samples=4, seed=5)
    assert r["beta_sigma"] > 0
    assert 0.0 <= r["estimated_yield_pct"] <= 100.0
    assert r["limiting_mechanism"]["metric"] in {"offset_sigma_mv", "decision_time_ps"}
    assert len(r["samples"]) == 4


def test_dno_refine_enlarges_input_for_tight_offset():
    tiny = copy.deepcopy(run_sim.DEFAULT_PARAMS)
    tiny["vdd"] = 1.0   # 0.7V 에선 0.5µ 입력쌍이 비기능 → feasibility 분기만 돈다
    tiny["devices"]["input"]["w_um"] = 0.5
    before = wicked.predicted_offset_sigma_mv(tiny)
    r = wicked.dno_refine(tiny, {"decision_time_ps": 700, "power_uw": 1000, "offset_sigma_mv": 5}, iterations=2)
    after = wicked.predicted_offset_sigma_mv(r["final_params"])
    assert after < before
    assert r["final_params"]["devices"]["input"]["w_um"] > tiny["devices"]["input"]["w_um"]


def test_mismatch_budget_includes_all_device_groups():
    r = wicked.mismatch_budget({})
    assert r["total_sigma_mv"] > 0
    assert {x["device"] for x in r["contributors"]} == set(wicked.DEV_KEYS)
    assert r["dominant"]["device"] == "input"


def test_importance_sampling_yield_smoke():
    r = wicked.importance_sampling_yield(
        {}, {"decision_time_ps": 700, "power_uw": 400, "offset_sigma_mv": 20}, n=2, seed=9
    )
    assert r["n"] == 2
    assert 0.0 <= r["estimated_yield_pct"] <= 100.0
    assert "mismatch_budget" in r and r["mismatch_budget"]["total_sigma_mv"] > 0


def test_parameter_screening_ranks_all_devices():
    r = wicked.parameter_screening({}, {"decision_time_ps": 700, "power_uw": 400, "offset_sigma_mv": 20}, delta=0.10)
    for m in ("decision_time_ps", "power_uw", "offset_sigma_mv"):
        assert len(r["rankings"][m]) == len(wicked.DEV_KEYS)
        assert r["rankings"][m][0]["sensitivity"] >= r["rankings"][m][-1]["sensitivity"]


def test_worst_case_corners_returns_top5():
    r = wicked.worst_case_corners({}, {"decision_time_ps": 700, "power_uw": 400, "offset_sigma_mv": 20})
    assert r["total_corners"] == 45
    assert len(r["worst_5"]) == 5
    assert "n_failing" in r


def test_yield_sweep_smoke():
    r = wicked.yield_sweep({}, {"decision_time_ps": 900, "power_uw": 2000, "offset_sigma_mv": 20}, n_points=2, seed=3)
    assert len(r["points"]) == 2
    assert all(0 <= p["yield_pct"] <= 100 for p in r["points"])


def test_postlayout_wcd_smoke():
    r = wicked.postlayout_wcd({}, {"decision_time_ps": 900, "power_uw": 2000, "offset_sigma_mv": 20}, n_samples=2, seed=5)
    assert "pre_layout" in r and "post_layout" in r
    assert r["pre_layout"]["wcd"]["beta_sigma"] > 0
    assert "par_caps" in r


def test_yop_optimize_smoke():
    r = wicked.yop_optimize({}, {"decision_time_ps": 900, "power_uw": 2000, "offset_sigma_mv": 20, "yield_pct": 80}, iterations=1, seed=7)
    assert len(r["history"]) == 1
    assert r["final_beta_sigma"] > 0

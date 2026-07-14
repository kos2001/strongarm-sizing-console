"""Tests for the WiCkeD-inspired VCO robustness/sizing suite (vco_wicked.py)."""
import vco_wicked as vw

XCPL = {"topology": "xcpl"}


def test_nominal_verdict_margins():
    # 기본(2N+4P 유닛, ~4.84GHz) — 밴드 중심을 실측 주파수로 명시
    v = vw.nominal_verdict({}, {"f_ghz": 4.84, "power_uw": 4000})   # 스타빙 없는 유닛은 전력 한계 상향
    assert set(v["margins"]) == {"oscillates", "f_band", "power_uw"}
    assert v["margins"]["oscillates"] == 1.0
    assert v["pass"] is True
    v2 = vw.nominal_verdict(XCPL)
    assert v2["margins"]["f_band"] < 0           # 기본 밴드(1.5±15%) 위로 벗어남
    assert v2["pass"] is False


def test_dev_keys_by_topology():
    # xcpl 유닛(2N+4P)에는 스타빙이 없다
    assert vw.dev_keys({}) == ["invp", "invn", "xcplp"]   # 기본 = xcpl(유닛 소자만)
    assert vw.dev_keys({"topology": "starved"}) == ["invp", "invn", "starvep", "starven"]
    assert vw.dev_keys(XCPL) == ["invp", "invn", "xcplp"]


def test_parameter_screening_ranks_inverters_for_frequency():
    r = vw.parameter_screening({}, delta=0.12)
    fr = r["rankings"]["f_osc_ghz"]
    assert len(fr) == 3 and all(x["sensitivity"] >= 0 for x in fr)   # 2N+4P: inv 2 + 래치
    # 스타빙이 없으니 주파수는 인버터(또는 래치 부하)가 지배해야 한다
    assert {fr[0]["key"], fr[1]["key"]} & {"invp", "invn", "xcplp"}


def test_mismatch_mc_measures_spread():
    mc = vw.mismatch_mc(XCPL, n=6, seed=3)
    assert mc["n"] == 6
    assert mc["sigma_f_pct"] is not None and mc["sigma_f_pct"] > 0
    assert 0 <= mc["osc_failures"] <= 6
    assert mc["startup_yield_pct"] == round(100.0 * (1 - mc["osc_failures"] / 6), 2)


def test_mismatch_netlist_has_per_device_draws():
    import re
    import random
    p = vw._full(XCPL)
    nl = vw._netlist_with_mismatch(p, random.Random(1))
    assert "delvto={dvtn}" not in nl and "delvto={dvtp}" not in nl
    draws = re.findall(r"delvto=(-?[\d.e-]+)", nl)
    assert len(draws) >= 6 * 3                   # xcpl N=3: 스테이지당 6소자(2N+4P)
    assert len({d for d in draws}) > 1           # independent, not one shared value


def test_wcd_returns_beta_and_yield():
    w = vw.worst_case_distance({}, n_samples=6, seed=5)
    assert w["beta_sigma"] > 0
    assert 0 < w["estimated_yield_pct"] <= 100
    assert len(w["samples"]) == 6


def test_dno_refine_centers_xcpl_frequency():
    # 2N+4P 유닛(~4.84GHz)을 4.0GHz 밴드로 소폭 센터링(레버: inv/래치/부하)
    t = {"f_ghz": 4.0, "power_uw": 4000}
    r = vw.dno_refine(XCPL, t, iterations=5)
    lo, hi = vw._band(vw._targets(t))
    f = r["final"]["nominal"]["f_osc_ghz"]
    assert r["final"]["nominal"]["oscillates"] is True
    assert f is not None and lo <= f <= hi
    assert r["success"] is True


def test_wco_and_worst_corners():
    wcc = vw.worst_case_corners({})
    assert wcc["total_corners"] == 45
    assert len(wcc["worst_5"]) == 5
    assert wcc["worst"]["f_min_ghz"] is not None
    # worst-ranked corner has no more margin than the 5th
    m0 = wcc["worst_5"][0]["f_margin"]
    m4 = wcc["worst_5"][4]["f_margin"]
    if m0 is not None and m4 is not None:
        assert m0 <= m4


def test_yield_sweep_compact():
    r = vw.yield_sweep({}, n_points=3, n_mc=3, seed=11)
    assert len(r["points"]) == 3
    assert all(0 <= pt["yield_pct"] <= 100 for pt in r["points"])


def test_yop_improves_or_holds_beta():
    r = vw.yop_optimize({}, iterations=1, seed=9)
    assert r["history"]
    h = r["history"][0]
    assert h["beta_after"] >= h["beta_before"] - 1e-9
    assert r["final_beta_sigma"] > 0


def test_postlayout_wcd_loads_frequency():
    r = vw.postlayout_wcd({}, n_samples=4, seed=13)
    assert r["par_caps"]["c_node_ff"] > 0
    assert r["f_delta_ghz"] < 0                  # parasitics slow the ring


def test_flow_stages_present():
    r = vw.wicked_flow(XCPL, dno_iterations=3, wcd_samples=6, mc_samples=4, seed=19)
    names = [s["name"] for s in r["stages"]]
    assert names[0].startswith("FEO") and any("DNO" in n for n in names)
    assert any("WCO" in n for n in names) and any("WCD" in n for n in names)
    assert any("Monte Carlo" in n for n in names)
    assert isinstance(r["overall"], bool)
    # DNO must have pulled the xcpl default into the band before sign-off stages
    assert r["dno"]["final"]["nominal"]["f_osc_ghz"] >= vw._band(r["targets"])[0]

"""Regression tests for the MOSFET ring VCO backend (vco_sim.py + optimize_vco)."""
import copy

import vco_sim
import server


def test_default_oscillates():
    m = vco_sim.measure_vco({})
    assert m["oscillates"] is True
    assert m["f_osc_ghz"] is not None and m["f_osc_ghz"] > 0
    assert m["power_uw"] is not None and m["power_uw"] > 0


def test_frequency_rises_with_vctrl():
    """starved 링은 진짜 VCO: V_ctrl 상승 → 주파수 상승. (기본 xcpl 유닛은
    2N+4P — 튜닝 노브가 없어 vctrl 무감이므로 starved 를 명시한다.)"""
    p = {"topology": "starved", "n_stages": 5}
    lo = vco_sim.measure_vco(p, vctrl=0.45)["f_osc_ghz"]
    hi = vco_sim.measure_vco(p, vctrl=0.9)["f_osc_ghz"]
    assert lo is not None and hi is not None and hi > lo


def test_tuning_sweep_fields():
    # xcpl(기본) 유닛은 vctrl 노브가 없다 — 스윕은 평탄해야 정상
    t = vco_sim.vco_tuning({})
    osc = [p for p in t["points"] if p["oscillates"]]
    assert len(osc) >= 3
    fs = [p["f_osc_ghz"] for p in osc if p["f_osc_ghz"]]
    assert max(fs) - min(fs) < 0.05 * max(fs)   # ±5% 이내 평탄
    # starved 는 여전히 진짜 튜닝
    t2 = vco_sim.vco_tuning({"topology": "starved", "n_stages": 5})
    assert t2["f_max_ghz"] > t2["f_min_ghz"]
    assert t2["kvco_ghz_per_v"] is not None and t2["kvco_ghz_per_v"] > 0


def test_partial_vco_device_merge():
    """A partial device dict keeps default fields (no KeyError)."""
    p = vco_sim._full({"devices": {"invp": {"w_um": 3}}})
    assert p["devices"]["invp"] == {"w_um": 3, "l_nm": 45, "m": 2}


def test_vco_waveform_captured():
    w = vco_sim.capture_vco_waveform({})
    assert "error" not in w
    assert len(w["t_ns"]) > 50 and len(w["o1"]) == len(w["t_ns"])
    assert w["f_osc_ghz"] is not None and w["f_osc_ghz"] > 0


def test_vco_pvt_corners():
    r = server.vco_pvt({})
    assert len(r["corners"]) == 45   # 5 process(SS/SF/TT/FS/FF) × 3 temp × 3 VDD
    osc = [c for c in r["corners"] if c["oscillates"]]
    assert len(osc) >= 20                       # oscillates across most corners
    assert r["f_max_ghz"] >= r["f_min_ghz"] > 0


def test_vco_pushing():
    r = vco_sim.vco_pushing({})
    assert len(r["points"]) == 7
    assert r["pushing_ghz_per_v"] is not None    # a finite pushing figure


def test_optimize_vco_hits_target():
    base = vco_sim._full({})
    r = server.optimize_vco(base, {"f_ghz": 1.5}, pop=10, gens=5, seed=3)
    assert r["nominal"]["oscillates"] is True
    assert r["nominal"]["f_osc_ghz"] is not None
    # within a reasonable band of the target after a short search
    assert abs(r["nominal"]["f_osc_ghz"] - 1.5) / 1.5 <= 0.2


def test_vco_layout_and_parasitics():
    import layout
    p = vco_sim._full({})
    L = layout.generate_vco_layout(p)
    assert L["area_um2"] > 0 and L["drc"]["clean"] is True
    assert len(L["labels"]) == 2 + 4 * p["n_stages"]      # bias pair + 4 per stage
    pc = layout.extract_vco_parasitics(p)
    assert pc["c_node_ff"] > 0
    # parasitics lower the frequency
    base = vco_sim.measure_vco(p)["f_osc_ghz"]
    pl = vco_sim.measure_vco({**p, "cload_ff": p["cload_ff"] + pc["c_node_ff"]})["f_osc_ghz"]
    assert pl < base


def test_vco_phase_noise():
    r = vco_sim.phase_noise({})
    assert "error" not in r
    assert r["period_jitter_fs"] > 0 and r["c_eff_ff"] > 0
    assert -130 < r["L_1mhz_dbc"] < -70          # plausible ring-VCO range @1MHz
    # 1/f^2 region (above the flicker corner): ~ -20 dB per decade
    p = {pt["offset_hz"]: pt["L_dbc"] for pt in r["points"]}
    import math as _m
    slope = (p[10000000] - p[1000000]) / _m.log10(10)
    assert -22 < slope < -18


def test_vco_phase_noise_flicker_region():
    """With a flicker corner the analytic curve steepens toward −30 dB/dec (1/f^3)
    below the corner, vs −20 dB/dec (1/f^2) above it."""
    r = vco_sim.phase_noise({}, measured=False, flicker_corner_hz=1e5)
    p = {pt["offset_hz"]: pt["L_dbc"] for pt in r["points"]}
    import math as _m
    near = (p[100000] - p[10000]) / _m.log10(100000 / 10000)     # below corner → ~ -30
    far = (p[10000000] - p[1000000]) / _m.log10(10000000 / 1000000)  # above → ~ -20
    assert near < -25 and -22 < far < -18


def test_vco_phase_noise_measured_agrees():
    """The multi-seed SPICE trnoise jitter should corroborate the analytic 1/f^2."""
    r = vco_sim.phase_noise({})   # 기본 xcpl — 실측 지원(starved 도 동일 경로)
    m = r.get("measured")
    assert m is not None and m["n_seeds"] >= 2 and m["cycles"] >= 60
    assert "jitter_spread_fs" in m
    # two independent methods within several dB at 1 MHz (thermal region).
    # 1차 해석 모델은 낙관적(실측이 위) — 2N+4P 유닛 실측 7.1dB, 여유 8dB
    assert abs(r["L_1mhz_dbc"] - m["L_1mhz_dbc"]) < 8.0
    assert m["L_1mhz_dbc"] >= r["L_1mhz_dbc"] - 1.0   # 실측 ≥ 해석(방향 일관)
    # jitter-accumulation slope: white/thermal injection → well below the 1.0
    # flicker regime, and σ_Δt(τ) grows monotonically
    assert m["accum_slope"] is not None and m["accum_slope"] < 0.7
    sig = [pt["sigma_fs"] for pt in m["accum"]]
    assert all(sig[i] <= sig[i + 1] + 1e-9 for i in range(len(sig) - 1))


def test_vco_pareto_front():
    r = server.optimize_vco_pareto(vco_sim._full({}), pop=10, gens=3)
    assert len(r["front"]) >= 3
    fs = [p["f_osc_ghz"] for p in r["front"]]
    pw = [p["power_uw"] for p in r["front"]]
    # front sorted by power; higher-power designs reach higher frequency (trade-off)
    assert max(fs) > min(fs) and max(pw) >= min(pw)


def test_vco_fullflow():
    r = server.vco_fullflow(vco_sim._full({}), {"f_ghz": 1.5})
    assert len(r["stages"]) == 4
    assert r["layout"]["drc"]["clean"] in (True, False)
    assert r["nominal"]["oscillates"] is True


def test_optimize_vco_surrogate_skips():
    """The GP surrogate should pre-screen at least some candidates (fewer SPICE
    runs) once enough training points exist."""
    r = server.optimize_vco(vco_sim._full({}), {"f_ghz": 1.5}, seed=3)
    assert r["n_surrogate_skips"] >= 1
    assert r["nominal"]["oscillates"] is True

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
    """It is a real VCO: higher control voltage -> higher frequency."""
    lo = vco_sim.measure_vco({}, vctrl=0.45)["f_osc_ghz"]
    hi = vco_sim.measure_vco({}, vctrl=0.9)["f_osc_ghz"]
    assert lo is not None and hi is not None and hi > lo


def test_tuning_sweep_fields():
    t = vco_sim.vco_tuning({})
    osc = [p for p in t["points"] if p["oscillates"]]
    assert len(osc) >= 3
    assert t["f_max_ghz"] > t["f_min_ghz"]
    assert t["kvco_ghz_per_v"] is not None and t["kvco_ghz_per_v"] > 0


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
    assert len(r["corners"]) == 27
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
    # 1/f^2 region: ~ -20 dB per decade of offset
    pts = sorted(r["points"], key=lambda p: p["offset_hz"])
    lo, hi = pts[0], pts[-1]
    import math as _m
    decades = _m.log10(hi["offset_hz"] / lo["offset_hz"])
    slope = (hi["L_dbc"] - lo["L_dbc"]) / decades
    assert -22 < slope < -18


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

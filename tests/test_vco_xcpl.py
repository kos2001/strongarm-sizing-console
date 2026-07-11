"""Tests for the cross-coupled pseudo-differential ring VCO topology
(topology="xcpl": N0/P0 starved inverters + P1 cross-coupled PMOS + reset PMOS)."""
import vco_sim

XCPL = {"topology": "xcpl"}


def test_xcpl_netlist_structure():
    p = vco_sim._full(XCPL)
    nl = vco_sim.gen_vco_netlist(p)
    # cross-coupled PMOS pair per stage: drain=own node, gate=complement
    assert "Mx1" in nl and "Mxb1" in nl
    assert f"Mx5" in nl                          # default n_stages=5, both rails coupled
    # reset PMOS clamps o1 high while rstb is low, released by a PULSE source
    assert "Mrst o1 rstb vdd vdd pmos" in nl
    assert "Vrst rstb 0 PULSE(0" in nl
    # reset-driven start-up: no artificial initial-condition kick-start
    assert ".ic" not in nl and " uic" not in nl


def test_starved_netlist_unchanged():
    """Default topology stays the current-starved ring with .ic kick-start."""
    p = vco_sim._full({})
    nl = vco_sim.gen_vco_netlist(p)
    assert "Mrst" not in nl and "Mx1" not in nl
    assert ".ic" in nl


def test_xcpl_oscillates():
    m = vco_sim.measure_vco(XCPL)
    assert m["oscillates"] is True
    assert m["f_osc_ghz"] is not None and m["f_osc_ghz"] > 0
    assert m["power_uw"] is not None and m["power_uw"] > 0


def test_xcpl_frequency_rises_with_vctrl():
    lo = vco_sim.measure_vco(XCPL, vctrl=0.55)["f_osc_ghz"]
    hi = vco_sim.measure_vco(XCPL, vctrl=0.9)["f_osc_ghz"]
    assert lo is not None and hi is not None and hi > lo


def test_xcpl_reset_holds_then_releases():
    """o1 is clamped to VDD during reset (t < trst_ns), then oscillates."""
    p = {**XCPL, "trst_ns": 2.0}
    w = vco_sim.capture_vco_waveform(p, tstop_ns=12.0)
    assert "error" not in w
    vdd = w["vdd"]
    held = [v for t, v in zip(w["t_ns"], w["o1"]) if 0.5 <= t <= 1.8]
    assert held and min(held) > 0.85 * vdd
    after = [v for t, v in zip(w["t_ns"], w["o1"]) if t >= 4.0]
    assert min(after) < 0.3 * vdd and max(after) > 0.7 * vdd


def test_xcpl_waveform_default_window_measures_period():
    """Default capture window still yields a period despite the reset phase."""
    w = vco_sim.capture_vco_waveform(XCPL)
    assert "error" not in w
    assert w["f_osc_ghz"] is not None and w["f_osc_ghz"] > 0


def test_xcpl_outputs_complementary():
    """The two rails (o1 vs ob1, exported as o1/o2) swing in anti-phase."""
    w = vco_sim.capture_vco_waveform({**XCPL}, tstop_ns=12.0)
    assert "error" not in w
    mid = w["vdd"] / 2.0
    pts = [(a, b) for t, a, b in zip(w["t_ns"], w["o1"], w["o2"]) if t >= 4.0]
    assert len(pts) > 20
    corr = sum((a - mid) * (b - mid) for a, b in pts)
    assert corr < 0

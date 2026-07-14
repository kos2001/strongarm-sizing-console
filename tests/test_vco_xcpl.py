"""Tests for the cross-coupled pseudo-differential ring VCO topology
(topology="xcpl": N0/P0 starved inverters + P1 cross-coupled PMOS + reset PMOS)."""
import vco_sim

XCPL = {"topology": "xcpl"}


def test_xcpl_netlist_structure():
    p = vco_sim._full(XCPL)
    nl = vco_sim.gen_vco_netlist(p)
    # cross-coupled PMOS pair per stage: drain=own node, gate=complement
    assert "Mx1" in nl and "Mxb1" in nl
    assert f"Mx3" in nl                          # default n_stages=3, both rails coupled
    # 유닛 소자만: 리셋/스타빙/바이어스 트랜지스터 없음
    assert "Mrst" not in nl and "Mbp" not in nl and "vbp" not in nl
    # 시동은 .ic 킥스타트(상보 초기조건) + uic
    assert ".ic" in nl and " uic" in nl
    # 스테이지당 정확히 6소자(2N+4P)
    import re
    assert len([l for l in nl.splitlines() if re.match(r"^M\w*1 ", l)]) == 6


def test_starved_netlist_unchanged():
    """Explicit starved topology keeps the .ic kick-start ring (default is xcpl)."""
    p = vco_sim._full({"topology": "starved"})
    nl = vco_sim.gen_vco_netlist(p)
    assert "Mrst" not in nl and "Mx1" not in nl
    assert ".ic" in nl


def test_xcpl_oscillates():
    m = vco_sim.measure_vco(XCPL)
    assert m["oscillates"] is True
    assert m["f_osc_ghz"] is not None and m["f_osc_ghz"] > 0
    assert m["power_uw"] is not None and m["power_uw"] > 0


def test_xcpl_frequency_insensitive_to_vctrl():
    """2N+4P 유닛에는 V_ctrl 노브가 없다 — 주파수는 vctrl 무감이어야 한다."""
    lo = vco_sim.measure_vco(XCPL, vctrl=0.55)["f_osc_ghz"]
    hi = vco_sim.measure_vco(XCPL, vctrl=0.9)["f_osc_ghz"]
    assert lo is not None and hi is not None and abs(hi - lo) < 0.05 * hi


def test_xcpl_kickstart_oscillates():
    """유닛 소자만(리셋 없음) — .ic 킥스타트 후 정착 발진해야 한다."""
    w = vco_sim.capture_vco_waveform(XCPL, tstop_ns=12.0)
    assert "error" not in w
    vdd = w["vdd"]
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

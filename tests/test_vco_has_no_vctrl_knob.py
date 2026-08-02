"""Each VCO topology must contain the devices its description claims, and no others.

PR #48 cut the cross-coupled cell down to exactly 2 NMOS + 4 PMOS per stage, removing the
current-starve transistors — so `xcpl` frequency does not depend on V_ctrl at all and Kvco is
0 by construction. That circuit is kept, but it is no longer the default, because the page
promised a voltage-controlled oscillator and a unit cell with no knob cannot be one. The
default `xcplsv` is the same cross-coupled cell WITH the starve pair: measured Kvco
3.45 GHz/V over a 144% range.

Both are tested here, in both directions. The failure this guards against is not a broken
circuit — it is a description drifting away from the circuit it describes, which is what
happened when "current-starved" stayed in a docstring twenty lines above a comment saying
there was no starving.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import vco_sim  # noqa: E402


def test_the_unit_only_deck_contains_no_knob_and_no_starve_devices():
    p = vco_sim._full({"topology": "xcpl"})
    deck = vco_sim.gen_vco_netlist(p, vctrl=0.35)
    assert "vctrl" not in deck            # the node does not exist
    for name in ("Mbn", "Mbp", "Mnref", "Mpref"):
        assert name not in deck, name     # nor any bias/starve device
    # exactly the unit cell, per stage: 2 NMOS + 4 PMOS
    n = int(p["n_stages"])
    assert deck.count(" nmos ") == 2 * n
    assert deck.count(" pmos ") == 4 * n


def test_frequency_is_independent_of_vctrl_on_the_unit_only_topology():
    """The flat curve is that design, so it is asserted rather than tolerated."""
    p = vco_sim._full({"topology": "xcpl"})
    fs = [vco_sim.measure_vco(p, vctrl=v)["f_osc_ghz"] for v in (0.30, 0.60, 0.98)]
    assert all(f is not None for f in fs), fs
    assert len(set(fs)) == 1, fs          # identical, not merely close


def test_tuning_reports_the_absence_of_a_knob():
    """A flat line labelled "tuning curve, slope = Kvco" reads as a broken oscillator.
    The result has to distinguish "no knob" from "knob that does nothing"."""
    t = vco_sim.vco_tuning(vco_sim._full({"topology": "xcpl"}))
    assert t["has_vctrl_knob"] is False
    assert t["tunable_range"] is False
    assert t["kvco_ghz_per_v"] == 0.0
    assert "no V_ctrl knob" in t["knob_note"]
    assert "sizing" in t["knob_note"]     # and names the lever that does work


def test_the_starved_topology_is_the_tunable_one():
    """Kept as the contrast: the tunable variant still exists and still tunes, so the
    absence above is a property of `xcpl`, not of the simulator."""
    t = vco_sim.vco_tuning(vco_sim._full({"topology": "starved"}))
    assert t["has_vctrl_knob"] is True
    assert t["tunable_range"] is True
    assert t["kvco_ghz_per_v"] > 1.0, t
    assert t["knob_note"] is None
    # and it correctly reports the voltages where it stops oscillating
    assert any(pt["oscillates"] is False for pt in t["points"])


def test_the_generator_docstring_no_longer_contradicts_its_own_circuit():
    doc = vco_sim._gen_xcpl_netlist.__doc__
    assert "NOT current-starved" in doc
    assert "no V_ctrl knob" in doc
    # the stale phrasing must not reappear as a bare claim
    assert "Two current-starved inverter rings" not in doc


def test_the_default_topology_is_a_real_vco():
    """The page calls this a voltage-controlled oscillator, so V_ctrl must control it.

    Measured on the default sizing: 0.442 GHz at V_ctrl 0.30 V rising monotonically to
    2.742 GHz at 0.98 V — Kvco 3.45 GHz/V across a 144% range, oscillating at every point."""
    p = vco_sim._full({})
    assert p["topology"] == "xcplsv"
    t = vco_sim.vco_tuning(p)
    assert t["has_vctrl_knob"] is True
    assert t["tunable_range"] is True
    assert t["kvco_ghz_per_v"] > 1.0, t
    assert t["knob_note"] is None
    fs = [pt["f_osc_ghz"] for pt in t["points"]]
    assert all(f is not None for f in fs), fs
    assert fs == sorted(fs), fs                       # monotonic in V_ctrl
    assert fs[-1] > 3 * fs[0], fs                     # and a wide range, not a nudge
    assert all(pt["oscillates"] for pt in t["points"])


def test_the_default_deck_wires_the_starve_pair_into_the_current_path():
    """The knob only works if the inverter sources go THROUGH the starve devices. Sizing
    them while the sources sit on the rails is how the previous default came to be flat."""
    p = vco_sim._full({})
    deck = vco_sim.gen_vco_netlist(p, vctrl=0.5)
    assert "Vc vctrl 0 0.5" in deck
    n = int(p["n_stages"])
    for i in range(1, n + 1):
        assert f"Mbp{i} a{i} vbp vdd vdd" in deck     # starve PMOS feeds node a_i
        assert f"Mbn{i} b{i} vctrl 0 0" in deck       # starve NMOS sinks node b_i
        # ...and the inverters hang off those nodes, not off the rails
        assert f"Mp{i}   o{i} o{n if i == 1 else i - 1} a{i} vdd" in deck
        assert f"Mn{i}   o{i} o{n if i == 1 else i - 1} b{i} 0" in deck
    # the cross-coupled latch pair stays on the rail on purpose
    assert f"Mx1   o1 ob1 vdd vdd" in deck


def test_every_topology_sizes_only_devices_its_deck_instantiates():
    """A sizing variable the netlist never places is silent: the optimizer reports progress
    and changes nothing. So the key list has to follow the deck."""
    import vco_wicked
    for topo, must, must_not in (
        ("xcplsv", ("starvep", "starven", "xcplp"), ()),
        ("xcpl", ("invp", "invn", "xcplp"), ("starvep", "starven")),
        ("starved", ("starvep", "starven"), ("xcplp",)),
    ):
        p = vco_sim._full({"topology": topo})
        keys = vco_wicked.dev_keys(p)
        deck = vco_sim.gen_vco_netlist(p)
        for k in must:
            assert k in keys, (topo, k)
        for k in must_not:
            assert k not in keys, (topo, k)
        # every sized device must correspond to a real width in the deck
        for k in keys:
            w = p["devices"][k]["w_um"]
            assert f"W={w}u" in deck, (topo, k, w)


def test_the_layout_draws_what_the_deck_instantiates():
    """Under-drawing devices under-reports area and under-extracts the parasitics that are
    fed back into the post-layout re-simulation. Counted through the device labels, since
    that is what the drawn geometry is keyed on."""
    import layout
    n = int(vco_sim._full({})["n_stages"])
    got = {}
    for topo in ("xcplsv", "xcpl"):
        r = layout.generate_vco_layout(vco_sim._full({"topology": topo}))
        names = {str(l.get("text") or l.get("label") or l) for l in (r.get("labels") or [])}
        got[topo] = (r, names)
        assert r["drc"]["clean"] is True, (topo, r["drc"])

    sv_names, uo_names = got["xcplsv"][1], got["xcpl"][1]
    # the starve devices and the shared bias mirror appear only in the starved layout
    for i in range(1, n + 1):
        assert any(f"Mbp{i}" in x for x in sv_names), sv_names
        assert any(f"Mbn{i}" in x for x in sv_names), sv_names
        assert not any(f"Mbp{i}" in x for x in uo_names), uo_names
    assert any("Mpref" in x for x in sv_names) and any("Mnref" in x for x in sv_names)
    # and drawing more devices must cost more area, not the same
    assert got["xcplsv"][0]["area_um2"] > got["xcpl"][0]["area_um2"]

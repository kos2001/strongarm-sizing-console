"""The default VCO topology has no V_ctrl knob, and everything that says otherwise is stale.

PR #48 deliberately cut the circuit down to exactly 2 NMOS + 4 PMOS of unit devices per
stage ("V_ctrl 입력 제거(노브 없음)"), which removed the current-starve transistors. The
frequency therefore does not depend on V_ctrl at all — Kvco is 0 by construction, not by
accident. What survived that change was a set of claims describing the circuit it used to
be: the generator's own docstring still said "current-starved" twenty lines above a comment
saying there is no starving, and the UI still told the user the curve's slope was Kvco.

These tests pin the behaviour so the claims cannot drift back apart from the circuit.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import vco_sim  # noqa: E402


def test_the_default_deck_contains_no_knob_and_no_starve_devices():
    p = vco_sim._full({})
    assert p["topology"] == "xcpl"
    deck = vco_sim.gen_vco_netlist(p, vctrl=0.35)
    assert "vctrl" not in deck            # the node does not exist
    for name in ("Mbn", "Mbp", "Mnref", "Mpref"):
        assert name not in deck, name     # nor any bias/starve device
    # exactly the unit cell, per stage: 2 NMOS + 4 PMOS
    n = int(p["n_stages"])
    assert deck.count(" nmos ") == 2 * n
    assert deck.count(" pmos ") == 4 * n


def test_frequency_is_independent_of_vctrl_on_the_default_topology():
    """The flat curve is the design, so it must be asserted rather than tolerated."""
    p = vco_sim._full({})
    fs = [vco_sim.measure_vco(p, vctrl=v)["f_osc_ghz"] for v in (0.30, 0.60, 0.98)]
    assert all(f is not None for f in fs), fs
    assert len(set(fs)) == 1, fs          # identical, not merely close


def test_tuning_reports_the_absence_of_a_knob():
    """A flat line labelled "tuning curve, slope = Kvco" reads as a broken oscillator.
    The result has to distinguish "no knob" from "knob that does nothing"."""
    t = vco_sim.vco_tuning(vco_sim._full({}))
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

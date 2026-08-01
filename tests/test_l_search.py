"""Channel length as a searched variable, plus the effective-L consistency fix.

Three things are pinned:

1. **Per-backend L bounds and nominals.** L used to come from the params verbatim
   on every backend, with the only per-model knowledge living in the web UI's
   model buttons — so an API/MCP caller asking for `{"model": "asap7"}` got
   L = 80/45 nm on a 7 nm card while the UI gave 21 nm. `L_RANGE_NM` is now the
   single source of truth; these tests keep it honest against the cards.

2. **Effective L.** On sky130 the netlist raises L to the device's bin floor, but
   every area calculation read `l_nm` directly — so asking for 45 nm simulated a
   150 nm device while reporting the offset of a 45 nm one, 1.83x worse than what
   was built, and the optimizer paid a penalty against that phantom.

3. **The L search itself** — that it respects the bounds, reports what it chose,
   and can only improve the objective.
"""
import os

import pytest

import run_sim

ALL_DEVICES = ("input", "tail", "ncc", "pcc", "pre", "prei")
needs_sky = pytest.mark.skipif(not os.path.exists(run_sim._sky130_lib_path()),
                               reason="sky130 PDK not installed")
TARGETS = {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 5}


def _sim(p):
    out = run_sim._run(run_sim.gen_netlist(p, vdiff=0.01))
    errs = [l for l in out.splitlines()
            if "rror" in l.lower() and "measure" not in l.lower()]
    return run_sim._parse(out, "tdec"), errs


# ── per-backend bounds and nominals ──────────────────────────────────────────

@pytest.mark.parametrize("model", ["ptm45", "sky130", "asap7", "gaa2nm"])
def test_every_backend_has_a_range_and_the_nominal_sits_inside_it(model):
    p = {"model": model}
    lo, hi = run_sim.l_range_nm(p)
    assert 0 < lo < hi
    for dev in ("input", "tail"):
        nom = run_sim.l_nominal_nm(p, dev)
        assert lo <= nom <= hi, f"{model}/{dev}: nominal {nom} outside [{lo}, {hi}]"


def test_api_gets_the_node_length_not_the_45nm_seed():
    """The regression this fixes: a 7 nm and a 2 nm-class card were both being
    driven at the 45 nm-class seed length by any non-UI caller."""
    assert run_sim._full({"model": "asap7"})["devices"]["tail"]["l_nm"] == 21.0
    assert run_sim._full({"model": "gaa2nm"})["devices"]["tail"]["l_nm"] == 14.0
    assert run_sim._full({"model": "gaa2nm"})["devices"]["input"]["l_nm"] == 20.0
    # ptm45 is the seed's own node, so it is unchanged
    assert run_sim._full({"model": "ptm45"})["devices"]["input"]["l_nm"] == 80.0


def test_an_explicit_length_is_never_overridden():
    p = run_sim._full({"model": "asap7", "devices": {"input": {"l_nm": 45.0}}})
    assert p["devices"]["input"]["l_nm"] == 45.0     # honoured
    assert p["devices"]["tail"]["l_nm"] == 21.0      # omitted -> node nominal


def test_clamp_respects_the_backend_range():
    p = {"model": "ptm45"}
    lo, hi = run_sim.l_range_nm(p)
    assert run_sim.clamp_l_nm(p, "tail", 1.0) == lo
    assert run_sim.clamp_l_nm(p, "tail", 1e6) == hi
    assert run_sim.clamp_l_nm(p, "tail", (lo + hi) / 2) == (lo + hi) / 2


def test_below_range_length_is_what_the_range_protects_against():
    """ptm45's lower bound is not cosmetic — the PTM card has no model below it
    and the deck errors out, which is why the search clamps instead of exploring
    into failure."""
    lo, _ = run_sim.l_range_nm({"model": "ptm45"})
    bad = run_sim._full({"model": "ptm45",
                         "devices": {k: {"l_nm": lo - 15.0} for k in ALL_DEVICES}})
    tdec, errs = _sim(bad)
    assert errs and tdec is None, "expected the sub-range deck to fail"
    ok = run_sim._full({"model": "ptm45", "devices": {k: {"l_nm": lo} for k in ALL_DEVICES}})
    tdec_ok, errs_ok = _sim(ok)
    assert not errs_ok and tdec_ok is not None


@pytest.mark.parametrize("model", ["ptm45", "asap7", "gaa2nm"])
def test_range_endpoints_simulate(model):
    lo, hi = run_sim.l_range_nm({"model": model})
    for L in (lo, hi):
        p = run_sim._full({"model": model, "devices": {k: {"l_nm": L} for k in ALL_DEVICES}})
        _, errs = _sim(p)
        assert not errs, f"{model} at L={L}: {errs[:2]}"


# ── effective L ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model", ["ptm45", "asap7", "gaa2nm"])
def test_effective_l_is_the_requested_l_off_sky130(model):
    p = run_sim._full({"model": model, "devices": {"input": {"l_nm": 60.0}}})
    assert run_sim.effective_l_nm(p, "input") == 60.0


@needs_sky
def test_effective_l_follows_the_pdk_bin_floor():
    p = run_sim._full({"model": "sky130", "vdd": 1.8,
                       "devices": {k: {"l_nm": 45.0} for k in ALL_DEVICES}})
    for dev in ALL_DEVICES:
        assert run_sim.effective_l_nm(p, dev) == 150.0
    # and the lvt pfet's own, higher floor
    q = run_sim._full({"model": "sky130", "vdd": 1.8,
                       "devices": {"pcc": {"l_nm": 45.0, "vt": "lvt"}}})
    assert run_sim.effective_l_nm(q, "pcc") == 350.0


@needs_sky
def test_offset_matches_the_geometry_actually_simulated():
    """The bug: params L = 45 nm, deck builds 150 nm, offset reported for 45 nm.
    Requesting a length below the floor must now give the same offset as
    requesting the floor itself, because it is the same device."""
    import server
    below = run_sim._full({"model": "sky130", "vdd": 1.8,
                           "devices": {k: {"l_nm": 45.0} for k in ALL_DEVICES}})
    at = run_sim._full({"model": "sky130", "vdd": 1.8,
                        "devices": {k: {"l_nm": 150.0} for k in ALL_DEVICES}})
    assert run_sim.gen_netlist(below, vdiff=0.01) == run_sim.gen_netlist(at, vdiff=0.01)
    assert server._pred_offset_mv(below) == pytest.approx(server._pred_offset_mv(at))
    assert server._predict_offset_mv(below) == pytest.approx(server._predict_offset_mv(at))
    rb = run_sim.run_sim(below, do_offset=True)["offset"]
    ra = run_sim.run_sim(at, do_offset=True)["offset"]
    assert rb["pelgrom_sigma_vth_mv"] == pytest.approx(ra["pelgrom_sigma_vth_mv"])
    assert rb["offset_sigma_mv"] == pytest.approx(ra["offset_sigma_mv"])


def test_gate_area_scales_the_way_pelgrom_needs():
    p = run_sim._full({"model": "ptm45", "devices": {"input": {"w_um": 8.0, "l_nm": 80.0, "m": 4}}})
    a = run_sim.gate_area_um2(p, "input")
    assert a == pytest.approx(8.0 * 0.080 * 4)
    q = run_sim._full({"model": "ptm45", "devices": {"input": {"w_um": 8.0, "l_nm": 160.0, "m": 4}}})
    assert run_sim.gate_area_um2(q, "input") == pytest.approx(2 * a)


# ── L is a real knob, and the search uses it ─────────────────────────────────

def test_longer_input_l_improves_matching():
    """Offset sigma goes as 1/sqrt(W·L·M), so this must hold or the whole
    motivation for searching L is wrong."""
    import server
    short = run_sim._full({"model": "ptm45", "devices": {"input": {"l_nm": 80.0}}})
    long_ = run_sim._full({"model": "ptm45", "devices": {"input": {"l_nm": 160.0}}})
    assert server._pred_offset_mv(long_) < server._pred_offset_mv(short)


def test_w_and_l_are_not_interchangeable():
    """Same gate area — so same predicted offset — but the W/L split still moves
    decision time. If these were equivalent, one 'area' variable would do and L
    would not need its own dimension."""
    import server
    wide = run_sim._full({"model": "ptm45", "devices": {"input": {"w_um": 8.0, "l_nm": 80.0}}})
    long_ = run_sim._full({"model": "ptm45", "devices": {"input": {"w_um": 4.0, "l_nm": 160.0}}})
    assert server._pred_offset_mv(wide) == pytest.approx(server._pred_offset_mv(long_))
    tw = run_sim.run_sim(wide, do_offset=False)["nominal"]["decision_time_ps"]
    tl = run_sim.run_sim(long_, do_offset=False)["nominal"]["decision_time_ps"]
    assert tw is not None and tl is not None
    assert abs(tw - tl) / tw > 0.2, (tw, tl)


def test_optimizer_reports_and_bounds_its_l_choice():
    import server
    base = run_sim._full({"model": "ptm45"})
    r = server.optimize(base, TARGETS, optimize_l=True, optimize_vt=False)
    assert r["l_searched"] is True and r["l_note"]
    lo, hi = r["l_range_nm"]
    assert set(r["final_l_nm"]) == set(ALL_DEVICES)
    for dev, L in r["final_l_nm"].items():
        assert lo <= L <= hi, f"{dev} L={L} outside [{lo}, {hi}]"
        assert r["final_params"]["devices"][dev]["l_nm"] == L


def test_l_search_can_be_turned_off():
    import server
    base = run_sim._full({"model": "ptm45"})
    r = server.optimize(base, TARGETS, optimize_l=False, optimize_vt=False)
    assert r["l_searched"] is False and r["l_note"] is None
    for dev in ALL_DEVICES:
        assert r["final_l_nm"][dev] == base["devices"][dev]["l_nm"]


def test_l_search_does_not_worsen_the_objective():
    """It only accepts a strict improvement, so it cannot cost more than the
    W-only optimum it starts from."""
    import server
    base = run_sim._full({"model": "ptm45"})
    off = server.optimize(base, TARGETS, optimize_l=False, optimize_vt=False)
    on = server.optimize(base, TARGETS, optimize_l=True, optimize_vt=False)
    assert on["final_power_uw"] <= off["final_power_uw"] + 1e-6
    assert on["n_sims"] >= off["n_sims"]

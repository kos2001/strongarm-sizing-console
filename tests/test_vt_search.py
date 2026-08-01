"""Vth as a per-device design variable (run_sim vt_* + server's Vt search pass).

Two classes of thing are pinned here. First, that adding the knob changed
nothing for callers who don't use it — `svt` is the default and must reproduce
the old netlist exactly. Second, the backend-specific traps, each of which was
found the hard way:

  * sky130 has no `nfet_01v8_hvt`, so an NMOS asked for hvt must fall back and
    say so rather than silently getting something else;
  * `pfet_01v8_lvt` is only characterized from L = 0.345 µm, and a shorter L
    matches no bin and aborts the whole deck;
  * the sky130 corner-deck prune drops model banks it thinks are unused — when
    Vt became searchable the LVT banks stopped being unused, and the first LVT
    deck died on `unknown subckt`. The whitelist is now derived from the flavor
    tables, and `test_prune_covers_every_flavor` is what keeps them together.
"""
import os

import pytest

import run_sim

ALL_DEVICES = ("input", "tail", "ncc", "pcc", "pre", "prei")
_HAVE_SKY = os.path.exists(run_sim._sky130_lib_path())
needs_sky = pytest.mark.skipif(not _HAVE_SKY, reason="sky130 PDK not installed")


def _all(level):
    return {k: {"vt": level} for k in ALL_DEVICES}


def _measure(p):
    out = run_sim._run(run_sim.gen_netlist(p, vdiff=0.01))
    errs = [l for l in out.splitlines()
            if "rror" in l.lower() and "measure" not in l.lower()]
    return {"tdec": run_sim._parse(out, "tdec"),
            "iavg": run_sim._parse(out, "iavg"),
            "fdiff": run_sim._parse(out, "fdiff"),
            "errors": errs}


# ── the knob is opt-in: default must change nothing ───────────────────────────

def test_default_level_is_standard():
    assert run_sim.vt_of({}) == "svt"
    assert run_sim.vt_of({"w_um": 1.0}) == "svt"
    assert run_sim.vt_of(None) == "svt"


def test_unknown_level_falls_back_to_standard():
    """A typo must not silently become a different threshold."""
    assert run_sim.vt_of({"vt": "ulvt"}) == "svt"
    assert run_sim.vt_of({"vt": ""}) == "svt"


@pytest.mark.parametrize("model", ["ptm45", "asap7", "gaa2nm"])
def test_explicit_svt_equals_omitting_vt(model):
    """The default path and an explicit svt request must generate the same deck,
    so the field's mere presence cannot perturb a result."""
    a = run_sim.gen_netlist(run_sim._full({"model": model}), vdiff=0.01)
    b = run_sim.gen_netlist(run_sim._full({"model": model, "devices": _all("svt")}), vdiff=0.01)
    assert a == b


@needs_sky
def test_explicit_svt_equals_omitting_vt_sky130():
    a = run_sim.gen_netlist(run_sim._full({"model": "sky130", "vdd": 1.8}), vdiff=0.01)
    b = run_sim.gen_netlist(run_sim._full({"model": "sky130", "vdd": 1.8,
                                           "devices": _all("svt")}), vdiff=0.01)
    assert a == b


# ── each backend maps the neutral level onto what it really has ───────────────

@pytest.mark.parametrize("level,flavor", [("lvt", "slvt"), ("svt", "lvt"), ("hvt", "rvt")])
def test_asap7_uses_real_flavors(level, flavor):
    p = run_sim._full({"model": "asap7", "devices": _all(level)})
    nl = run_sim.gen_netlist(p, vdiff=0.01)
    assert f"nmos_{flavor}" in nl and f"pmos_{flavor}" in nl
    # and no other flavor leaked in
    for other in ("slvt", "lvt", "rvt"):
        if other != flavor:
            assert f"nmos_{other} " not in nl


@pytest.mark.parametrize("model", ["ptm45", "gaa2nm"])
def test_generic_card_shifts_delvto_and_composes_with_corner(model):
    """No flavors on a generic BSIM4 card, so the level is a delvto proxy — and it
    must ADD to the corner skew param, not replace it."""
    p = run_sim._full({"model": model, "nskew": 0.05, "devices": {"tail": {"vt": "hvt"}}})
    nl = run_sim.gen_netlist(p, vdiff=0.01)
    tail = [l for l in nl.splitlines() if l.startswith("M7 ")][0]
    assert "dvtn+" in tail, tail          # corner param still there, offset added
    lo = run_sim._full({"model": model, "devices": {"tail": {"vt": "lvt"}}})
    assert "dvtn-" in [l for l in run_sim.gen_netlist(lo, vdiff=0.01).splitlines()
                       if l.startswith("M7 ")][0]


def test_generic_proxy_is_scaled_for_low_vth_nodes():
    """gaa2nm's |Vth0| is 0.20 V — a flat 50 mV implant proxy would be a quarter
    of the threshold, so it scales the same way the corner skew does."""
    assert abs(run_sim.vt_offset_v({"vt": "hvt"}, {"model": "gaa2nm"}, "n")) < \
           abs(run_sim.vt_offset_v({"vt": "hvt"}, {"model": "ptm45"}, "n"))


@needs_sky
@pytest.mark.parametrize("level,nsub,psub", [
    ("lvt", "sky130_fd_pr__nfet_01v8_lvt", "sky130_fd_pr__pfet_01v8_lvt"),
    ("svt", "sky130_fd_pr__nfet_01v8", "sky130_fd_pr__pfet_01v8"),
])
def test_sky130_uses_real_pdk_devices(level, nsub, psub):
    nl = run_sim.gen_netlist(
        run_sim._full({"model": "sky130", "vdd": 1.8, "devices": _all(level)}), vdiff=0.01)
    assert nsub in nl and psub in nl


# ── the traps ────────────────────────────────────────────────────────────────

@needs_sky
def test_sky130_nmos_hvt_falls_back_and_is_reported():
    """There is no nfet_01v8_hvt in sky130. The NMOS must land on svt, the PMOS
    must still get its real hvt device, and the fallback must be reported."""
    p = run_sim._full({"model": "sky130", "vdd": 1.8, "devices": _all("hvt")})
    plan = run_sim.vt_plan(p)
    for k in run_sim.NMOS_DEVICES:
        assert plan["levels"][k] == "svt"
        assert k in plan["fallbacks"]
    for k in run_sim.PMOS_DEVICES:
        assert plan["levels"][k] == "hvt"
        assert k not in plan["fallbacks"]
    nl = run_sim.gen_netlist(p, vdiff=0.01)
    assert "sky130_fd_pr__pfet_01v8_hvt" in nl
    assert "nfet_01v8_hvt" not in nl          # would be an invented device


@needs_sky
def test_sky130_lvt_pmos_min_length_is_enforced_and_reported():
    """pfet_01v8_lvt has no bin below 0.345 µm; a shorter L kills the deck. The
    clamp must be applied AND surfaced — it more than doubles L, which is a real
    speed/area cost the caller has to know about."""
    assert run_sim.sky130_min_l_um("sky130_fd_pr__pfet_01v8_lvt") > \
           run_sim.sky130_min_l_um("sky130_fd_pr__pfet_01v8")
    p = run_sim._full({"model": "sky130", "vdd": 1.8,
                       "devices": {k: {"vt": "lvt", "l_nm": 45.0} for k in run_sim.PMOS_DEVICES}})
    nl = run_sim.gen_netlist(p, vdiff=0.01)
    for line in nl.splitlines():
        if "pfet_01v8_lvt" in line:
            l_val = float(line.split("l=")[1].split()[0])
            assert l_val >= 0.345, line
    clamps = run_sim.vt_plan(p)["l_clamps"]
    for k in run_sim.PMOS_DEVICES:
        assert k in clamps and "350nm" in clamps[k]


@needs_sky
def test_prune_covers_every_flavor():
    """Structural guard against the drift that already bit once: the corner-deck
    prune must keep a bank for every device gen_netlist can emit. Asserting only
    that parsed banks are whitelisted (test_sky130_prune) cannot catch a NEEDED
    bank being dropped — this can."""
    emitted = set(run_sim._VT_SKY130_N.values()) | set(run_sim._VT_SKY130_P.values())
    for sub in emitted:
        base = f"{sub}__tt.corner.spice"
        assert run_sim._sky130_keep_include(base), f"prune would drop {sub}"


@needs_sky
def test_every_sky130_flavor_actually_simulates():
    """The end-to-end version of the above: each level must produce a deck ngspice
    runs to completion. This is the test that fails if a model bank goes missing."""
    for level in run_sim.VT_LEVELS:
        p = run_sim._full({"model": "sky130", "vdd": 1.8, "devices": _all(level)})
        r = _measure(p)
        assert not r["errors"], f"{level}: {r['errors'][:2]}"
        assert r["tdec"] is not None and r["fdiff"] is not None, f"{level}: {r}"


@pytest.mark.parametrize("model", ["ptm45", "asap7", "gaa2nm"])
def test_every_flavor_simulates_on_generic_backends(model):
    for level in run_sim.VT_LEVELS:
        p = run_sim._full({"model": model, "devices": _all(level)})
        r = _measure(p)
        assert not r["errors"], f"{model}/{level}: {r['errors'][:2]}"
        assert r["tdec"] is not None, f"{model}/{level}: {r}"


# ── Vt is a real knob, and the search uses it ────────────────────────────────

def test_vt_level_actually_moves_the_metrics():
    """If Vt did not move speed/power there would be no reason to search it. On
    asap7 the flavors are real cards, so the ordering must be monotonic:
    lower Vth -> faster and hungrier."""
    got = {}
    for level in run_sim.VT_LEVELS:
        p = run_sim._full({"model": "asap7", "devices": _all(level)})
        r = _measure(p)
        assert r["tdec"] is not None
        got[level] = (r["tdec"], abs(r["iavg"]))
    assert got["lvt"][0] < got["svt"][0] < got["hvt"][0], got   # decision time
    assert got["lvt"][1] > got["svt"][1] > got["hvt"][1], got   # supply current


def test_optimizer_reports_its_vt_choice():
    import server
    base = run_sim._full({"model": "ptm45"})
    targets = {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 5}
    r = server.optimize(base, targets, optimize_vt=True)
    assert r["vt_searched"] is True
    assert r["vt_note"]
    levels = r["final_vt"]["levels"]
    assert set(levels) == set(ALL_DEVICES)
    assert all(v in run_sim.VT_LEVELS for v in levels.values())
    # the levels reported must be the ones actually in the returned sizing
    for k, v in levels.items():
        assert run_sim.vt_of(r["final_params"]["devices"][k]) == v


def test_vt_search_can_be_turned_off():
    import server
    base = run_sim._full({"model": "ptm45"})
    targets = {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 5}
    r = server.optimize(base, targets, optimize_vt=False)
    assert r["vt_searched"] is False
    assert r["vt_note"] is None
    # untouched: everything stays at the level it came in with
    assert all(v == "svt" for v in r["final_vt"]["levels"].values())


def test_vt_search_does_not_worsen_the_objective():
    """The pass only accepts a strict improvement, so its result can never cost
    more than the W-only optimum it started from."""
    import server
    base = run_sim._full({"model": "ptm45"})
    targets = {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 5}
    off = server.optimize(base, targets, optimize_vt=False)
    on = server.optimize(base, targets, optimize_vt=True)
    assert on["final_power_uw"] <= off["final_power_uw"] + 1e-6
    assert on["n_sims"] >= off["n_sims"]        # it does cost extra simulations

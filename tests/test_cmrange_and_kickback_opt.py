"""Input common-mode range, and giving the optimizer sight of kickback.

**Common-mode range.** `vcm_frac` was a parameter nothing swept, hiding a hard
lower bound (below it the latch never resolves) and the speed the chosen operating
point gives up. Deliberately *not* a CMRR number: this deck is symmetric, so with
zero mismatch the systematic offset is zero at every Vcm and CMRR is infinite —
probing it just returns the offset bisection's own quantisation step. The tests
below pin that reasoning so nobody later "fixes" the missing CMRR figure by
reporting an artifact.

**Kickback in the cost function.** Kickback measures far above the offset σ the
optimizer minimises and moves against the same lever, so a target had to become
part of the constraint set rather than a report read afterwards.
"""
import pytest

import run_sim
import server

TARGETS = {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 5}


# ── common-mode range ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def cm():
    return run_sim.cm_range_sweep({"model": "ptm45"})


def test_finds_a_hard_lower_bound(cm):
    """Below the usable range the latch does not resolve at all. That is a hard
    bound — reporting it as a slow corner would be wrong."""
    assert cm["n_nonfunctional"] > 0, "expected some Vcm where it cannot resolve"
    lo, hi = cm["usable_vcm_frac"]
    assert lo > min(p["vcm_frac"] for p in cm["points"])
    for pt in cm["points"]:
        if pt["vcm_frac"] < lo:
            assert not pt["functional"]


def test_all_usable_points_are_contiguous_and_functional(cm):
    lo, hi = cm["usable_vcm_frac"]
    inside = [p for p in cm["points"] if lo <= p["vcm_frac"] <= hi]
    assert all(p["functional"] for p in inside), [p for p in inside if not p["functional"]]


def test_reports_the_speed_cost_of_the_operating_point(cm):
    """The finding worth surfacing: the seed operating point is far from the
    fastest usable one."""
    cur, fast = cm["at_current_vcm"], cm["fastest"]
    assert cur is not None, "the caller's own operating point must be in the sweep"
    assert cur["functional"] and fast["functional"]
    assert cm["speed_spread"] > 2, cm["speed_spread"]
    assert cur["decision_time_ps"] >= fast["decision_time_ps"]


def test_caller_operating_point_is_always_included():
    """Even when it is off the default grid — otherwise the report cannot say what
    the current choice costs."""
    r = run_sim.cm_range_sweep({"model": "ptm45", "vcm_frac": 0.637},
                               vcm_fracs=[0.6, 0.7, 0.8])
    assert r["at_current_vcm"] is not None
    assert any(p["vcm_frac"] == 0.637 for p in r["points"])


def test_offset_is_flat_in_common_mode():
    """Input-pair Vth mismatch refers to the input gate-to-gate, so σ_offset does
    not depend on Vcm. Measured, not assumed — and it is the reason the operating
    point is a speed knob only."""
    r = run_sim.cm_range_sweep({"model": "ptm45"}, vcm_fracs=[0.55, 0.70, 0.90],
                               with_offset=True, n_mc=6)
    sigs = [p["offset_sigma_mv"] for p in r["points"] if p.get("offset_sigma_mv")]
    assert len(sigs) >= 3
    assert max(sigs) == pytest.approx(min(sigs), rel=1e-6), sigs
    # while speed is emphatically not flat
    ts = [p["decision_time_ps"] for p in r["points"] if p["functional"]]
    assert max(ts) / min(ts) > 2


def test_offset_sweep_is_off_by_default(cm):
    """It costs ~90 sims per point and the answer is flat, so it must be opt-in."""
    assert all("offset_sigma_mv" not in p for p in cm["points"])


def test_no_cmrr_number_is_reported_and_the_reason_is_stated(cm):
    """Guards against someone later "adding the missing CMRR" by publishing the
    bisection quantisation step as a measurement."""
    assert "cmrr" not in {k.lower() for k in cm} - {"cmrr_note"}
    assert "symmetric" in cm["cmrr_note"]


def test_symmetric_deck_has_no_systematic_offset_to_measure():
    """The claim behind that refusal: with zero mismatch the probe returns the same
    value at every Vcm, and that value is the bisection step — an artifact."""
    vals = []
    for vf in (0.55, 0.70, 0.90):
        p = run_sim._full({"model": "ptm45", "vcm_frac": vf})
        vals.append(run_sim._offset_sample(p, 0.0, 0.0))
    assert all(v is not None for v in vals)
    assert max(vals) == pytest.approx(min(vals), rel=1e-9), vals
    step = 0.06 / (2 ** 7)          # bisection range / iterations
    assert abs(abs(vals[0]) - step / 2) < step, (vals[0], step)


# ── kickback as a constraint ────────────────────────────────────────────────

def test_no_kickback_target_means_no_extra_cost():
    r = server.optimize(run_sim._full({"model": "ptm45"}), TARGETS)
    assert r["kickback_target_mv"] is None
    assert r["final_kickback"] is None


def test_a_kickback_target_is_measured_and_reported():
    T = {**TARGETS, "kickback_diff_mv": 10.0}
    r = server.optimize(run_sim._full({"model": "ptm45"}), T)
    assert r["kickback_target_mv"] == 10.0
    kb = r["final_kickback"]
    assert kb and kb.get("kickback_diff_mv") is not None


def test_tightening_kickback_shrinks_the_input_pair():
    """The trade this exists to expose: kickback wants a small input pair, offset
    wants a big one. Loose vs tight target must move W in that direction."""
    loose = server.optimize(run_sim._full({"model": "ptm45"}),
                            {**TARGETS, "kickback_diff_mv": 30.0})
    tight = server.optimize(run_sim._full({"model": "ptm45"}),
                            {**TARGETS, "kickback_diff_mv": 5.0})
    w_loose = loose["final_params"]["devices"]["input"]["w_um"]
    w_tight = tight["final_params"]["devices"]["input"]["w_um"]
    assert w_tight < w_loose, (w_tight, w_loose)
    kb_l = loose["final_kickback"]["kickback_diff_mv"]
    kb_t = tight["final_kickback"]["kickback_diff_mv"]
    assert kb_t < kb_l, (kb_t, kb_l)


def test_conflicting_specs_report_failure_rather_than_picking_one():
    """A tight offset and a tight kickback cannot both be met with W alone, since
    they pull opposite ways. The optimizer must say so."""
    T = {"decision_time_ps": 400, "power_uw": 150,
         "offset_sigma_mv": 1.0, "kickback_diff_mv": 3.0}
    r = server.optimize(run_sim._full({"model": "ptm45"}), T)
    assert r["success"] is False
    kb = r["final_kickback"]["kickback_diff_mv"]
    off = (r["final_result"].get("offset") or {}).get("offset_sigma_mv")
    assert kb is not None and off is not None
    # at least one of the two conflicting specs must be missed
    assert kb > T["kickback_diff_mv"] or off > T["offset_sigma_mv"]


def test_the_assumed_driver_is_configurable_and_matters():
    """rs_ohm/cs_ff belong to the system around the comparator. A bigger held cap
    must lower the kickback the optimizer sees for the same target."""
    T = {**TARGETS, "kickback_diff_mv": 8.0}
    small = server.optimize(run_sim._full({"model": "ptm45", "cs_ff": 50.0}), T)
    big = server.optimize(run_sim._full({"model": "ptm45", "cs_ff": 400.0}), T)
    assert small["final_kickback"]["cs_ff"] == 50.0
    assert big["final_kickback"]["cs_ff"] == 400.0

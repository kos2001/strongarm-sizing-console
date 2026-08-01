"""Decision-to-decision memory, clock edge rate, and the reset check they corrected.

**Hysteresis.** A StrongARM's nodes must return to the rails during precharge or the
previous decision biases the next — a data-dependent offset, which in a SAR shows up
correlated with the code and therefore does not calibrate out. The default deck
evaluates once, so this needed a two-decision transient.

**Clock edge rate.** Was hardcoded at 12 ps. Nearly irrelevant to decision time (it
is timed from the clock's own VDD/2 crossing) but it costs max f_clk headroom — and
only when the design is already near its limit.

**The reset check.** Measuring hysteresis exposed a real defect in `max_fclk_sweep`:
its reset criterion tested absolute output levels only. At a 0.45 ns period the
outputs come back to 0.681 and 0.712 V, so ">0.9·VDD" passes on both while 31 mV of
*differential* memory survives. That overstated max f_clk by 1.6x at a fast
operating point.
"""
import pytest

import run_sim

FAST = {"model": "ptm45", "vcm_frac": 0.95}


# ── the clock edge rate is now a parameter ──────────────────────────────────

def test_default_edge_rate_leaves_the_deck_electrically_unchanged():
    nl = run_sim.gen_netlist(run_sim._full({"model": "ptm45"}), vdiff=0.01)
    assert "200p 12p 12p" in nl          # formatted as before, not "12.0p"


def test_edge_rate_is_settable():
    nl = run_sim.gen_netlist(run_sim._full({"model": "ptm45", "clk_trf_ps": 40}), vdiff=0.01)
    assert "200p 40p 40p" in nl


def test_no_clkb_in_this_topology():
    """Single clock: the tail switch and precharge PMOS share it, so there is no
    clk/clkb skew to sweep. Guards against someone adding a skew knob that has
    nothing to skew against."""
    nl = run_sim.gen_netlist(run_sim._full({"model": "ptm45"}), vdiff=0.01)
    assert "clkb" not in nl
    r = run_sim.clock_edge_sweep({"model": "ptm45"}, trf_ps=[12, 50])
    assert "single-clock" in r["no_clkb_note"]


def test_decision_time_is_nearly_flat_in_edge_rate():
    """Measured, because it is the reason this is reported as max f_clk instead."""
    r = run_sim.clock_edge_sweep({"model": "ptm45"}, trf_ps=[5, 50, 200])
    assert r["decision_time_spread"] is not None
    assert r["decision_time_spread"] < 1.1, r["decision_time_spread"]


def test_edge_rate_costs_max_fclk_only_near_the_limit():
    """At the default operating point the design has headroom and edge rate changes
    nothing; pushed fast, a slow edge costs real clock rate. Both halves matter —
    the first stops the feature from over-claiming."""
    relaxed = run_sim.clock_edge_sweep({"model": "ptm45"}, trf_ps=[12, 200])
    assert relaxed["fclk_spread"] == pytest.approx(1.0), relaxed["points"]
    fast = run_sim.clock_edge_sweep(FAST, trf_ps=[12, 200])
    assert fast["fclk_spread"] > 1.2, fast["points"]


def test_current_edge_rate_is_always_in_the_sweep():
    r = run_sim.clock_edge_sweep({"model": "ptm45", "clk_trf_ps": 37}, trf_ps=[12, 50])
    assert r["at_current_trf"] is not None
    assert any(p["clk_trf_ps"] == 37 for p in r["points"])


# ── hysteresis ──────────────────────────────────────────────────────────────

def test_two_decision_deck_produces_two_decisions():
    """The priming decision and the measured one must both be present and, with a
    large priming input, must go opposite ways for opposite priming."""
    p = run_sim._full({"model": "ptm45", "clk_period_ns": 1.0, "clk_high_ns": 0.5,
                       "tstop_ns": 2.25, "iavg_to_ns": 1.2})
    a = run_sim._run(run_sim.gen_netlist({**p, "prime_v": 0.2}, vdiff=0.001))
    b = run_sim._run(run_sim.gen_netlist({**p, "prime_v": -0.2}, vdiff=0.001))
    f1a, f1b = run_sim._parse(a, "fdiff1"), run_sim._parse(b, "fdiff1")
    assert f1a is not None and f1b is not None
    assert (f1a > 0) != (f1b > 0), (f1a, f1b)          # priming worked
    assert run_sim._parse(a, "fdiff2") is not None      # and a second decision exists


def test_prime_v_unset_leaves_a_single_decision_deck():
    nl = run_sim.gen_netlist(run_sim._full({"model": "ptm45"}), vdiff=0.01)
    assert "PWL" not in nl and "fdiff2" not in nl


def test_hysteresis_vanishes_at_a_relaxed_clock():
    """Ample precharge time means no memory. If this ever reports a large value the
    measurement is broken, not the circuit."""
    r = run_sim.measure_hysteresis({"model": "ptm45"}, clk_period_ns=4.0)
    assert "error" not in r, r
    assert r["hysteresis_mv"] <= r["resolution_mv"], r
    assert r["resolved"] is False           # i.e. below what bisection can resolve
    assert abs(r["reset_residue_mv"]) < 1.0


def test_hysteresis_grows_as_the_clock_is_squeezed():
    slow = run_sim.measure_hysteresis({"model": "ptm45"}, clk_period_ns=1.0)
    fast = run_sim.measure_hysteresis({"model": "ptm45"}, clk_period_ns=0.45)
    assert "error" not in slow and "error" not in fast
    assert fast["hysteresis_mv"] > slow["hysteresis_mv"] * 4, (slow, fast)
    assert fast["resolved"] is True


def test_hysteresis_reports_its_own_resolution():
    """A bisection cannot resolve better than one step, so a value at that step must
    not be presented as a measurement."""
    r = run_sim.measure_hysteresis({"model": "ptm45"}, clk_period_ns=4.0)
    assert r["resolution_mv"] > 0
    assert "resolved" in r


def test_hysteresis_tracks_the_differential_residue():
    """The mechanism: memory is the leftover output imbalance, so the two must move
    together."""
    rows = [run_sim.measure_hysteresis({"model": "ptm45"}, clk_period_ns=T)
            for T in (1.0, 0.6, 0.45)]
    assert all("error" not in r for r in rows)
    hyst = [r["hysteresis_mv"] for r in rows]
    resid = [abs(r["reset_residue_mv"]) for r in rows]
    assert hyst == sorted(hyst), hyst
    assert resid == sorted(resid), resid


def test_absolute_reset_can_pass_while_memory_survives():
    """The defect that this work uncovered, pinned: the absolute level check is
    necessary but not sufficient."""
    r = run_sim.measure_hysteresis({"model": "ptm45"}, clk_period_ns=0.45)
    assert r["reset_absolute_ok"] is True
    assert abs(r["reset_residue_mv"]) > 10.0
    assert r["hysteresis_mv"] > 5.0


# ── the corrected reset criterion in max_fclk ───────────────────────────────

def test_max_fclk_reports_both_reset_criteria():
    r = run_sim.max_fclk_sweep(run_sim._full({"model": "ptm45"}))
    for pt in r["points"]:
        for k in ("reset_absolute_ok", "reset_balanced", "reset_residue_mv"):
            assert k in pt


def test_balanced_reset_is_what_rejects_the_fast_periods():
    """At a fast operating point some periods resolve and pass the absolute check but
    leave tens of mV of differential residue. Those must now be rejected."""
    r = run_sim.max_fclk_sweep(run_sim._full(FAST))
    caught = [pt for pt in r["points"]
              if pt["functional"] and pt["reset_absolute_ok"] and not pt["reset_balanced"]]
    assert caught, "expected periods that the absolute check alone would have passed"
    for pt in caught:
        assert pt["ok"] is False
        assert abs(pt["reset_residue_mv"]) > 1.0


def test_the_stricter_check_lowers_the_reported_max_fclk():
    """Directly: with the residue budget effectively disabled the sweep reports a
    higher max f_clk than with it enforced — quantifying what was overstated."""
    p = run_sim._full(FAST)
    strict = run_sim.max_fclk_sweep(p)
    loose = run_sim.max_fclk_sweep(p, reset_residue_limit=10.0)   # never binds
    assert strict["max_fclk_ghz"] < loose["max_fclk_ghz"], (strict["max_fclk_ghz"],
                                                            loose["max_fclk_ghz"])


def test_relaxed_operating_point_is_unaffected_by_the_stricter_check():
    """Where resolution binds first, the residue check changes nothing — so the fix
    does not penalise designs that were already honest."""
    p = run_sim._full({"model": "ptm45"})
    assert (run_sim.max_fclk_sweep(p)["max_fclk_ghz"]
            == run_sim.max_fclk_sweep(p, reset_residue_limit=10.0)["max_fclk_ghz"])

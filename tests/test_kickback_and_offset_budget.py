"""Two things real comparator sign-off demands that the tool could not report.

**Kickback.** When the outputs slew, the input pair pushes charge back through Cgd
into whatever drives the gates. In a SAR ADC that is the DAC's held sample, so the
disturbance corrupts the value being compared. The deck drove the inputs from ideal
voltage sources, which hold the gate rigid — so kickback was not merely unmeasured,
it was *unmeasurable by construction*.

**Offset beyond the input pair.** `measure_offset` models the input pair only;
run_sim called latch and tail mismatch "a documented extension point". The
cross-coupled pair fires exactly when regeneration decides, so its Vth mismatch
steers the outcome.

Both features must be opt-in: with `rs_ohm` unset and `mismatch_v` unset the
generated deck has to be unchanged, which the first tests here pin.
"""
import math

import pytest

import run_sim

ALL = ("input", "tail", "ncc", "pcc", "pre", "prei")


# ── opt-in: the default deck must be untouched ───────────────────────────────

@pytest.mark.parametrize("model", ["ptm45", "asap7", "gaa2nm"])
def test_default_deck_has_no_drive_network_or_mismatch_sources(model):
    nl = run_sim.gen_netlist(run_sim._full({"model": model}), vdiff=0.01)
    assert "Rsp" not in nl and "Csp" not in nl        # ideal sources, as before
    assert "kbd_max" not in nl                        # no kickback measurement
    assert "Vmm" not in nl                            # no extra mismatch sources
    assert "Vinp inpx 0" in nl                        # the original input drive


def test_explicit_zero_rs_is_the_same_as_omitting_it():
    a = run_sim.gen_netlist(run_sim._full({"model": "ptm45"}), vdiff=0.01)
    b = run_sim.gen_netlist(run_sim._full({"model": "ptm45", "rs_ohm": 0}), vdiff=0.01)
    assert a == b


def test_empty_mismatch_dict_changes_nothing():
    a = run_sim.gen_netlist(run_sim._full({"model": "ptm45"}), vdiff=0.01)
    b = run_sim.gen_netlist(run_sim._full({"model": "ptm45", "mismatch_v": {"ncc": 0.0}}),
                            vdiff=0.01)
    assert a == b


# ── kickback ────────────────────────────────────────────────────────────────

def test_drive_network_appears_only_with_a_real_driver():
    nl = run_sim.gen_netlist(run_sim._full({"model": "ptm45", "rs_ohm": 2000, "cs_ff": 50}),
                             vdiff=0.005)
    assert "Rsp srcp inpx 2000" in nl and "Csp inpx 0 50.0f" in nl
    assert "kbd_max" in nl and "kbd_end" in nl
    assert "Vinp srcp 0" in nl          # source moved behind the resistance


@pytest.fixture(scope="module")
def kb():
    return run_sim.measure_kickback({"model": "ptm45"})


def test_kickback_is_measured_and_nonzero(kb):
    assert kb.get("kickback_se_mv", 0) > 0, kb
    assert kb.get("kickback_diff_mv", 0) > 0, kb
    assert kb["functional"] is True


def test_kickback_grows_with_input_pair_width():
    """Cgd scales with W, so a wider input pair injects more charge. If this
    inverted, the measurement would not be kickback."""
    small = run_sim.measure_kickback({"model": "ptm45", "devices": {"input": {"w_um": 2.0}}})
    large = run_sim.measure_kickback({"model": "ptm45", "devices": {"input": {"w_um": 24.0}}})
    assert large["kickback_se_mv"] > small["kickback_se_mv"] * 1.5, (small, large)


def test_kickback_shrinks_with_a_bigger_held_capacitor():
    """ΔV = Q/C — more held charge absorbs the same injection with less swing."""
    tiny = run_sim.measure_kickback({"model": "ptm45"}, cs_ff=10.0)
    big = run_sim.measure_kickback({"model": "ptm45"}, cs_ff=250.0)
    assert big["kickback_se_mv"] < tiny["kickback_se_mv"], (tiny, big)


def test_kickback_shrinks_with_a_stiffer_driver():
    stiff = run_sim.measure_kickback({"model": "ptm45"}, rs_ohm=200.0)
    weak = run_sim.measure_kickback({"model": "ptm45"}, rs_ohm=20000.0)
    assert stiff["kickback_se_mv"] < weak["kickback_se_mv"], (stiff, weak)


def test_kickback_reports_the_driver_it_assumed(kb):
    """rs_ohm/cs_ff are properties of the system around the comparator, so the
    number is meaningless without them."""
    assert kb["rs_ohm"] > 0 and kb["cs_ff"] > 0
    assert "rs_ohm" in kb["note"]


def test_kickback_is_comparable_to_the_error_budget(kb):
    """The reason this matters: kickback is not a rounding error next to the
    offset σ the optimizer minimises. Asserted loosely — the point is the order of
    magnitude, not a specific ratio."""
    off = run_sim.run_sim(run_sim._full({"model": "ptm45"}), do_offset=True)
    sig = off["offset"]["offset_sigma_mv"]
    assert kb["kickback_diff_mv"] > sig, (kb["kickback_diff_mv"], sig)


# ── offset budget ───────────────────────────────────────────────────────────

def test_pelgrom_sigma_scales_with_area():
    p = run_sim._full({"model": "ptm45"})
    small = run_sim._full({"model": "ptm45", "devices": {"input": {"w_um": 2.0}}})
    assert run_sim.pelgrom_sigma_v(small, "input") > run_sim.pelgrom_sigma_v(p, "input")
    # quadrupling area halves sigma
    big = run_sim._full({"model": "ptm45", "devices": {"input": {"w_um": 32.0}}})
    assert run_sim.pelgrom_sigma_v(big, "input") == pytest.approx(
        run_sim.pelgrom_sigma_v(p, "input") / 2, rel=1e-6)


def test_tail_is_excluded_and_says_why():
    """One device has no differential partner, so its mismatch is common-mode."""
    assert "tail" not in run_sim.OFFSET_PAIRS
    b = run_sim.offset_budget({"model": "ptm45"}, n_mc=4)
    assert "tail" in b["excluded"]


@pytest.fixture(scope="module")
def budget():
    return run_sim.offset_budget({"model": "ptm45"}, n_mc=8)


def test_every_matched_pair_is_reported(budget):
    for g in run_sim.OFFSET_PAIRS:
        assert g in budget["per_device"]
        assert budget["per_device"][g]["pelgrom_sigma_vth_mv"] > 0


def test_total_is_the_rss_of_the_contributors(budget):
    contrib = [v["offset_sigma_mv"] for v in budget["per_device"].values()
               if v.get("offset_sigma_mv") is not None]
    assert budget["total_sigma_mv"] == pytest.approx(
        math.sqrt(sum(c * c for c in contrib)), rel=1e-3)


def test_the_budget_is_worse_than_the_input_pair_alone(budget):
    """The correction this makes: extra contributors can only add, so the
    input-pair-only figure understates the total."""
    assert budget["total_sigma_mv"] >= budget["input_only_sigma_mv"]


def test_input_pair_dominates_but_is_not_everything(budget):
    """Validates the original comment that the input pair is the dominant term,
    while showing it is not the whole story."""
    assert budget["dominant"][0] == "input"
    others = [budget["per_device"][g]["offset_sigma_mv"] for g in budget["dominant"][1:]
              if budget["per_device"][g].get("offset_sigma_mv") is not None]
    assert others and max(others) > 0


def test_latch_has_larger_vth_sigma_but_smaller_input_referred_offset(budget):
    """Physics check: the latch devices are smaller so their Vth σ is bigger, but
    referred to the input it is divided by the pair's gain — so their offset
    contribution comes out smaller. If this inverted, the referral is wrong."""
    inp, ncc = budget["per_device"]["input"], budget["per_device"]["ncc"]
    assert ncc["pelgrom_sigma_vth_mv"] > inp["pelgrom_sigma_vth_mv"]
    if ncc.get("offset_sigma_mv") is not None:
        assert ncc["offset_sigma_mv"] < inp["offset_sigma_mv"]


def test_mismatch_injection_reaches_the_devices_with_the_right_sense():
    """With zero input the latch is metastable, so its own mismatch decides — and
    the sign of the injection must control which way. That is the unambiguous
    statement; fighting a nonzero input instead only works if you pick the opposing
    sign, and `fdiff` saturates at a rail so its magnitude says little."""
    p = run_sim._full({"model": "ptm45"})

    def fdiff(mm, vdiff=0.0):
        deck = run_sim.gen_netlist({**p, "mismatch_v": {"ncc": mm}} if mm else p, vdiff=vdiff)
        return run_sim._parse(run_sim._run(deck), "fdiff")

    plus, minus = fdiff(+0.05), fdiff(-0.05)
    assert plus is not None and minus is not None
    assert (plus > 0) != (minus > 0), (plus, minus)      # sign controls the outcome
    assert abs(plus) > 0.5 * p["vdd"] and abs(minus) > 0.5 * p["vdd"]  # fully resolved

    # and it can overcome a small input when it opposes it
    vin = 0.0005
    same_way = fdiff(+0.05, vin)
    against = fdiff(-0.2, vin)
    assert (same_way > 0) != (against > 0), (same_way, against)

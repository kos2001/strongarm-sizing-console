"""BER is exponential in σ, so its σ cannot come from one Monte-Carlo draw.

`_ber_at` is `erfc(v / (σ√2))`. Both BER paths used to take σ from a single MC draw of the
input pair alone — 0.842 mV at the default seed on the seed design (0.84-1.67 across four
seeds, 62% spread) where the deterministic full budget is 1.873 mV. The consequence was not
a rounding error: the page asked for 2.607 mV of input amplitude to reach BER 1e-3 when the
real requirement is 5.792 mV, and the true BER at its own recommendation was 8.2e-2 rather
than 1e-3 — off by 82x, in the direction that signs off a design that does not work.
"""
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import run_sim  # noqa: E402
import server  # noqa: E402


@pytest.fixture(scope="module")
def p():
    return run_sim._full({"model": "ptm45"})


def test_ber_sigma_is_the_full_budget_not_the_input_pair(p):
    budget = run_sim.offset_budget(p)
    for got in (server.ber_curve(p)["offset_sigma_mv"],
                server.resolution_view(p)["sigma"]["offset_mv"]):
        assert got == pytest.approx(budget["total_sigma_mv"], rel=1e-9)
        # ...and specifically NOT the input-pair-only figure, which is what it used to be
        assert got != pytest.approx(budget["input_only_sigma_mv"], rel=1e-6)


def test_both_ber_paths_agree_and_repeat(p):
    """Two views of one quantity. They were both wrong the same way, so fixing one and
    not the other would have left them disagreeing on the same screen."""
    b1, b2 = server.ber_curve(p), server.ber_curve(p)
    assert b1 == b2                                    # deterministic
    r = server.resolution_view(p)
    assert r["sigma"]["offset_mv"] == pytest.approx(b1["offset_sigma_mv"], rel=1e-9)
    assert r["sigma"]["total_uv"] == pytest.approx(b1["sigma_total_uv"], rel=1e-6)


def test_the_recommended_amplitude_actually_meets_the_target(p):
    """The headline number is a requirement a user designs to, so it has to be true at the
    σ the design really has. At the old recommendation the real BER was 8.2e-2."""
    b = server.ber_curve(p, ber_target=1e-3)
    sig_tot = b["sigma_total_uv"] * 1e-6
    v = b["min_input_total_uv"] * 1e-6
    assert server._ber_at(v, sig_tot) == pytest.approx(1e-3, rel=0.02)
    # and it must exceed the noise-only requirement by a wide margin: offset dominates here
    assert b["min_input_total_uv"] > 10 * b["min_input_noise_uv"]


def test_offset_dominates_the_ber_requirement_and_the_text_says_so(p):
    r = server.resolution_view(p)
    assert "offset" in r["reading"].lower()
    sig = server._input_sigmas(p)
    assert sig["sigma_offset_v"] > 10 * sig["sigma_noise_v"]
    assert "deterministic" in sig["offset_source"]
    # the input-only figure is still reported, so the difference stays visible
    assert sig["offset_input_only_mv"] < sig["offset_sigma_mv"]


def test_the_flat_input_pair_claim_is_now_provable(p):
    """`cm_range_sweep`'s central claim is that the input pair's contribution is flat in
    Vcm while the total is not. It used to support that with one MC draw at n_mc=8 (~24%
    standard error) — a noisy estimate cannot demonstrate flatness.

    Deterministically the input-only figure is identical to four decimals across a
    0.55-0.86 sweep while the total rises ~62%, and the dominant device flips from the
    input pair to the latch at high Vcm — which the page did not surface at all before."""
    r = run_sim.cm_range_sweep(p, vcm_fracs=[0.55, 0.62, 0.70, 0.78, 0.86],
                               with_offset=True)
    io = [x["offset_sigma_mv"] for x in r["points"]]
    tt = [x["offset_total_sigma_mv"] for x in r["points"]]
    assert len(set(io)) == 1, io                       # exactly flat, not approximately
    assert (max(tt) - min(tt)) / min(tt) > 0.3, tt     # the total is emphatically not
    dom = [x["offset_dominant"] for x in r["points"]]
    assert dom[0] == "input" and dom[-1] == "ncc", dom  # and the binding device changes

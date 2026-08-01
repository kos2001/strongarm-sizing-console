"""The merged input-resolution view (server.resolution_view).

metastability, Monte-Carlo offset and BER were three sidebar pages answering one
question about one variable: how small a differential input this comparator can be
given. They were not merely adjacent — `ber_curve` already ran the offset MC that
the offset page displays, and both sweeps used the same log amplitude axis.

These tests pin that the merge is faithful (same numbers as the separate views, on
one axis) and that the thing the merge exists to reveal is actually there: a small
input can be "resolved" and still be a coin flip.
"""
import math

import pytest

import run_sim
import server


@pytest.fixture(scope="module")
def res():
    return server.resolution_view(run_sim._full({"model": "ptm45"}))


def test_one_shared_amplitude_axis(res):
    """Every point carries both consequences of its amplitude — that is the whole
    point. Previously the two curves lived on different axes (13 vs 21 points)."""
    assert res["points"], res
    for pt in res["points"]:
        assert pt["vin_v"] > 0
        assert "ber_noise" in pt and "ber_total" in pt
        assert "decision_time_ps" in pt and "resolved" in pt
    amps = [p["vin_v"] for p in res["points"]]
    assert amps == sorted(amps)


def test_matches_the_separate_views_it_replaces(res):
    """Same measurement, so the headline numbers must agree with what the
    metastability and BER pages report on their own."""
    p = run_sim._full({"model": "ptm45"})
    meta = run_sim.metastability_sweep(p)
    ber = server.ber_curve(p)
    assert res["tau_ps"] == meta["tau_ps"]
    assert res["min_resolved_v"] == meta["min_resolved_v"]
    assert res["sigma"]["noise_uv"] == ber["noise_uv_rms"]
    assert res["sigma"]["offset_mv"] == ber["offset_sigma_mv"]
    assert res["markers_uv"]["min_input_total"] == ber["min_input_total_uv"]
    assert res["markers_uv"]["min_input_noise"] == ber["min_input_noise_uv"]


def test_ber_is_evaluated_at_the_sweeps_own_amplitudes(res):
    """BER is closed-form, so it costs nothing to evaluate on the metastability
    axis — which is what makes a single axis possible without extra simulation."""
    p = run_sim._full({"model": "ptm45"})
    meta_amps = [pt["vin_v"] for pt in run_sim.metastability_sweep(p)["points"]]
    assert [pt["vin_v"] for pt in res["points"]] == meta_amps


def test_ber_curves_are_monotone_and_ordered(res):
    """Bigger input, fewer errors; and including offset can only make it worse."""
    prev_n = prev_t = 1.0
    for pt in res["points"]:
        assert pt["ber_noise"] <= prev_n + 1e-12
        assert pt["ber_total"] <= prev_t + 1e-12
        assert pt["ber_total"] >= pt["ber_noise"] - 1e-12
        prev_n, prev_t = pt["ber_noise"], pt["ber_total"]


def test_resolved_does_not_mean_correct(res):
    """The reason to merge these views. At the small end the latch reaches a rail
    — metastability alone reports success — while the decision is near a coin
    flip. Only the shared axis shows both at once."""
    small = res["points"][0]
    assert small["resolved"] is True
    assert small["decision_time_ps"] is not None
    assert small["ber_total"] > 0.3, small


def test_offset_dominates_the_resolution_floor(res):
    """Chip-to-chip offset, not per-decision noise, sets how small an input is
    usable — the actionable conclusion, and visible only with both sigmas on one
    axis."""
    m = res["markers_uv"]
    assert m["min_input_total"] > m["min_input_noise"]
    assert m["sigma_total"] >= m["sigma_noise"]
    # sigmas add in quadrature
    assert m["sigma_total"] == pytest.approx(
        math.hypot(m["sigma_noise"], m["sigma_offset"]), rel=1e-3)


def test_markers_sit_where_the_curves_cross_the_target(res):
    """min_input_total must be the amplitude where the offset-broadened BER meets
    the target — otherwise the marker and the curve disagree on screen.

    Tolerance is 1e-3 relative because the markers are rounded for display (µV to
    2 dp, σ to 1 dp), so re-deriving BER from the published numbers cannot land
    exactly on the target. That is rounding, not misplacement; a marker on the
    wrong amplitude would be off by orders of magnitude here, not parts per
    thousand."""
    target = res["ber_target"]
    v = res["markers_uv"]["min_input_total"] * 1e-6
    sig = res["markers_uv"]["sigma_total"] * 1e-6
    assert server._ber_at(v, sig) == pytest.approx(target, rel=1e-3)
    v_n = res["markers_uv"]["min_input_noise"] * 1e-6
    sig_n = res["markers_uv"]["sigma_noise"] * 1e-6
    assert server._ber_at(v_n, sig_n) == pytest.approx(target, rel=1e-3)


def test_ber_target_is_configurable():
    p = run_sim._full({"model": "ptm45"})
    loose = server.resolution_view(p, ber_target=1e-2)
    tight = server.resolution_view(p, ber_target=1e-6)
    assert loose["markers_uv"]["min_input_total"] < tight["markers_uv"]["min_input_total"]


def test_reports_instead_of_crashing_when_noise_is_unavailable():
    """A sizing that never resolves has no input-referred noise, so there is no
    resolution story to tell — say that rather than returning half a view."""
    dead = run_sim._full({"model": "ptm45",
                          "devices": {"tail": {"w_um": 0.1, "m": 1},
                                      "input": {"w_um": 0.1, "m": 1}}})
    r = server.resolution_view(dead)
    assert "error" in r or r["points"]


def test_ber_at_edges():
    assert server._ber_at(0.0, 1e-3) == pytest.approx(0.5)
    assert server._ber_at(1.0, 0.0) == 0.0          # no sigma -> never wrong
    assert server._ber_at(1.0, 1e-6) == pytest.approx(0.0, abs=1e-12)

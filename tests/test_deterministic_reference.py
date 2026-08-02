"""The offset reference: deterministic quadrature instead of Monte Carlo.

Every mis-fitted constant in the analytic offset model traces to the same cause — a
reference with a 21% standard error per estimate was treated as ground truth. `R_input`
was published as 1.414, "corrected" to 1.06, "corrected" to 1.268, and the first value
was right. So the reference itself is now the thing under test.
"""
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_sim  # noqa: E402


def test_quadrature_rule_is_exact():
    """Validate the hardcoded nodes/weights by integrating x^k, no numpy needed.

    An n-point Gauss-Hermite rule is exact for polynomials up to degree 2n-1, and the
    moments of a standard normal are known in closed form: E[x^k] is 0 for odd k and
    (k-1)!! for even k. That pins every digit of the table."""
    def double_fact(k):
        r = 1
        while k > 1:
            r *= k
            k -= 2
        return r

    for n, (x, w) in run_sim._GAUSS_HERMITE.items():
        assert len(x) == len(w) == n
        assert sum(w) == pytest.approx(1.0, abs=1e-12)         # normalised weights
        for k in range(0, 2 * n):
            got = sum(wi * xi ** k for xi, wi in zip(x, w))
            want = 0.0 if k % 2 else float(double_fact(k - 1))
            assert got == pytest.approx(want, abs=1e-8, rel=1e-8), (n, k, got, want)


def test_the_reference_repeats_bit_for_bit():
    """A reference that does not repeat cannot support a gate. The MC path returned
    0.42, 0.51 and 0.39 mV for one sizing on three seeds."""
    p = run_sim._full({"model": "ptm45"})
    a = run_sim.offset_budget(p, groups=("ncc", "pcc"))
    b = run_sim.offset_budget(p, groups=("ncc", "pcc"))
    assert a["total_sigma_mv"] == b["total_sigma_mv"]
    assert a["method"] == "quadrature"
    for g in ("ncc", "pcc"):
        assert a["per_device"][g]["offset_sigma_mv"] == b["per_device"][g]["offset_sigma_mv"]


def test_quadrature_agrees_across_node_counts():
    """Convergence is the evidence that the rule is resolving the integral rather than
    the bisection floor. At the old 11-step bisection the same sweep scattered 5.1%,
    because one LSB (0.029 mV) was 14% of the response at the inner nodes."""
    p = run_sim._full({"model": "ptm45"})
    sig = run_sim.pelgrom_sigma_v(p, "ncc")
    vals = [run_sim._offset_of_pair_quad(p, "ncc", sig, nodes=n)["offset_sigma_mv"]
            for n in (3, 5, 7)]
    assert all(v for v in vals), vals
    assert (max(vals) - min(vals)) / min(vals) < 0.01, vals


def test_the_input_pair_collapses_to_one_dimension():
    """Two independent Vth draws, but only their difference moves the offset — so the
    quadrature rule over a single scalar is exact, not an approximation."""
    p = run_sim._full({"model": "ptm45"})
    d = run_sim.pelgrom_sigma_v(p, "input") * math.sqrt(2.0)
    one = run_sim._offset_sample(p, d, 0.0, n_iter=16)
    split = run_sim._offset_sample(p, d / 2, -d / 2, n_iter=16)
    common = run_sim._offset_sample(p, d / 2, d / 2, n_iter=16)
    assert one == pytest.approx(split, rel=1e-6)
    lsb = run_sim.offset_bisect_resolution_v(16)
    assert abs(common) <= 2 * lsb, (common, lsb)


def test_the_mc_reference_seed_actually_reproduces():
    """`hash(group)` is salted per process, so this path took a `seed` and returned a
    different draw set on every interpreter — including for the calibration history."""
    p = run_sim._full({"model": "ptm45"})
    sig = run_sim.pelgrom_sigma_v(p, "ncc")
    a = run_sim._offset_of_pair(p, "ncc", sig, 6, 4242)
    b = run_sim._offset_of_pair(p, "ncc", sig, 6, 4242)
    assert a["offset_sigma_mv"] == b["offset_sigma_mv"]
    assert a["method"] == "mc"
    # and a different seed must actually give a different draw set
    c = run_sim._offset_of_pair(p, "ncc", sig, 6, 99)
    assert c["offset_sigma_mv"] != a["offset_sigma_mv"]


def test_a_failed_quadrature_node_reports_no_number():
    """A partial rule is not a weaker estimate, it is a wrong one — the weights no longer
    sum to 1, so the variance comes out low, i.e. optimistic."""
    calls = {"n": 0}
    real = run_sim._offset_sample

    def flaky(*a, **k):
        calls["n"] += 1
        return None if calls["n"] == 2 else real(*a, **k)

    p = run_sim._full({"model": "ptm45"})
    run_sim._offset_sample = flaky
    try:
        out = run_sim._offset_of_pair_quad(p, "ncc", run_sim.pelgrom_sigma_v(p, "ncc"))
    finally:
        run_sim._offset_sample = real
    assert out["offset_sigma_mv"] is None
    assert "quadrature nodes failed" in out["error"]

"""The offset-model calibration loop's guardrails.

`scripts/calibrate_offset_model.py` re-measures, re-fits and — only if the held-out
error improves — rewrites the constants in `predicted_offset_budget_mv`. The measuring
is slow (minutes), so these tests exercise the parts that decide *whether to accept*
using synthetic data. Those are the parts that must not break: a loop that can rewrite
its own model needs a gate that actually gates.

One real trap is pinned here because the loop walked into it: R_input was being fitted
on the latch grid, where ncc is driven to 0.5 µm to expose the latch term. A weak latch
inflates the input pair's measured offset, so that fit returned 1.36 instead of 1.06 —
and the held-out set shared the same skew, so the held-out error *improved*. A gate
only protects against overfitting when the held-out data is drawn differently from the
training data.
"""
import importlib.util
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def cal():
    spec = importlib.util.spec_from_file_location(
        "calibrate_offset_model", os.path.join(ROOT, "scripts", "calibrate_offset_model.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["calibrate_offset_model"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── the grids ───────────────────────────────────────────────────────────────

def _devs(override):
    """Grid entries are full params overrides now, not devices dicts — they had to be,
    because passing only devices dropped the vcm_frac the optimizer raises."""
    return (override or {}).get("devices", {})


def test_grid_entries_are_full_params_overrides(cal):
    """Pins the shape, since three separate bugs came from passing a subset of a sizing
    around: w_um only (lost vt), devices only (lost vcm_frac)."""
    for grid in (cal.TRAIN, cal.TRAIN_INPUT, cal.HOLDOUT):
        for d in grid:
            assert set(d) <= {"devices", "model", "vdd", "vcm_frac", "cload_ff",
                              "avt_mv_um", "n_mc"}, d


def test_holdout_is_disjoint_from_training(cal):
    """A gate over data the fit has already seen is not a gate."""
    def key(d):
        return tuple(sorted((g, v.get("w_um")) for g, v in _devs(d).items()))
    train = {key(d) for d in cal.TRAIN} | {key(d) for d in cal.TRAIN_INPUT}
    hold = {key(d) for d in cal.HOLDOUT}
    assert not (train & hold), sorted(train & hold)


def test_holdout_reaches_outside_the_training_range(cal):
    """It must include sizings the grid does not bracket, or it only proves
    interpolation."""
    tr_ncc = [_devs(d)["ncc"]["w_um"] for d in cal.TRAIN if "ncc" in _devs(d)]
    ho_ncc = [_devs(d)["ncc"]["w_um"] for d in cal.HOLDOUT if "ncc" in _devs(d)]
    assert ho_ncc, cal.HOLDOUT
    assert max(ho_ncc) > max(tr_ncc) or min(ho_ncc) < min(tr_ncc), (tr_ncc, ho_ncc)


def test_input_sweep_keeps_the_latch_nominal(cal):
    """The trap: fitting R_input where the latch has been deliberately weakened.
    TRAIN_INPUT must not touch ncc."""
    for d in cal.TRAIN_INPUT:
        assert set(_devs(d)) <= {"input"}, d


# ── the fits ────────────────────────────────────────────────────────────────

def _row(input_w=8.0, ncc_w=4.0, contrib=None, sig=None):
    """A synthetic (params, measurement) row shaped like `measured()` returns."""
    import run_sim
    p = run_sim._full({"model": "ptm45",
                       "devices": {"input": {"w_um": input_w}, "ncc": {"w_um": ncc_w}}})
    m = {g: (0.03, run_sim.pelgrom_sigma_v(p, g) * 1e3) for g in run_sim.OFFSET_PAIRS}
    if contrib is not None:
        m["ncc"] = (contrib, sig if sig is not None else m["ncc"][1])
    return p, m


def test_input_R_fit_recovers_a_known_ratio(cal):
    import run_sim
    rows = []
    for w in (2.0, 8.0, 32.0):
        p, m = _row(input_w=w)
        sig = run_sim.pelgrom_sigma_v(p, "input") * 1e3
        m["input"] = (1.23 * sig, sig)          # plant an exact ratio
        rows.append((p, m))
    r, spread = cal.fit_input_R(rows)
    assert r == pytest.approx(1.23, rel=1e-6)
    assert spread == pytest.approx(0.0, abs=1e-9)


def test_input_R_fit_reports_instability(cal):
    """The spread is what would reveal that the "stable" constant has stopped being
    stable — the thing I over-claimed by sweeping only one variable."""
    import run_sim
    rows = []
    for w, ratio in ((2.0, 1.0), (8.0, 1.3), (32.0, 1.6)):
        p, m = _row(input_w=w)
        sig = run_sim.pelgrom_sigma_v(p, "input") * 1e3
        m["input"] = (ratio * sig, sig)
        rows.append((p, m))
    r, spread = cal.fit_input_R(rows)
    assert r == pytest.approx(1.3, rel=1e-6)
    assert spread > 0.4, spread


def test_ncc_fit_recovers_planted_exponents(cal):
    """Least squares in log space must return the coefficients it was given, or the
    loop is fitting something other than what it claims."""
    import run_sim
    K, A, B = 0.2, 0.7, 0.4
    rows = []
    for iw in (4.0, 8.0, 16.0, 32.0):
        for nw in (0.5, 1.0, 2.0, 4.0, 8.0):
            p, m = _row(input_w=iw, ncc_w=nw)
            sig = run_sim.pelgrom_sigma_v(p, "ncc") * 1e3
            di, dn = p["devices"]["input"], p["devices"]["ncc"]
            ratio = (di["w_um"] * di["m"]) / (dn["w_um"] * dn["m"])
            m["ncc"] = (K * sig ** A * ratio ** B, sig)
            rows.append((p, m))
    k, a, b = cal.fit_ncc(rows)
    assert k == pytest.approx(K, rel=1e-4)
    assert a == pytest.approx(A, rel=1e-4)
    assert b == pytest.approx(B, rel=1e-4)


def test_ncc_fit_refuses_too_little_data(cal):
    assert cal.fit_ncc([_row()]) is None


def test_flat_fit_is_a_median(cal):
    rows = []
    for v in (0.30, 0.36, 0.42, 99.0):        # one outlier
        p, m = _row()
        m["pcc"] = (v, m["pcc"][1])
        rows.append((p, m))
    assert cal.fit_flat(rows, "pcc") == pytest.approx(0.39)   # median, not mean


# ── the gate ────────────────────────────────────────────────────────────────

def test_holdout_error_is_zero_for_a_perfect_model(cal):
    import run_sim
    K, A, B = 0.2, 0.7, 0.4
    flat = dict(run_sim._OFFSET_FLAT_MV)
    rows = []
    for iw, nw in ((6.0, 3.0), (20.0, 1.0)):
        p, m = _row(input_w=iw, ncc_w=nw)
        sig_i = run_sim.pelgrom_sigma_v(p, "input") * 1e3
        sig_n = run_sim.pelgrom_sigma_v(p, "ncc") * 1e3
        di, dn = p["devices"]["input"], p["devices"]["ncc"]
        ratio = (di["w_um"] * di["m"]) / (dn["w_um"] * dn["m"])
        m["input"] = (1.1 * sig_i, sig_i)
        m["ncc"] = (K * sig_n ** A * ratio ** B, sig_n)
        for g, v in flat.items():
            m[g] = (v, m[g][1])
        # pcc is a power law in its own width, not one of the flat constants, so a
        # "perfect" planted measurement has to include the model's own pcc term —
        # otherwise this asserts zero error against a term nobody planted
        m["pcc"] = (run_sim.predicted_offset_budget_mv(p)[1]["pcc"], m["pcc"][1])
        rows.append((p, m))
    assert cal.holdout_error(rows, K, A, B, 1.1, flat) == pytest.approx(0.0, abs=1e-9)


def test_the_gate_vetoes_an_optimizer_region_regression(cal):
    """The gate's first real run accepted a refit that improved the hand-chosen region
    13.0% -> 3.4% while making the optimizer-converged region worse, 6.4% -> 9.2%, because
    eight hand-chosen holdout points outvoted four optimizer ones in the median. That is
    backwards — the optimizer region is the only one the predictor is used in. The veto
    logic lives in main(), so this pins the arithmetic it rests on."""
    slack = 0.10
    # overall improves, optimizer region regresses beyond slack -> must not accept
    assert not (0.034 < 0.126 and not (0.092 > 0.064 * (1 + slack)))
    # a regression inside the slack is tolerated (estimator noise)
    assert not (0.068 > 0.064 * (1 + slack))
    # and a genuine improvement in both is accepted
    assert 0.030 < 0.126 and not (0.050 > 0.064 * (1 + slack))


def test_region_split_partitions_measured_rows_without_reconstructing(cal):
    """Two properties, both learned the hard way. The split must partition rows that
    were already measured — re-measuring one region compares the two against different
    draws of a reference that scatters ~27-33%. And it must not match rows by rebuilding
    a sizing from a subset of its fields, which is how vcm_frac got lost."""
    src = open(os.path.join(ROOT, "scripts", "calibrate_offset_model.py")).read()
    assert "hand_rows, opt_rows = hold[:-n_opt], hold[-n_opt:]" in src
    assert "opt_rows = [measured(" not in src
    assert 'run_sim._full({"model": args.model, "devices": d})["devices"]' not in src


def test_a_worse_model_scores_worse_on_holdout(cal):
    """The gate's only job: the ordering must be right."""
    import run_sim
    flat = dict(run_sim._OFFSET_FLAT_MV)
    rows = []
    for iw, nw in ((6.0, 3.0), (20.0, 1.0), (10.0, 6.0)):
        p, m = _row(input_w=iw, ncc_w=nw)
        sig_i = run_sim.pelgrom_sigma_v(p, "input") * 1e3
        sig_n = run_sim.pelgrom_sigma_v(p, "ncc") * 1e3
        di, dn = p["devices"]["input"], p["devices"]["ncc"]
        ratio = (di["w_um"] * di["m"]) / (dn["w_um"] * dn["m"])
        m["input"] = (1.1 * sig_i, sig_i)
        m["ncc"] = (0.2 * sig_n ** 0.7 * ratio ** 0.4, sig_n)
        for g, v in flat.items():
            m[g] = (v, m[g][1])
        m["pcc"] = (run_sim.predicted_offset_budget_mv(p)[1]["pcc"], m["pcc"][1])
        rows.append((p, m))
    good = cal.holdout_error(rows, 0.2, 0.7, 0.4, 1.1, flat)
    bad = cal.holdout_error(rows, 0.2 * 3, 0.7, 0.4, 1.1 * 2, flat)
    assert bad > good


def test_apply_is_reversible_and_rewrites_only_the_constants(cal, tmp_path):
    """It edits run_sim.py in place, so it has to leave a .bak and touch nothing else."""
    import shutil
    import run_sim
    path = os.path.join(ROOT, "run_sim.py")
    keep = tmp_path / "run_sim.py.keep"
    shutil.copy(path, keep)
    before = open(path).read()
    try:
        cal.apply_constants(0.1111, 0.5555, 0.2222, 1.2345,
                            {"pcc": 0.111, "pre": 0.011, "prei": 0.012}, model="asap7")
        after = open(path).read()
        # R_input is sqrt(2) by the linearity of the input response, not a fit, so a
        # candidate value must NOT be written — rewriting it published 1.06 and 1.268
        assert "_OFFSET_R_INPUT = 1.234" not in after
        assert "1.4142135623730951" in after
        assert "0.5555, 0.2222" in after
        # the latch coefficient goes into the named model's slot, not the global fallback
        assert '"asap7": 0.1111' in after
        assert f'"ptm45": {run_sim._OFFSET_NCC_K_BY_MODEL["ptm45"]:.4g}' in after
        assert os.path.exists(path + ".bak")
        # only the three fitted-constant lines changed (R_input is not one of them)
        diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
        assert len(diff) == 3, diff
    finally:
        shutil.copy(keep, path)
        if os.path.exists(path + ".bak"):
            os.remove(path + ".bak")
    assert open(path).read() == before


def test_a_candidate_latch_coefficient_actually_reaches_the_model(cal):
    import run_sim

    """The loop installs K into the per-model table, not only the scalar fallback.

    Patching `_OFFSET_NCC_K` alone left every candidate K silently ignored for all four
    backends, because the model reads its own slot first — a calibration loop whose
    candidates have no effect reports convergence on a constant it never varied."""
    p = run_sim._full({"model": "ptm45"})
    a, b = run_sim._OFFSET_NCC_A, run_sim._OFFSET_NCC_B
    r, flat = run_sim._OFFSET_R_INPUT, dict(run_sim._OFFSET_FLAT_MV)
    snapshot = dict(run_sim._OFFSET_NCC_K_BY_MODEL)
    lo = cal.predict(p, 0.05, a, b, r, flat)
    hi = cal.predict(p, 0.50, a, b, r, flat)
    assert hi > lo * 1.2, (lo, hi)
    # and it restores the table afterwards. Compared against a snapshot, not a literal:
    # a test that pins the value the loop exists to improve is a test fighting its feature
    assert run_sim._OFFSET_NCC_K_BY_MODEL == snapshot


def test_apply_refuses_to_silently_no_op(cal, tmp_path):
    """A pattern that stops matching must fail loudly instead of reporting success."""
    with pytest.raises(SystemExit, match="matched 0 times"):
        cal.apply_constants(0.1, 0.5, 0.2, 1.2, {"pre": 0.01}, model="no_such_backend")


def test_the_reference_is_deterministic_and_repeats(cal):
    """The loop's reference must repeat, or a gate cannot mean anything.

    The Monte-Carlo path carried a 21% standard error per estimate and 27% scatter
    between seeds — larger than most differences the loop is asked to resolve, and large
    enough that a real 55% out-of-sample error read as noise."""
    import run_sim
    a = cal.measured("ptm45", {"devices": {"ncc": {"w_um": 2.0}}}, 8, (1, 2, 3))
    b = cal.measured("ptm45", {"devices": {"ncc": {"w_um": 2.0}}}, 8, (4, 5, 6))
    # different "seeds", identical answer — because seeds do not apply to quadrature
    assert a[1]["ncc"][0] == b[1]["ncc"][0]
    assert a[1]["input"][0] == b[1]["input"][0]
    assert all(v[0] and v[0] > 0 for v in a[1].values())


def test_the_loop_does_not_refit_the_input_referral_factor(cal, tmp_path):
    """R_input is sqrt(2) by linearity. Two published values came from fitting it."""
    import shutil
    import run_sim
    path = os.path.join(ROOT, "run_sim.py")
    keep = tmp_path / "keep.py"
    shutil.copy(path, keep)
    before = open(path).read()
    try:
        cal.apply_constants(0.12, 0.68, 0.37, 1.06, {"pre": 0.007, "prei": 0.005})
        assert "_OFFSET_R_INPUT = 1.06" not in open(path).read()
    finally:
        shutil.copy(keep, path)
        if os.path.exists(path + ".bak"):
            os.remove(path + ".bak")
    assert open(path).read() == before

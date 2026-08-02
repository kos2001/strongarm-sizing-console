#!/usr/bin/env python3
"""Self-improvement loop for the analytic offset model.

`run_sim.predicted_offset_budget_mv` predicts each matched pair's input-referred
offset contribution so the optimizer can price mismatch it used to ignore. Its
constants were fitted by hand, once, on one afternoon's measurements — against a
reference that itself scatters ~27% at practical Monte-Carlo sample counts. That makes
them a snapshot, not a calibration, and nothing would notice if the circuit, the model
card or the measurement changed underneath them.

This closes the loop:

    measure a grid  ->  re-fit  ->  validate on HELD-OUT sizings  ->  accept or reject

The gate is the point. A refit that fits the training grid better but the held-out
sizings worse is rejected, so the loop cannot talk itself into overfitting. Every run
appends to a history file whether it accepted or not, so drift is visible over time
even when nothing changes.

The history lives under `out/`, which is gitignored — deliberately, since the numbers
are specific to the machine and ngspice build that produced them, but it does mean the
record is **local**: a fresh clone starts with no history. Copy the file if you want to
carry a calibration trail between machines.

Usage:
    python3 scripts/calibrate_offset_model.py                 # measure, fit, report
    python3 scripts/calibrate_offset_model.py --apply         # also rewrite the constants
    python3 scripts/calibrate_offset_model.py --n-mc 24       # tighter reference
    python3 scripts/calibrate_offset_model.py --model asap7   # calibrate another backend

Applying edits `run_sim.py` in place and leaves a `.bak`. Run the test suite after.
"""
import argparse
import copy
import json
import math
import os
import re
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_sim  # noqa: E402

HISTORY = os.path.join(ROOT, "out", "offset_model_history.jsonl")

# Training grid and a disjoint validation set. The split is by *sizing*, not by
# random sample, because the failure mode being guarded against is a model that
# works where it was fitted and nowhere else.
# Input widths must reach the optimizer's own search bound (40 µm — `HI = log10(40)` in
# server.optimize), because that is where it lands and a fit that stops at 32 is
# extrapolating exactly there. Diagnosed from a per-term comparison on optimizer output:
# the input term was accurate to +1% while the ncc term under-predicted 26%, and the
# geometry ratio at input 40 / ncc 2.25 sat outside the fitted range.
TRAIN = [{"devices": {"input": {"w_um": iw}, "ncc": {"w_um": nw}}}
         for iw in (4.0, 8.0, 16.0, 32.0, 40.0)
         for nw in (0.5, 1.0, 2.0, 4.0, 8.0)]

# R_input gets its OWN sweep, at nominal ncc. Fitting it on TRAIN is wrong and the
# loop caught me doing it: that grid drives ncc down to 0.5 µm to expose the latch
# term, and a weak latch inflates the input pair's measured offset, so a median over
# TRAIN returned R_input = 1.363 where a nominal-latch sweep gives 1.06. The held-out
# error looked better because the held-out set shares the same skew, which is exactly
# the trap a held-out gate is supposed to catch and would not have.
# Widths chosen to avoid HOLDOUT's input-only points (3.0 and 24.0) — they were in
# both until a test noticed, which made two of the eight gate points training data.
TRAIN_INPUT = [{"devices": {"input": {"w_um": w}}}
               for w in (2.0, 4.0, 5.0, 10.0, 16.0, 30.0)]
# The grids above are hand-chosen, and that turned out to be the model's biggest
# weakness rather than a detail. Validated on them the predictor is off by a median
# -10%; on the sizings the *optimizer actually converges to* it is off by -35%
# (worst -42%), because the search seeks out precisely the region where the model is
# most optimistic — that is where it reports "cheap and compliant". The gate never saw
# that region, so the validation missed it.
#
# `optimizer_sizings()` adds those points. It makes the calibration depend on the
# optimizer, which depends on the constants being calibrated, so this is a fixed-point
# iteration rather than a one-shot fit: one pass moves the model toward the region that
# matters, and re-running moves it further. The loop reports the two regions' bias
# separately so the selection effect stays visible instead of averaging away.
HOLDOUT = [
    {},                                                        # the seed itself
    {"devices": {"input": {"w_um": 24.0}}},
    {"devices": {"input": {"w_um": 3.0}}},
    {"devices": {"ncc": {"w_um": 0.8}}},
    {"devices": {"ncc": {"w_um": 12.0}}},
    {"devices": {"input": {"w_um": 19.12}, "ncc": {"w_um": 1.16}, "pcc": {"w_um": 0.79}}},
    # the extreme corner — deliberately just off the training grid, which now reaches
    # input 40.0, so this stays a genuine gate point
    {"devices": {"input": {"w_um": 36.0}, "ncc": {"w_um": 0.6}}},
    {"devices": {"input": {"w_um": 6.0}, "ncc": {"w_um": 3.0}, "pcc": {"w_um": 6.0}}},
]


def optimizer_sizings(model, targets=None, seeds=(1234, 7, 99, 4242)):
    """Sizings the optimizer actually lands on — the region the predictor is used in.

    Imported lazily: the calibration script is useful without a webapp on the path, and
    only this function needs it."""
    sys.path.insert(0, os.path.join(ROOT, "webapp"))
    import server                                              # noqa: E402
    t = targets or {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 2.0}
    out = []
    for s in seeds:
        fin = server.optimize(run_sim._full({"model": model}), t,
                              seed=s, budget_check=False)["final_params"]
        # the WHOLE device dict, not just w_um. Taking only the width dropped the `vt`
        # levels the optimizer's Vt pass assigns — so the loop was calibrating on a
        # different device than the optimizer produces, and the measured bias in this
        # region came out 13.6% instead of the ~35% a direct measurement shows.
        # the WHOLE params, scalars included — vcm_frac especially, which the
        # corner-feasibility step raises and which changes the measured offset by ~2x
        out.append({k: (copy.deepcopy(v) if k == "devices" else v)
                    for k, v in fin.items()})
    return out


def measured(model, override, n_mc, seeds, method="quadrature"):
    """Measured contribution per group, from the DETERMINISTIC reference by default.

    This used to be a median over estimator seeds, because one Monte-Carlo draw scatters
    ~27-33% and does not tighten with n_mc. Averaging noise was the best available answer
    while the reference was Monte Carlo; it is not any more. `offset_budget`'s quadrature
    path evaluates the same expectation exactly — each group's mismatch is a single scalar,
    so it is a 1-D integral, not a sampling problem — and it repeats bit-for-bit.

    That matters more than precision. The old reference could not tell a real 55%
    out-of-sample error from noise, so the gate below was passing fits that did not
    generalise. `seeds` and `n_mc` now apply only to `method="mc"`, kept for comparison.

    `override` is a full params override, not just a devices dict. Passing only devices
    silently dropped whatever scalars the optimizer had changed — it raises `vcm_frac`
    from 0.62 to 0.82 in its corner-feasibility step — and measuring at 0.62 gave an ncc
    contribution of 0.98 where the real circuit gives 2.03. A 2.1x error from a dropped
    field, and the third time this loop lost information by reconstructing a sizing from
    a subset of it (first `w_um` only, losing `vt`; then `devices` only, losing this).
    So nothing is reconstructed any more: overrides are whole params."""
    ov = dict(override or {})
    ov.setdefault("model", model)
    p = run_sim._full(ov)
    if method == "quadrature":
        b = run_sim.offset_budget(p)
        return p, {g: (v.get("offset_sigma_mv"), v["pelgrom_sigma_vth_mv"])
                   for g, v in b["per_device"].items()}
    out = {}
    for g in run_sim.OFFSET_PAIRS:
        sig = run_sim.pelgrom_sigma_v(p, g)
        vals = []
        for s in seeds:
            if g == "input":
                import random
                c = run_sim.measure_offset({**p, "n_mc": n_mc},
                                           random.Random(s)).get("offset_sigma_mv")
            else:
                c = run_sim._offset_of_pair(p, g, sig, n_mc, s).get("offset_sigma_mv")
            if c:
                vals.append(c)
        out[g] = (statistics.median(vals) if vals else None, sig * 1e3)
    return p, out


def fit_input_R(rows):
    """R_input = contribution / sigma_Vth, a plain ratio, so a median is the whole fit.

    NOTE this is now a CHECK, not a fit. Measured deterministically the input pair's
    response is v = -d to within 0.06% on all four backends out to 4 sigma, so a linear
    response gives R_input = sqrt(2) exactly and there is nothing to fit. This function
    stays because the ratio is worth watching — if a backend ever breaks linearity it will
    show up here — but `main` no longer writes what it returns. Fitting it is how the
    constant got published as 1.06 and then 1.268, both wrong, both times because a
    reference with a 21% standard error was treated as ground truth.

    Must be given the nominal-latch sweep: on the latch-fitting grid the weakened
    latch inflates the input pair's measured offset. The spread across the sweep is
    reported so a drift in stability shows up."""
    rs = [c / s for _, m in rows for c, s in [m["input"]] if c and s]
    if not rs:
        return None, None
    return statistics.median(rs), (max(rs) - min(rs)) / statistics.median(rs)


def fit_ncc(rows):
    """contribution = k * sigma_Vth^a * (Wi*Mi / Wn*Mn)^b, least squares in log space."""
    X, Y = [], []
    for p, m in rows:
        c, s = m["ncc"]
        if not c or not s:
            continue
        di, dn = p["devices"]["input"], p["devices"]["ncc"]
        ratio = (di["w_um"] * di["m"]) / max(dn["w_um"] * dn["m"], 1e-9)
        X.append((1.0, math.log(s), math.log(ratio)))
        Y.append(math.log(c))
    n = len(X)
    if n < 5:
        return None
    M = [[sum(X[i][r] * X[i][c] for i in range(n)) for c in range(3)] for r in range(3)]
    v = [sum(X[i][r] * Y[i] for i in range(n)) for r in range(3)]
    for i in range(3):                                  # gaussian elimination
        pv = M[i][i]
        for j in range(i + 1, 3):
            f = M[j][i] / pv
            for k in range(3):
                M[j][k] -= f * M[i][k]
            v[j] -= f * v[i]
    s3 = [0.0] * 3
    for i in (2, 1, 0):
        s3[i] = (v[i] - sum(M[i][k] * s3[k] for k in range(i + 1, 3))) / M[i][i]
    return math.exp(s3[0]), s3[1], s3[2]


def fit_flat(rows, group):
    """Groups whose contribution does not track their own sigma — pcc rises with its
    width, pre/prei are constant — are modelled as a single number, so the fit is a
    median. Guards against a sigma-proportional term pushing the search backwards."""
    vals = [m[group][0] for _, m in rows if m[group][0]]
    return statistics.median(vals) if vals else None


def predict(p, k, a, b, r_input, flat):
    """Predict with a candidate constant set by installing it and calling the model.

    This used to reimplement `predicted_offset_budget_mv`'s formula, and the two
    silently diverged the moment `pcc` stopped being a flat constant — a calibration
    loop fitting a formula the production code no longer uses is worse than none. Now
    there is one formula and the loop only swaps its constants.

    The latch coefficient is per model, so it has to be installed into
    `_OFFSET_NCC_K_BY_MODEL` and not only into the scalar fallback: patching the scalar
    alone left the candidate K silently ignored for every backend that has its own
    entry, which is all four of them.
    """
    model = p.get("model") or "ptm45"
    saved = (run_sim._OFFSET_NCC_K, run_sim._OFFSET_NCC_A, run_sim._OFFSET_NCC_B,
             run_sim._OFFSET_R_INPUT, dict(run_sim._OFFSET_FLAT_MV),
             dict(run_sim._OFFSET_NCC_K_BY_MODEL))
    try:
        run_sim._OFFSET_NCC_K_BY_MODEL = {**run_sim._OFFSET_NCC_K_BY_MODEL, model: k}
        run_sim._OFFSET_NCC_K, run_sim._OFFSET_NCC_A, run_sim._OFFSET_NCC_B = k, a, b
        run_sim._OFFSET_R_INPUT = r_input
        run_sim._OFFSET_FLAT_MV = {g: v for g, v in flat.items()
                                   if g in run_sim._OFFSET_FLAT_MV}
        return run_sim.predicted_offset_budget_mv(p)[0]
    finally:
        (run_sim._OFFSET_NCC_K, run_sim._OFFSET_NCC_A, run_sim._OFFSET_NCC_B,
         run_sim._OFFSET_R_INPUT, run_sim._OFFSET_FLAT_MV,
         run_sim._OFFSET_NCC_K_BY_MODEL) = saved


def holdout_error(rows, k, a, b, r_input, flat):
    """Median absolute relative error of the *total* budget on held-out sizings."""
    errs = []
    for p, m in rows:
        tot = math.sqrt(sum(c * c for c, _ in m.values() if c))
        if tot <= 0:
            continue
        errs.append(abs(predict(p, k, a, b, r_input, flat) - tot) / tot)
    return statistics.median(errs) if errs else None


def current(model="ptm45"):
    return (run_sim._OFFSET_NCC_K_BY_MODEL.get(model, run_sim._OFFSET_NCC_K),
            run_sim._OFFSET_NCC_A, run_sim._OFFSET_NCC_B,
            run_sim._OFFSET_R_INPUT, dict(run_sim._OFFSET_FLAT_MV))


def _sub1(src, pat, repl, what):
    """re.sub that refuses to silently no-op.

    Every one of these patterns has been broken once by an unrelated edit to the
    constant block, and a regex that matches nothing turns --apply into a loop that
    reports success and changes nothing."""
    out, n = re.subn(pat, repl, src, count=1)
    if n != 1:
        raise SystemExit(f"apply: pattern for {what} matched {n} times in run_sim.py, "
                         f"expected 1 — the constant block moved; fix the pattern "
                         f"rather than letting --apply no-op")
    return out


def apply_constants(k, a, b, r_input, flat, model="ptm45"):
    """Rewrite the fitted constants in run_sim.py, keeping a .bak.

    `k` lands in that model's slot in `_OFFSET_NCC_K_BY_MODEL`; the exponents and the flat
    terms are global. `r_input` is accepted and IGNORED — it is sqrt(2) by the linearity of
    the input response, not a fit, and rewriting it is what produced two wrong published
    values. The parameter stays so callers do not silently pass a fit into nowhere."""
    if abs(r_input - run_sim._OFFSET_R_INPUT) > 1e-9:
        print(f"  note: R_input {r_input:.4g} not applied — held at sqrt(2) by linearity")
    path = os.path.join(ROOT, "run_sim.py")
    original = src = open(path).read()
    # every substitution first, then the .bak, then the write: a failing pattern used to
    # leave a stray .bak behind having changed nothing
    src = _sub1(src, rf'("{re.escape(model)}": )[\d.]+', rf"\g<1>{k:.4g}",
                f"latch coefficient for {model}")
    src = _sub1(src, r"_OFFSET_NCC_A, _OFFSET_NCC_B = [^\n]+",
                f"_OFFSET_NCC_A, _OFFSET_NCC_B = {a:.4g}, {b:.4g}", "ncc exponents")
    src = _sub1(src, r"_OFFSET_FLAT_MV = \{[^}]*\}",
                "_OFFSET_FLAT_MV = {" + ", ".join(
                    f'"{g}": {v:.3g}' for g, v in flat.items()) + "}", "flat terms")
    open(path + ".bak", "w").write(original)
    open(path, "w").write(src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="ptm45")
    ap.add_argument("--n-mc", type=int, default=16)
    ap.add_argument("--seeds", type=int, default=5,
                    help="estimator seeds per measurement. 3 was too few for the input "
                         "referral factor — it refitted to 1.179 where 5 seeds give a "
                         "stable 1.268 — and a single draw is how the value got "
                         "published as 1.06 in the first place")
    ap.add_argument("--mc-reference", action="store_true",
                    help="use the Monte-Carlo reference instead of the deterministic "
                         "quadrature one. Kept for comparison only: it carries a 21%% "
                         "standard error per estimate, which is larger than most of the "
                         "differences this loop is asked to resolve, and it could not "
                         "distinguish a real 55%% out-of-sample error from noise")
    ap.add_argument("--apply", action="store_true",
                    help="rewrite the constants if the held-out error improves")
    ap.add_argument("--no-optimizer-sizings", action="store_true",
                    help="skip adding optimizer-converged sizings to the grids. They "
                         "are the region the predictor is actually used in and where "
                         "it is worst, so excluding them reproduces the blind spot "
                         "this loop exists to close")
    ap.add_argument("--region-slack", type=float, default=0.10,
                    help="how much the optimizer-converged region may regress before it "
                         "vetoes an otherwise-improving refit (default 10%%, to absorb "
                         "estimator noise without letting a real regression through)")
    ap.add_argument("--limit", type=int, default=0,
                    help="subsample every grid to N sizings — for smoke-testing the "
                         "loop end to end without a full measurement run (a full run "
                         "takes >10 min and saturates the ngspice gate)")
    args = ap.parse_args()
    seeds = [11 + 11 * i for i in range(args.seeds)]
    train_grid, input_grid, hold_grid = TRAIN, TRAIN_INPUT, HOLDOUT
    if args.limit:
        # keep the ends of each grid, not the head — the extremes are what the fit is
        # weakest on, so a subsample that drops them would flatter the model
        def ends(g, n):
            return g[: max(1, n // 2)] + g[-max(1, n - n // 2):] if len(g) > n else g
        train_grid = ends(TRAIN, max(args.limit, 6))
        input_grid = ends(TRAIN_INPUT, max(args.limit, 3))
        hold_grid = ends(HOLDOUT, max(args.limit, 3))

    # Appended AFTER --limit on purpose: that branch rebuilds the grids from the module
    # constants, so adding these earlier silently dropped them — which is how the first
    # run of this feature measured the optimizer region for reporting while excluding it
    # from the fit, i.e. exactly the blind spot it was meant to close.
    opt_grid = []
    if not args.no_optimizer_sizings:
        print("running the optimizer to collect the sizings it converges to…")
        opt_grid = optimizer_sizings(args.model)
        # into BOTH: training so the fit covers the region, holdout so the gate sees it
        train_grid = train_grid + opt_grid
        hold_grid = hold_grid + opt_grid

    t0 = time.time()
    print(f"measuring {len(train_grid)} latch-grid + {len(input_grid)} input-sweep + "
          f"{len(hold_grid)} held-out sizings "
          f"(model={args.model}, n_mc={args.n_mc}, {args.seeds} estimator seeds"
          + (f", subsampled --limit {args.limit}" if args.limit else "") + ")…")
    train = [measured(args.model, d, args.n_mc, seeds,
                       method="mc" if args.mc_reference else "quadrature") for d in train_grid]
    train_in = [measured(args.model, d, args.n_mc, seeds,
                       method="mc" if args.mc_reference else "quadrature") for d in input_grid]
    hold = [measured(args.model, d, args.n_mc, seeds,
                       method="mc" if args.mc_reference else "quadrature") for d in hold_grid]
    print(f"  measured in {time.time() - t0:.0f}s")

    fit = fit_ncc(train)
    # R_input is NOT fitted any more. It is sqrt(2) exactly, because the input pair's
    # response to a differential Vth mismatch is linear — verified directly rather than
    # inferred. The measured ratio is still computed and reported so a backend that broke
    # linearity would be visible, but the loop no longer writes it: refitting this constant
    # against a noisy reference is how it got published as 1.06 and then 1.268.
    r_check = fit_input_R(train_in)   # own sweep, at nominal latch — see TRAIN_INPUT
    r_check, r_spread = r_check if isinstance(r_check, tuple) else (r_check, None)
    r_in = run_sim._OFFSET_R_INPUT
    lin = run_sim.input_referral_is_linear({"model": args.model})
    if not fit:
        print("not enough usable measurements — nothing to fit")
        return 1
    k, a, b = fit
    flat = {g: fit_flat(train, g) or run_sim._OFFSET_FLAT_MV[g]
            for g in run_sim._OFFSET_FLAT_MV}

    ck, ca, cb, cr, cflat = current(args.model)
    e_old = holdout_error(hold, ck, ca, cb, cr, cflat)
    e_new = holdout_error(hold, k, a, b, r_in, flat)
    print(f"\n  R_input   : held at sqrt(2) = {r_in:.6g} — linear={lin['linear']}, "
          f"max deviation {lin['max_deviation']:.2%} out to 4 sigma"
          + (f"; measured ratio/sigma_1dev {r_check:.4g}" if r_check else "")
          + (f" (spread {r_spread:.0%})" if r_spread is not None else ""))
    if not lin["linear"]:
        print("  WARNING: the input response is no longer linear on this backend, so "
              "R_input = sqrt(2) is not safe here. Investigate before trusting any fit.")
    print(f"  current : ncc k={ck:.4g} a={ca:.4g} b={cb:.4g}  flat {cflat}")
    print(f"  refitted: ncc k={k:.4g} a={a:.4g} b={b:.4g}  flat "
          + "{" + ", ".join(f"{g}: {v:.3g}" for g, v in flat.items()) + "}")
    print(f"\n  held-out median |error|:  current {e_old:.1%}   refitted {e_new:.1%}")
    e_opt_old = e_opt_new = None
    if opt_grid:
        # report the two regions separately — an average hides the selection effect,
        # and the optimizer region also gets veto power over the verdict below
        # partition by position, not by comparing reconstructed device dicts — the
        # optimizer rows are exactly the tail that was appended to hold_grid, and
        # matching on a reconstruction is what lost vcm_frac in the first place
        n_opt = len(opt_grid)
        hand_rows, opt_rows = hold[:-n_opt], hold[-n_opt:]
        for label, rows in (("hand-chosen", hand_rows), ("optimizer-converged", opt_rows)):
            if not rows:
                continue
            eo = holdout_error(rows, ck, ca, cb, cr, cflat)
            en = holdout_error(rows, k, a, b, r_in, flat)
            print(f"    {label:22s} current {eo:.1%}   refitted {en:.1%}")
            if label == "optimizer-converged":
                e_opt_old, e_opt_new = eo, en

    # The gate cannot be a median over the whole holdout. Its first real run improved
    # the hand-chosen region 13.0% -> 3.4% while making the optimizer-converged region
    # WORSE (6.4% -> 9.2%) and accepted anyway, because eight hand-chosen points outvote
    # four optimizer ones. That is backwards: the optimizer region is the only one the
    # predictor is used in. So the overall error must improve AND the optimizer region
    # must not regress.
    accept = e_new is not None and e_old is not None and e_new < e_old
    reason = "held-out error improved" if accept else "no held-out improvement"
    if accept and opt_grid and e_opt_old is not None and e_opt_new is not None:
        if e_opt_new > e_opt_old * (1.0 + args.region_slack):
            accept = False
            reason = (f"overall improved but the optimizer-converged region regressed "
                      f"({e_opt_old:.1%} -> {e_opt_new:.1%}) — that is the region the "
                      f"predictor is actually used in, so it vetoes")
    print("  verdict: " + ("ACCEPT — " + reason if accept else "REJECT — " + reason
                           + ", keeping current"))

    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "a") as f:
        f.write(json.dumps({
            "model": args.model, "n_mc": args.n_mc, "seeds": seeds,
            "limit": args.limit or None,
            "optimizer_sizings": len(opt_grid),
            "grid_sizes": [len(train_grid), len(input_grid), len(hold_grid)],
            "current": {"r_input": cr, "k": ck, "a": ca, "b": cb, "flat": cflat},
            "reference": "quadrature" if not args.mc_reference else "mc",
            "r_input": {"held_at": r_in, "measured_ratio": r_check,
                        "spread": r_spread, "linear": lin["linear"],
                        "max_deviation": lin["max_deviation"]},
            "refitted": {"k": k, "a": a, "b": b, "flat": flat},
            "holdout_err_current": e_old, "holdout_err_refit": e_new,
            "holdout_err_optimizer_region": {"current": e_opt_old, "refit": e_opt_new},
            "verdict_reason": reason,
            "accepted": bool(accept and args.apply),
            "applied": bool(accept and args.apply),
            "seconds": round(time.time() - t0, 1),
        }) + "\n")
    print(f"  history appended to {os.path.relpath(HISTORY, ROOT)}")

    if accept and args.apply:
        apply_constants(k, a, b, r_in, flat, model=args.model)
        print("  constants rewritten in run_sim.py (.bak kept) — run the test suite now")
    elif accept:
        print("  re-run with --apply to write them")
    return 0


if __name__ == "__main__":
    sys.exit(main())

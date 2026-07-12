#!/usr/bin/env python3
"""WiCkeD-inspired robustness analysis and sizing flow for the StrongARM backend.

This is NOT Cadence/MunEDA WiCkeD. It is an open, ngspice-backed implementation
of the public methodology ideas that fit this repo:

* FEO/DNO style feasibility + nominal sizing refinement.
* Sensitivity-guided parameter moves rather than blind manual tuning.
* Worst-case operation (WCO) over process/voltage/temperature.
* Worst-case distance (WCD) as a sigma robustness proxy for high-sigma/yield.
* Full-device mismatch budget across all device groups.
* Importance-sampled high-sigma yield estimation.
* Yield-aware robust design-centering optimizer.
* Parameter screening for design-variable ranking.
* Yield sweep over global variation (WiCkeD yield-plot style).
* Post-layout WCD re-evaluation through the existing layout parasitic proxy.
* Worst-case corner extraction from the full PVT grid.

The implementation intentionally uses only the Python stdlib and the existing
run_sim.py ngspice wrapper so it works in the current repo without commercial EDA
licenses. The WCD estimate is a practical proxy: it combines an analytic Pelgrom
mismatch distance with simulation-backed operating/PVT boundary interpolation.
"""
import copy
import math
import random
from concurrent.futures import ThreadPoolExecutor

import run_sim

DEFAULT_TARGETS = {
    "decision_time_ps": 400.0,
    "power_uw": 100.0,
    "offset_sigma_mv": 5.0,
    "yield_pct": 99.0,
}
DEV_KEYS = ["input", "tail", "ncc", "pcc", "pre"]
_WORKERS = max(2, min(8, __import__("os").cpu_count() or 4))


def _pmap(fn, items):
    items = list(items)
    if len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        return list(ex.map(fn, items))


def _full(params):
    p = copy.deepcopy(run_sim.DEFAULT_PARAMS)
    params = params or {}
    p.update({k: v for k, v in params.items() if k != "devices"})
    p["devices"] = run_sim.merge_devices(params.get("devices"))
    return p


def _targets(targets):
    t = dict(DEFAULT_TARGETS)
    t.update(targets or {})
    return t


def predicted_offset_sigma_mv(params):
    """Input-referred pair offset sigma from Pelgrom, matching repo convention."""
    p = _full(params)
    d = p["devices"]["input"]
    area = max(d["w_um"] * (d["l_nm"] / 1000.0) * d["m"], 1e-12)
    return math.sqrt(2.0) * p["avt_mv_um"] / math.sqrt(area)


def total_width_um(params):
    p = _full(params)
    return round(sum(d["w_um"] * d["m"] for d in p["devices"].values()), 3)


def nominal_verdict(params, targets=None, with_noise=False):
    """Run nominal ngspice once and return normalized margins for main specs."""
    p, t = _full(params), _targets(targets)
    r = run_sim.run_sim(p, do_offset=False, with_noise=with_noise)
    nom = r["nominal"]
    offp = predicted_offset_sigma_mv(p)
    margins = {
        "functional": 1.0 if nom.get("functional") else -1.0,
        "decision_time_ps": _margin_le(nom.get("decision_time_ps"), t["decision_time_ps"]),
        "power_uw": _margin_le(nom.get("power_uw"), t["power_uw"]),
        "offset_sigma_mv": _margin_le(offp, t["offset_sigma_mv"]),
    }
    return {"nominal": nom, "predicted_offset_sigma_mv": round(offp, 4),
            "margins": margins, "pass": all(v is not None and v >= 0 for v in margins.values()),
            "params": p, "targets": t}


def _margin_le(value, limit):
    if value is None or limit in (None, 0):
        return None
    return (float(limit) - float(value)) / float(limit)


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


def _scale_width(params, key, factor):
    p = copy.deepcopy(params)
    d = p["devices"][key]
    d["w_um"] = round(_clip(d["w_um"] * factor, 0.5, 80.0), 3)
    return p


def sensitivity(params, targets=None, delta=0.12):
    """One-at-a-time width sensitivity for DNO-style guidance."""
    p, t = _full(params), _targets(targets)
    base = nominal_verdict(p, t)["nominal"]
    base_off = predicted_offset_sigma_mv(p)

    def metrics(pp):
        n = run_sim.run_sim(pp, do_offset=False)["nominal"]
        return {"decision_time_ps": n.get("decision_time_ps"),
                "power_uw": n.get("power_uw"),
                "functional": bool(n.get("functional")),
                "offset_sigma_mv": predicted_offset_sigma_mv(pp)}

    jobs = [(k, 1.0 - delta) for k in DEV_KEYS] + [(k, 1.0 + delta) for k in DEV_KEYS]
    vals = _pmap(lambda kf: metrics(_scale_width(p, kf[0], kf[1])), jobs)
    by = {k: {} for k in DEV_KEYS}
    for (k, f), m in zip(jobs, vals):
        by[k]["low" if f < 1 else "high"] = m
    out = []
    for k in DEV_KEYS:
        low, high = by[k]["low"], by[k]["high"]
        out.append({
            "key": k,
            "base_w_um": p["devices"][k]["w_um"],
            "d_decision_ps_per_pct_width": _slope_pct(low["decision_time_ps"], high["decision_time_ps"], delta),
            "d_power_uw_per_pct_width": _slope_pct(low["power_uw"], high["power_uw"], delta),
            "d_offset_mv_per_pct_width": _slope_pct(low["offset_sigma_mv"], high["offset_sigma_mv"], delta),
            "low": low,
            "high": high,
        })
    return {"base": {"decision_time_ps": base.get("decision_time_ps"),
                     "power_uw": base.get("power_uw"),
                     "functional": base.get("functional"),
                     "offset_sigma_mv": round(base_off, 4)},
            "delta_pct": round(delta * 100, 2), "devices": out, "targets": t}


def _slope_pct(lo, hi, delta):
    if lo is None or hi is None:
        return None
    return round((hi - lo) / (2.0 * delta * 100.0), 5)


def dno_refine(params, targets=None, iterations=4):
    """Small deterministic nominal optimization loop inspired by WiCkeD DNO.

    It uses explicit feasibility moves for offset/speed, then a sensitivity-guided
    power trim when specs pass. This is deliberately conservative and inspectable.
    """
    p, t = _full(params), _targets(targets)
    history = []
    for it in range(max(1, int(iterations))):
        v = nominal_verdict(p, t)
        nom, offp = v["nominal"], v["predicted_offset_sigma_mv"]
        action = "hold"
        if not nom.get("functional") or nom.get("decision_time_ps") is None:
            for k in ("tail", "ncc", "pcc"):
                p = _scale_width(p, k, 1.25)
            action = "feasibility: strengthen latch/tail widths"
        elif offp > t["offset_sigma_mv"]:
            # Required area from sigma_pair = sqrt(2)*AVT/sqrt(W*L*M).
            d = p["devices"]["input"]
            req_area = (math.sqrt(2.0) * p["avt_mv_um"] / (0.92 * t["offset_sigma_mv"])) ** 2
            l_um = d["l_nm"] / 1000.0
            d["w_um"] = round(_clip(req_area / max(l_um * d["m"], 1e-12), d["w_um"], 80.0), 3)
            action = "feasibility: enlarge input pair for offset robustness"
        elif nom["decision_time_ps"] > t["decision_time_ps"]:
            s = sensitivity(p, t, delta=0.10)["devices"]
            # Most negative slope: width increase reduces decision time most.
            useful = [x for x in s if x["d_decision_ps_per_pct_width"] is not None]
            key = min(useful, key=lambda x: x["d_decision_ps_per_pct_width"])["key"] if useful else "tail"
            p = _scale_width(p, key, 1.20)
            action = f"DNO: widen {key} for decision-time margin"
        elif nom.get("power_uw") is not None and nom["power_uw"] > t["power_uw"]:
            s = sensitivity(p, t, delta=0.10)["devices"]
            # Trim the device whose shrink hurts decision least and saves power.
            candidates = [x for x in s if x["d_decision_ps_per_pct_width"] is not None]
            key = max(candidates, key=lambda x: x["d_decision_ps_per_pct_width"])["key"] if candidates else "pre"
            p = _scale_width(p, key, 0.90)
            action = f"DNO: trim {key} to reduce power"
        else:
            # Passed; try one gentle trim of precharge/core parasitic/power.
            p = _scale_width(p, "pre", 0.95)
            action = "centered: gentle precharge trim"
        history.append({"iter": it, "action": action, "nominal": nom,
                        "predicted_offset_sigma_mv": offp,
                        "total_width_um": total_width_um(p),
                        "devices": copy.deepcopy(p["devices"])})
    final = nominal_verdict(p, t, with_noise=True)
    return {"initial_params": _full(params), "final_params": p, "history": history,
            "final": final, "success": final["pass"]}


def robust_refine(params, targets=None, iterations=2):
    """Representative-corner refinement before full WCO.

    This is a cheap WCO-in-the-loop step: test likely slow corners and strengthen
    regenerative devices until the representative worst corner resolves within
    the decision spec, or the iteration budget is exhausted.
    """
    p, t = _full(params), _targets(targets)
    history = []
    _sk = 0.05 * run_sim.skew_scale(p)   # gaa2nm: |Vth0| 0.2V 에 맞춰 ±25mV
    reps = [("SS_cold_lowV", _sk, -40, 0.90), ("SS_hot_lowV", _sk, 125, 0.90),
            ("TT_room_nomV", 0.0, 27, 1.0), ("FF_cold_highV", -_sk, -40, 1.10)]
    base_vdd = float(p.get("vdd", run_sim.DEFAULT_PARAMS["vdd"]))
    for it in range(max(0, int(iterations))):
        def one(r):
            name, skew, temp, vf = r
            n = run_sim.run_sim({**p, "pskew": skew, "temp": temp, "vdd": round(base_vdd * vf, 3)}, do_offset=False)["nominal"]
            return {"corner": name, "decision_time_ps": n.get("decision_time_ps"),
                    "power_uw": n.get("power_uw"), "functional": bool(n.get("functional"))}
        corners = _pmap(one, reps)
        worst = max((c for c in corners if c["decision_time_ps"] is not None),
                    key=lambda c: c["decision_time_ps"], default=None)
        ok = worst is not None and worst["decision_time_ps"] <= t["decision_time_ps"] and all(c["functional"] for c in corners)
        history.append({"iter": it, "ok": bool(ok), "corners": corners, "devices": copy.deepcopy(p["devices"])})
        if ok:
            break
        # Strengthen the regeneration/current path. Do not touch input unless offset is limiting.
        for k, f in (("tail", 1.25), ("ncc", 1.22), ("pcc", 1.22)):
            p = _scale_width(p, k, f)
    final = nominal_verdict(p, t)
    return {"final_params": p, "history": history, "final": final}


def wco_operating(params, targets=None):
    """Worst-case operation over process, temperature, and VDD.

    Mirrors public WiCkeD WCO guidance: run enumerated corners; do not skip final
    verification corners based only on a model. For PTM we map process to Vth skew;
    for SKY130 we use the PDK corner names already supported by run_sim.py.
    """
    p, t = _full(params), _targets(targets)
    base_vdd = float(p.get("vdd", run_sim.DEFAULT_PARAMS["vdd"]))
    sky = p.get("model") == "sky130"
    cmap = {"SS": "ss", "TT": "tt", "FF": "ff", "SF": "sf", "FS": "fs"}
    specs = []
    _sk = 0.05 * run_sim.skew_scale(p)   # gaa2nm: ±25mV
    for label, ns, ps in (("SS", _sk, _sk), ("TT", 0.0, 0.0), ("FF", -_sk, -_sk),
                          ("SF", _sk, -_sk), ("FS", -_sk, _sk)):
        for temp in (-40, 27, 125):
            for vf in (0.9, 1.0, 1.1):
                proc = {"corner": cmap[label]} if sky else {"nskew": ns, "pskew_p": ps}
                specs.append((label, temp, vf, round(base_vdd * vf, 3), proc))

    def one(s):
        label, temp, vf, vdd, proc = s
        n = run_sim.run_sim({**p, "vdd": vdd, "temp": temp, **proc}, do_offset=False)["nominal"]
        return {"process": label, "temp": temp, "v_frac": vf, "vdd": vdd,
                "decision_time_ps": n.get("decision_time_ps"),
                "power_uw": n.get("power_uw"), "functional": bool(n.get("functional")),
                "decision_margin": _margin_le(n.get("decision_time_ps"), t["decision_time_ps"]),
                "power_margin": _margin_le(n.get("power_uw"), t["power_uw"])}

    corners = _pmap(one, specs)
    worst_dec = max((c["decision_time_ps"] for c in corners if c["decision_time_ps"] is not None), default=None)
    worst_pw = max((c["power_uw"] for c in corners if c["power_uw"] is not None), default=None)
    min_dec_margin = min((c["decision_margin"] for c in corners if c["decision_margin"] is not None), default=None)
    return {"corners": corners, "worst": {"decision_time_ps": worst_dec,
            "power_uw": worst_pw, "any_nonfunctional": any(not c["functional"] for c in corners),
            "min_decision_margin": min_dec_margin}, "targets": t}


def worst_case_distance(params, targets=None, n_samples=24, seed=19):
    """Estimate nearest failure distance in sigma units.

    Components:
    1. Analytic offset WCD: beta_offset = offset_limit / sigma_offset.
    2. Simulation-backed operating WCD: sample standard-normal directions for
       process skew, VDD, and temperature; interpolate the boundary distance when
       decision-time crosses the target.
    The reported beta is the minimum of all observed/interpolated mechanisms.
    """
    p, t = _full(params), _targets(targets)
    rng = random.Random(seed)
    nom = run_sim.run_sim(p, do_offset=False)["nominal"]
    nom_dec = nom.get("decision_time_ps")
    sigma_off = predicted_offset_sigma_mv(p)
    beta_offset = (t["offset_sigma_mv"] / sigma_off) if sigma_off > 0 else float("inf")
    candidates = [{"metric": "offset_sigma_mv", "beta": beta_offset,
                   "detail": f"offset limit / predicted sigma = {t['offset_sigma_mv']}/{round(sigma_off,4)}"}]

    base_vdd = float(p.get("vdd", run_sim.DEFAULT_PARAMS["vdd"]))
    samples = []
    for _ in range(max(1, int(n_samples))):
        z_proc = _clip(rng.gauss(0, 1), -3.5, 3.5)
        z_vdd = _clip(rng.gauss(0, 1), -3.5, 3.5)
        z_temp = _clip(rng.gauss(0, 1), -3.5, 3.5)
        cfg = {**p,
               "pskew": 0.03 * run_sim.skew_scale(p) * z_proc,
               "vdd": round(_clip(base_vdd * (1.0 - 0.05 * z_vdd), 0.75 * base_vdd, 1.25 * base_vdd), 4),
               "temp": round(_clip(27.0 + 45.0 * z_temp, -40.0, 125.0), 2)}
        samples.append((z_proc, z_vdd, z_temp, cfg))

    def one(s):
        zp, zv, zt, cfg = s
        n = run_sim.run_sim(cfg, do_offset=False)["nominal"]
        dec = n.get("decision_time_ps")
        dist = math.sqrt(zp * zp + zv * zv + zt * zt)
        beta = None
        failed = (not n.get("functional")) or dec is None or (dec > t["decision_time_ps"])
        if failed:
            if nom_dec is not None and dec is not None and dec > nom_dec and dec != nom_dec:
                frac = (t["decision_time_ps"] - nom_dec) / (dec - nom_dec)
                beta = max(0.0, min(dist, dist * frac))
            else:
                beta = dist
        return {"z": [round(zp, 3), round(zv, 3), round(zt, 3)],
                "distance": round(dist, 3), "beta_to_failure": round(beta, 3) if beta is not None else None,
                "decision_time_ps": dec, "power_uw": n.get("power_uw"),
                "functional": bool(n.get("functional")), "failed": bool(failed),
                "vdd": cfg["vdd"], "temp": cfg["temp"], "pskew": round(cfg["pskew"], 4)}

    sim_samples = _pmap(one, samples)
    betas = [s["beta_to_failure"] for s in sim_samples if s["beta_to_failure"] is not None]
    if betas:
        b = min(betas)
        nearest = min((s for s in sim_samples if s["beta_to_failure"] is not None), key=lambda s: s["beta_to_failure"])
        candidates.append({"metric": "decision_time_ps", "beta": b, "detail": "nearest simulated/interpolated PVT failure", "sample": nearest})
    beta = min(c["beta"] for c in candidates if c["beta"] is not None)
    limiting = min(candidates, key=lambda c: c["beta"] if c["beta"] is not None else float("inf"))
    # Conservative one-sided normal robustness proxy; offset is two-sided, handled separately below.
    normal_yield = 0.5 * (1.0 + math.erf(beta / math.sqrt(2.0)))
    offset_yield = math.erf(beta_offset / math.sqrt(2.0)) if math.isfinite(beta_offset) else 1.0
    yield_pct = 100.0 * min(normal_yield, offset_yield)
    return {"beta_sigma": round(beta, 3), "estimated_yield_pct": round(yield_pct, 4),
            "limiting_mechanism": limiting, "candidates": candidates,
            "nominal": nom, "predicted_offset_sigma_mv": round(sigma_off, 4),
            "samples": sim_samples, "targets": t,
            "note": "WCD proxy: analytic Pelgrom offset + ngspice PVT boundary sampling; not commercial WiCkeD."}


def mismatch_budget(params):
    """Approximate full-device mismatch budget by device group.

    ngspice injection currently supports input-pair Vth mismatch directly. This
    budget extends the risk model to latch/tail/precharge using conservative
    weighting factors so the WiCkeD report exposes second-order contributors
    instead of hiding them. Values are input-referred mV sigma contributions.
    """
    p = _full(params)
    weights = {"input": math.sqrt(2.0), "ncc": 0.35, "pcc": 0.30, "tail": 0.18, "pre": 0.08}
    items = []
    total2 = 0.0
    for k in DEV_KEYS:
        d = p["devices"][k]
        area = max(d["w_um"] * (d["l_nm"] / 1000.0) * d["m"], 1e-12)
        sigma = p["avt_mv_um"] / math.sqrt(area)
        contrib = weights[k] * sigma
        total2 += contrib * contrib
        items.append({"device": k, "area_um2": round(area, 4), "sigma_vth_mv": round(sigma, 4),
                      "input_referred_sigma_mv": round(contrib, 4), "weight": weights[k]})
    items.sort(key=lambda x: x["input_referred_sigma_mv"], reverse=True)
    return {"total_sigma_mv": round(math.sqrt(total2), 4), "dominant": items[0], "contributors": items,
            "note": "input pair is simulated directly; other groups are weighted analytic mismatch contributors"}


def importance_sampling_yield(params, targets=None, n=24, shift_beta=None, seed=31):
    """Shifted high-sigma Monte Carlo around the nearest WCD point.

    This is a lightweight BOIS/importance-sampling inspired estimator: find the
    WCD-limiting mechanism, shift sampling toward that failure region, evaluate
    SPICE at the shifted PVT/mismatch points, then unbias with the Gaussian
    likelihood ratio p(x)/q(x). It is intentionally small enough for interactive
    use and reports raw failures plus weighted failure probability.
    """
    p, t = _full(params), _targets(targets)
    rng = random.Random(seed)
    wcd0 = worst_case_distance(p, t, n_samples=max(6, min(18, int(n))), seed=seed)
    beta = float(shift_beta if shift_beta is not None else min(max(wcd0["beta_sigma"], 1.0), 4.0))
    direction = [0.0, 0.0, 0.0]
    mech = wcd0["limiting_mechanism"]
    if mech.get("metric") == "decision_time_ps" and mech.get("sample"):
        z = mech["sample"].get("z") or [1.0, 0.0, 0.0]
        norm = math.sqrt(sum(v * v for v in z)) or 1.0
        direction = [v / norm for v in z]
    elif mech.get("metric") == "offset_sigma_mv":
        # mismatch axis: represented separately by an offset sample, no PVT shift.
        direction = [0.0, 0.0, 0.0]
    mu = [beta * v for v in direction]
    base_vdd = float(p.get("vdd", run_sim.DEFAULT_PARAMS["vdd"]))
    mb = mismatch_budget(p)
    sig_off_v = mb["total_sigma_mv"] / 1000.0

    def one(_):
        z = [rng.gauss(mu[i], 1.0) for i in range(3)]
        off = rng.gauss(0.0, sig_off_v)
        cfg = {**p,
               "pskew": 0.03 * run_sim.skew_scale(p) * _clip(z[0], -4.0, 4.0),
               "vdd": round(_clip(base_vdd * (1.0 - 0.05 * z[1]), 0.75 * base_vdd, 1.25 * base_vdd), 4),
               "temp": round(_clip(27.0 + 45.0 * z[2], -40.0, 125.0), 2)}
        out = run_sim._run(run_sim.gen_netlist(cfg, vdiff=0.05, dvth1=off / 2.0, dvth2=-off / 2.0))
        dec = run_sim._parse(out, "tdec")
        fdiff = run_sim._parse(out, "fdiff")
        iavg = run_sim._parse(out, "iavg")
        dec_ps = dec * 1e12 if dec else None
        functional = dec_ps is not None and fdiff is not None and abs(fdiff) > 0.7 * cfg["vdd"]
        fail = (not functional) or (dec_ps is not None and dec_ps > t["decision_time_ps"]) or abs(off * 1000.0) > t["offset_sigma_mv"]
        # likelihood ratio for N(0,I) / N(mu,I) = exp(-mu·z + |mu|²/2)
        lr = math.exp(-sum(mu[i] * z[i] for i in range(3)) + 0.5 * sum(m * m for m in mu))
        return {"z": [round(v, 3) for v in z], "offset_mv": round(off * 1000.0, 4),
                "decision_time_ps": round(dec_ps, 3) if dec_ps else None,
                "power_uw": round(abs(iavg) * cfg["vdd"] * 1e6, 3) if iavg is not None else None,
                "functional": bool(functional), "fail": bool(fail), "weight": lr,
                "vdd": cfg["vdd"], "temp": cfg["temp"], "pskew": round(cfg["pskew"], 4)}

    samples = _pmap(one, range(max(1, int(n))))
    pf = sum(s["weight"] for s in samples if s["fail"]) / len(samples)
    pf = max(0.0, min(1.0, pf))
    return {"n": len(samples), "shift_mu": [round(x, 3) for x in mu], "shift_beta": round(beta, 3),
            "weighted_failure_prob": round(pf, 8), "estimated_yield_pct": round(100.0 * (1.0 - pf), 6),
            "raw_failures": sum(1 for s in samples if s["fail"]), "wcd_seed": wcd0,
            "mismatch_budget": mb, "samples": samples[:80],
            "note": "importance-sampling proxy with Gaussian likelihood reweighting; not sign-off high-sigma"}


def robust_optimize(params=None, targets=None, rounds=3, seed=47):
    """Yield-aware coordinate search using WCO/WCD feedback.

    Each round evaluates a compact set of physically meaningful sizing moves and
    keeps the candidate with the best spec-aware score. This complements DE with
    a deterministic, explainable WiCkeD-style design-centering pass.
    """
    p, t = _full(params), _targets(targets)
    rng = random.Random(seed)
    hist = []

    def score(pp):
        n = nominal_verdict(pp, t)["nominal"]
        wco = wco_operating(pp, t)["worst"]
        wcd = worst_case_distance(pp, t, n_samples=6, seed=rng.randrange(10**9))
        dec = wco.get("decision_time_ps") or n.get("decision_time_ps") or 1e6
        pw = n.get("power_uw") or 1e6
        penalty = 0.0
        penalty += max(0.0, dec / t["decision_time_ps"] - 1.0) * 5000.0
        penalty += max(0.0, pw / t["power_uw"] - 1.0) * 500.0
        penalty += max(0.0, t["yield_pct"] - wcd["estimated_yield_pct"]) * 25.0
        if wco.get("any_nonfunctional") or not n.get("functional"):
            penalty += 1e5
        return {"score": round(pw + total_width_um(pp) * 0.15 + penalty, 6), "nominal": n, "wco": wco,
                "wcd": {"beta_sigma": wcd["beta_sigma"], "estimated_yield_pct": wcd["estimated_yield_pct"],
                         "limiting": wcd["limiting_mechanism"]["metric"]},
                "total_width_um": total_width_um(pp), "params": pp}

    cur = p
    for r in range(max(1, int(rounds))):
        moves = [("hold", cur)]
        for k in ("input", "tail", "ncc", "pcc", "pre"):
            moves.append((f"{k}+", _scale_width(cur, k, 1.18)))
            moves.append((f"{k}-", _scale_width(cur, k, 0.92)))
        evals = _pmap(lambda mv: {"move": mv[0], **score(mv[1])}, moves)
        best = min(evals, key=lambda x: x["score"])
        cur = best["params"]
        hist.append({"round": r, "selected": best["move"], "score": best["score"],
                     "nominal": best["nominal"], "wco": best["wco"], "wcd": best["wcd"],
                     "total_width_um": best["total_width_um"],
                     "candidates": [{k: e[k] for k in ("move", "score", "total_width_um", "wcd")} for e in evals]})
    final = score(cur)
    ok = (not final["wco"].get("any_nonfunctional") and
          final["wco"].get("decision_time_ps") is not None and final["wco"]["decision_time_ps"] <= t["decision_time_ps"] and
          final["nominal"].get("power_uw") is not None and final["nominal"]["power_uw"] <= t["power_uw"] and
          final["wcd"]["estimated_yield_pct"] >= t["yield_pct"])
    return {"success": bool(ok), "history": hist, "final": final, "final_params": cur, "targets": t}


def parameter_screening(params, targets=None, delta=0.15):
    """Rank design parameters by their influence on each performance metric.

    This mirrors WiCkeD's parameter-screening feature: for each device width,
    perturb ±delta and measure the normalized change in decision-time, power, and
    offset. Returns a ranked table so the designer knows which parameters to
    focus on during manual or automated sizing.
    """
    p, t = _full(params), _targets(targets)
    base = nominal_verdict(p, t)["nominal"]
    base_off = predicted_offset_sigma_mv(p)
    base_vals = {"decision_time_ps": base.get("decision_time_ps"),
                 "power_uw": base.get("power_uw"),
                 "offset_sigma_mv": base_off}

    def eval_one(args):
        k, f = args
        pp = _scale_width(p, k, f)
        n = run_sim.run_sim(pp, do_offset=False)["nominal"]
        return {"key": k, "factor": f,
                "decision_time_ps": n.get("decision_time_ps"),
                "power_uw": n.get("power_uw"),
                "offset_sigma_mv": predicted_offset_sigma_mv(pp),
                "functional": bool(n.get("functional"))}

    jobs = [(k, 1.0 + delta) for k in DEV_KEYS] + [(k, 1.0 - delta) for k in DEV_KEYS]
    results = _pmap(eval_one, jobs)
    by = {k: {"up": None, "down": None} for k in DEV_KEYS}
    for r in results:
        by[r["key"]]["up" if r["factor"] > 1 else "down"] = r

    metrics = ["decision_time_ps", "power_uw", "offset_sigma_mv"]
    rankings = {m: [] for m in metrics}
    for k in DEV_KEYS:
        up, dn = by[k]["up"], by[k]["down"]
        for m in metrics:
            if up and dn and up[m] is not None and dn[m] is not None and base_vals[m]:
                sensitivity = abs(up[m] - dn[m]) / (2 * delta * base_vals[m])
                rankings[m].append({"key": k, "sensitivity": round(sensitivity, 5),
                                    "base": round(base_vals[m], 4) if base_vals[m] else None,
                                    "up": round(up[m], 4), "down": round(dn[m], 4)})
    for m in metrics:
        rankings[m].sort(key=lambda x: x["sensitivity"], reverse=True)
    return {"base": base_vals, "delta_pct": round(delta * 100, 2),
            "rankings": rankings,
            "note": "Normalized OAT sensitivity ranking; high sensitivity = prioritize for sizing"}


def yield_sweep(params, targets=None, n_points=7, seed=53):
    """Yield vs global process variation — WiCkeD yield-plot style.

    Sweeps a global process skew factor from SS-equivalent to FF-equivalent and
    runs a compact MC at each point to estimate the yield. This reveals how
    yield degrades toward the slow corner and whether the design is centered.
    """
    p, t = _full(params), _targets(targets)
    rng = random.Random(seed)
    _sk6 = 0.06 * run_sim.skew_scale(p)   # gaa2nm: 스윕 범위도 절반
    skews = [round(-_sk6 + 2 * _sk6 * i / max(1, n_points - 1), 4) for i in range(n_points)]
    mb = mismatch_budget(p)
    sig_off_v = mb["total_sigma_mv"] / 1000.0

    def one_point(skw):
        passes = 0
        n = 8
        samples = []
        for _ in range(n):
            off = rng.gauss(0.0, sig_off_v)
            cfg = {**p, "pskew": skw, "temp": rng.choice([-40, 27, 125]),
                   "vdd": round(float(p.get("vdd", 1.0)) * rng.uniform(0.9, 1.1), 3)}
            out = run_sim._run(run_sim.gen_netlist(cfg, vdiff=0.05, dvth1=off / 2.0, dvth2=-off / 2.0))
            dec = run_sim._parse(out, "tdec")
            fdiff = run_sim._parse(out, "fdiff")
            dec_ps = dec * 1e12 if dec else None
            fn = dec_ps is not None and fdiff is not None and abs(fdiff) > 0.7 * cfg["vdd"]
            ok = fn and dec_ps is not None and dec_ps <= t["decision_time_ps"] and abs(off * 1000.0) <= t["offset_sigma_mv"]
            if ok:
                passes += 1
            samples.append({"dec_ps": round(dec_ps, 2) if dec_ps else None, "off_mv": round(off * 1000, 3), "pass": ok})
        return {"pskew": skw, "yield_pct": round(100.0 * passes / n, 1), "n": n, "pass": passes, "samples": samples}

    points = _pmap(one_point, skews)
    return {"points": points, "n_mc_per_point": 8, "targets": t,
            "note": "Compact MC per process skew point; yield-plot proxy"}


def yop_optimize(params=None, targets=None, iterations=3, seed=71):
    """YOP-like yield optimization: maximize WCD beta by coordinate search.

    Each iteration tries width moves on all device groups and selects the one
    that most improves the WCD beta sigma (the yield proxy). Falls back to
    nominal power score if WCD doesn't differentiate. This is a simplified
    version of WiCkeD's YOP design-centering, using beta as the objective.
    """
    p, t = _full(params), _targets(targets)
    rng = random.Random(seed)
    hist = []
    cur = p
    for it in range(max(1, int(iterations))):
        wcd_cur = worst_case_distance(cur, t, n_samples=4, seed=rng.randrange(10**9))
        beta_cur = wcd_cur["beta_sigma"]
        moves = [("hold", cur, beta_cur)]
        for k in DEV_KEYS:
            for f in (1.15, 0.90):
                cand = _scale_width(cur, k, f)
                wcd_c = worst_case_distance(cand, t, n_samples=4, seed=rng.randrange(10**9))
                moves.append((f"{k}{'+' if f > 1 else '-'}", cand, wcd_c["beta_sigma"]))
        best = max(moves, key=lambda x: x[2])
        cur = best[1]
        hist.append({"iter": it, "selected": best[0], "beta_before": round(beta_cur, 4),
                     "beta_after": round(best[2], 4), "total_width_um": total_width_um(cur),
                     "candidates": [{"move": m[0], "beta": round(m[2], 4)} for m in moves]})
        if best[0] == "hold" and it > 0:
            break
    final_wcd = worst_case_distance(cur, t, n_samples=8, seed=seed)
    return {"history": hist, "final_beta_sigma": final_wcd["beta_sigma"],
            "final_yield_pct": final_wcd["estimated_yield_pct"],
            "final_params": cur, "final_wcd": final_wcd, "targets": t}


def postlayout_wcd(params, targets=None, n_samples=12, seed=91):
    """WCD re-evaluation with layout-extracted parasitics.

    Uses the existing layout.extract_parasitics() to add layout-derived node
    capacitance, then re-runs the WCD analysis on the parasitic-loaded netlist.
    This mirrors WiCkeD's post-layout verification capability.
    """
    import layout
    p, t = _full(params), _targets(targets)
    pc = layout.extract_parasitics(p)
    p_pl = {**p, "parasitic": True, "par_caps": pc}
    wcd_pre = worst_case_distance(p, t, n_samples=n_samples, seed=seed)
    wcd_post = worst_case_distance(p_pl, t, n_samples=n_samples, seed=seed)
    nom_pre = run_sim.run_sim(p, do_offset=False)["nominal"]
    nom_post = run_sim.run_sim(p_pl, do_offset=False)["nominal"]
    return {"pre_layout": {"nominal": nom_pre, "wcd": wcd_pre},
            "post_layout": {"nominal": nom_post, "wcd": wcd_post},
            "par_caps": pc,
            "decision_delta_ps": round((nom_post.get("decision_time_ps") or 0) - (nom_pre.get("decision_time_ps") or 0), 3),
            "beta_delta": round(wcd_post["beta_sigma"] - wcd_pre["beta_sigma"], 4),
            "note": "layout parasitic proxy extraction → WCD re-evaluation"}


def worst_case_corners(params, targets=None):
    """Extract and rank the worst-case PVT corners from the full 27-corner grid.

    Returns the top-N most-violating corners (by decision margin) so the
    designer knows exactly which PVT conditions are limiting. This is WiCkeD's
    worst-case corner diagnosis feature.
    """
    wco = wco_operating(params, targets)
    corners = wco["corners"]
    t = wco["targets"]
    ranked = sorted(corners, key=lambda c: c.get("decision_margin") or 1e6)
    failing = [c for c in ranked if c.get("decision_margin") is not None and c["decision_margin"] < 0]
    near = [c for c in ranked if c.get("decision_margin") is not None and 0 <= c["decision_margin"] < 0.15]
    return {"worst_5": ranked[:5], "failing_corners": failing, "near_margin_corners": near,
            "total_corners": len(corners), "n_failing": len(failing),
            "worst": wco["worst"], "targets": t,
            "note": "Ranked by decision-time margin; negative = spec violation"}


def wicked_flow(params=None, targets=None, dno_iterations=4, wcd_samples=24, seed=19, importance_samples=8):
    """End-to-end WiCkeD-like flow: FEO/DNO -> WCO -> WCD/yield report."""
    p, t = _full(params), _targets(targets)
    stages = []
    initial = nominal_verdict(p, t)
    stages.append({"name": "FEO feasibility check", "ok": bool(initial["nominal"].get("functional")),
                   "detail": initial["nominal"], "margins": initial["margins"]})
    dno = dno_refine(p, t, iterations=dno_iterations)
    fin = dno["final_params"]
    stages.append({"name": "DNO sensitivity-guided nominal refinement", "ok": bool(dno["success"]),
                   "detail": dno["final"]["nominal"], "margins": dno["final"]["margins"]})
    rob = robust_refine(fin, t, iterations=2)
    fin = rob["final_params"]
    rob_ok = bool(rob["history"] and rob["history"][-1]["ok"])
    stages.append({"name": "WCO-in-loop robust refinement", "ok": rob_ok,
                   "detail": rob["history"][-1] if rob["history"] else rob["final"]["nominal"]})
    wco = wco_operating(fin, t)
    wco_ok = (not wco["worst"]["any_nonfunctional"] and
              wco["worst"]["decision_time_ps"] is not None and
              wco["worst"]["decision_time_ps"] <= t["decision_time_ps"])
    stages.append({"name": "WCO PVT worst-case operation", "ok": bool(wco_ok), "detail": wco["worst"]})
    wcd = worst_case_distance(fin, t, n_samples=wcd_samples, seed=seed)
    yield_ok = wcd["estimated_yield_pct"] >= float(t.get("yield_pct", 0.0))
    stages.append({"name": "WCD high-sigma/yield proxy", "ok": bool(yield_ok),
                   "detail": {"beta_sigma": wcd["beta_sigma"], "estimated_yield_pct": wcd["estimated_yield_pct"],
                              "limiting": wcd["limiting_mechanism"]["metric"]}})
    mb = mismatch_budget(fin)
    stages.append({"name": "Full-device mismatch budget", "ok": mb["total_sigma_mv"] <= t["offset_sigma_mv"],
                   "detail": {"total_sigma_mv": mb["total_sigma_mv"], "dominant": mb["dominant"]}})
    imp = None
    if int(importance_samples or 0) > 0:
        imp = importance_sampling_yield(fin, t, n=int(importance_samples), seed=seed + 1)
        stages.append({"name": "Importance-sampled high-sigma check", "ok": imp["estimated_yield_pct"] >= t["yield_pct"],
                       "detail": {"estimated_yield_pct": imp["estimated_yield_pct"],
                                  "raw_failures": imp["raw_failures"], "shift_beta": imp["shift_beta"]}})
    scr = parameter_screening(fin, t, delta=0.12)
    stages.append({"name": "Parameter screening", "ok": True,
                   "detail": {m: scr["rankings"][m][:2] for m in scr["rankings"]}})
    wcc = worst_case_corners(fin, t)
    stages.append({"name": "Worst-case corner extraction", "ok": wcc["n_failing"] == 0,
                   "detail": {"n_failing": wcc["n_failing"], "worst_5": wcc["worst_5"]}})
    plw = postlayout_wcd(fin, t, n_samples=4, seed=seed + 2)
    pl_ok = plw["post_layout"]["wcd"]["beta_sigma"] >= 0
    stages.append({"name": "Post-layout WCD re-evaluation", "ok": bool(pl_ok),
                   "detail": {"beta_pre": plw["pre_layout"]["wcd"]["beta_sigma"],
                              "beta_post": plw["post_layout"]["wcd"]["beta_sigma"],
                              "decision_delta_ps": plw["decision_delta_ps"]}})
    return {"stages": stages, "overall": all(s["ok"] for s in stages),
            "initial": initial, "dno": dno, "robust_refine": rob, "wco": wco, "wcd": wcd,
            "mismatch_budget": mb, "importance_sampling": imp,
            "parameter_screening": scr, "worst_case_corners": wcc, "postlayout_wcd": plw,
            "final_params": fin, "targets": t,
            "sources_applied": [
                "FEO/DNO/GNO/YOP/WCO/WCD public WiCkeD descriptions",
                "WCO corner+continuous operating parameter guidance",
                "High-sigma rare-event motivation: MC is infeasible for rare failures; use WCD/IS-style proxies",
            ]}


if __name__ == "__main__":
    import json
    import sys
    body = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    print(json.dumps(wicked_flow(body.get("params", body), body.get("targets"),
                                 dno_iterations=int(body.get("dno_iterations", 3)),
                                 wcd_samples=int(body.get("wcd_samples", 12)),
                                 importance_samples=int(body.get("importance_samples", 4))), indent=2))

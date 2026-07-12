#!/usr/bin/env python3
"""WiCkeD-inspired robustness analysis and sizing flow for the ring VCO backend.

Ports the comparator methodology in wicked.py to the VCO metrics: oscillation
(functional), frequency accuracy (band around a target f), power, and — for the
cross-coupled "xcpl" topology — start-up robustness against mismatch (the
cross-coupled P1 pair can latch a stage if mismatch/PVT weakens the tail
current). Applied analyses:

* Nominal verdict with normalized spec margins (FEO-style feasibility).
* Parameter screening — OAT width sensitivity ranking per device group.
* WCO worst-case operation over the 27 PVT corners + worst-corner extraction.
* WCD worst-case distance (sigma robustness proxy) over pskew/VDD/temp.
* Per-device Vth mismatch Monte Carlo (the comparator's MC-offset analog):
  sigma_f/f spread + oscillation-failure count under Pelgrom mismatch.
* Yield sweep over global process skew (yield-plot style).
* DNO sensitivity-guided nominal sizing refinement (center f, trim power).
* YOP-like design centering that maximizes the WCD beta.
* Post-layout WCD re-evaluation through the layout parasitic proxy.
* wicked_flow chaining all of the above into a staged sign-off report.

Same ground rules as wicked.py: stdlib + the existing ngspice wrappers only,
and every estimate is an inspectable proxy, not commercial WiCkeD.
"""
import copy
import math
import random
import re
from concurrent.futures import ThreadPoolExecutor

import run_sim
import vco_sim

DEFAULT_TARGETS = {
    "f_ghz": 1.5,        # target oscillation frequency
    "f_tol_pct": 15.0,   # acceptable band around the target
    "power_uw": 1500.0,
    "yield_pct": 99.0,
}
_WORKERS = max(2, min(8, __import__("os").cpu_count() or 4))


def _pmap(fn, items):
    items = list(items)
    if len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        return list(ex.map(fn, items))


def _full(params):
    return vco_sim._full(params)


def _targets(targets):
    t = dict(DEFAULT_TARGETS)
    t.update(targets or {})
    return t


def dev_keys(params):
    """Sizing variables: the starve/inverter widths always; the cross-coupled
    and reset PMOS only when the xcpl topology is active."""
    p = _full(params)
    keys = list(vco_sim.DEV_KEYS)
    if p.get("topology", "starved") == "xcpl":
        keys += ["xcplp", "rstp"]
    return keys


def _band(t):
    f0, tol = float(t["f_ghz"]), float(t["f_tol_pct"]) / 100.0
    return f0 * (1.0 - tol), f0 * (1.0 + tol)


def _margin_le(value, limit):
    if value is None or limit in (None, 0):
        return None
    return (float(limit) - float(value)) / float(limit)


def _f_margin(f, t):
    """Normalized distance to the nearer band edge; positive inside the band."""
    if f is None:
        return None
    lo, hi = _band(t)
    half = 0.5 * (hi - lo)
    return round((half - abs(f - 0.5 * (lo + hi))) / half, 4) if half > 0 else None


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


def _scale_width(params, key, factor):
    p = copy.deepcopy(params)
    d = p["devices"][key]
    d["w_um"] = round(_clip(d["w_um"] * factor, 0.1, 80.0), 3)
    return p


def nominal_verdict(params, targets=None):
    """One nominal measurement -> normalized margins for the main specs."""
    p, t = _full(params), _targets(targets)
    m = vco_sim.measure_vco(p)
    margins = {
        "oscillates": 1.0 if m.get("oscillates") else -1.0,
        "f_band": _f_margin(m.get("f_osc_ghz"), t),
        "power_uw": _margin_le(m.get("power_uw"), t["power_uw"]),
    }
    return {"nominal": m, "margins": margins,
            "pass": all(v is not None and v >= 0 for v in margins.values()),
            "params": p, "targets": t}


def parameter_screening(params, targets=None, delta=0.15):
    """Rank device widths by influence on frequency and power (OAT ±delta).

    The VCO version of wicked.parameter_screening/sensitivity: tells the
    designer which width actually moves f or power (and which kills the
    oscillation — its slot reports functional=False)."""
    p, t = _full(params), _targets(targets)
    keys = dev_keys(p)
    base = vco_sim.measure_vco(p)
    base_vals = {"f_osc_ghz": base.get("f_osc_ghz"), "power_uw": base.get("power_uw")}

    def eval_one(args):
        k, f = args
        m = vco_sim.measure_vco(_scale_width(p, k, f))
        return {"key": k, "factor": f, "f_osc_ghz": m.get("f_osc_ghz"),
                "power_uw": m.get("power_uw"), "functional": bool(m.get("oscillates"))}

    jobs = [(k, 1.0 + delta) for k in keys] + [(k, 1.0 - delta) for k in keys]
    results = _pmap(eval_one, jobs)
    by = {k: {"up": None, "down": None} for k in keys}
    for r in results:
        by[r["key"]]["up" if r["factor"] > 1 else "down"] = r

    metrics = ["f_osc_ghz", "power_uw"]
    rankings = {m: [] for m in metrics}
    for k in keys:
        up, dn = by[k]["up"], by[k]["down"]
        for m in metrics:
            if up and dn and up[m] is not None and dn[m] is not None and base_vals[m]:
                s = abs(up[m] - dn[m]) / (2 * delta * base_vals[m])
                rankings[m].append({"key": k, "sensitivity": round(s, 5),
                                    "base": round(base_vals[m], 4),
                                    "up": round(up[m], 4), "down": round(dn[m], 4),
                                    "kills_osc": not (up["functional"] and dn["functional"])})
    for m in metrics:
        rankings[m].sort(key=lambda x: x["sensitivity"], reverse=True)
    return {"base": base_vals, "delta_pct": round(delta * 100, 2), "dev_keys": keys,
            "rankings": rankings,
            "note": "Normalized OAT width sensitivity; kills_osc flags a width move that stopped oscillation"}


def wco_operating(params, targets=None):
    """Worst-case operation over the 45 process/temperature/VDD corners (5 corners incl. SF/FS)."""
    p, t = _full(params), _targets(targets)
    base_vdd = float(p["vdd"])
    specs = [(lbl, ns, ps, temp, vf)
             for lbl, ns, ps in (("SS", 0.05, 0.05), ("TT", 0.0, 0.0), ("FF", -0.05, -0.05), ("SF", 0.05, -0.05), ("FS", -0.05, 0.05))
             for temp in (-40, 27, 125) for vf in (0.9, 1.0, 1.1)]

    def one(s):
        lbl, ns, ps, temp, vf = s
        m = vco_sim.measure_vco({**p, "nskew": ns, "pskew_p": ps, "temp": temp, "vdd": round(base_vdd * vf, 3)})
        return {"process": lbl, "temp": temp, "v_frac": vf, "vdd": round(base_vdd * vf, 3),
                "f_osc_ghz": m.get("f_osc_ghz"), "power_uw": m.get("power_uw"),
                "oscillates": bool(m.get("oscillates")),
                "f_margin": _f_margin(m.get("f_osc_ghz"), t),
                "power_margin": _margin_le(m.get("power_uw"), t["power_uw"])}

    corners = _pmap(one, specs)
    fs = [c["f_osc_ghz"] for c in corners if c["f_osc_ghz"] is not None]
    return {"corners": corners,
            "worst": {"f_min_ghz": min(fs, default=None), "f_max_ghz": max(fs, default=None),
                      "max_power_uw": max((c["power_uw"] for c in corners if c["power_uw"] is not None), default=None),
                      "any_nonosc": any(not c["oscillates"] for c in corners),
                      "min_f_margin": min((c["f_margin"] for c in corners if c["f_margin"] is not None), default=None)},
            "targets": t}


def worst_case_corners(params, targets=None):
    """Rank the PVT corners by frequency-band margin (negative = violation)."""
    wco = wco_operating(params, targets)
    ranked = sorted(wco["corners"], key=lambda c: (c["f_margin"] if c["f_margin"] is not None else -1e6)
                    if c["oscillates"] else -1e6)
    failing = [c for c in ranked if (not c["oscillates"]) or (c["f_margin"] is not None and c["f_margin"] < 0)]
    return {"worst_5": ranked[:5], "failing_corners": failing, "n_failing": len(failing),
            "total_corners": len(wco["corners"]), "worst": wco["worst"], "targets": wco["targets"],
            "note": "Ranked by f-band margin; non-oscillating corners rank worst"}


def worst_case_distance(params, targets=None, n_samples=24, seed=19):
    """Nearest-failure distance in sigma units over (pskew, VDD, temp).

    Failure = no oscillation, frequency outside the band, or power over
    target. When frequency is measurable the boundary crossing is linearly
    interpolated toward the band edge, exactly like the comparator's
    decision-time interpolation."""
    p, t = _full(params), _targets(targets)
    rng = random.Random(seed)
    nom = vco_sim.measure_vco(p)
    f_nom = nom.get("f_osc_ghz")
    lo, hi = _band(t)
    base_vdd = float(p["vdd"])
    samples = []
    for _ in range(max(1, int(n_samples))):
        z = [_clip(rng.gauss(0, 1), -3.5, 3.5) for _ in range(3)]
        cfg = {**p, "pskew": 0.03 * z[0],
               "vdd": round(_clip(base_vdd * (1.0 - 0.05 * z[1]), 0.75 * base_vdd, 1.25 * base_vdd), 4),
               "temp": round(_clip(27.0 + 45.0 * z[2], -40.0, 125.0), 2)}
        samples.append((z, cfg))

    def one(s):
        z, cfg = s
        m = vco_sim.measure_vco(cfg)
        f = m.get("f_osc_ghz")
        dist = math.sqrt(sum(v * v for v in z))
        out_of_band = f is not None and (f < lo or f > hi)
        failed = (not m.get("oscillates")) or f is None or out_of_band or \
                 (m.get("power_uw") is not None and m["power_uw"] > t["power_uw"])
        beta = None
        if failed:
            beta = dist
            if out_of_band and f_nom is not None and f is not None and f != f_nom:
                edge = lo if f < lo else hi
                frac = (edge - f_nom) / (f - f_nom)
                if 0.0 <= frac <= 1.0:
                    beta = max(0.0, dist * frac)
        return {"z": [round(v, 3) for v in z], "distance": round(dist, 3),
                "beta_to_failure": round(beta, 3) if beta is not None else None,
                "f_osc_ghz": f, "power_uw": m.get("power_uw"),
                "oscillates": bool(m.get("oscillates")), "failed": bool(failed),
                "vdd": cfg["vdd"], "temp": cfg["temp"], "pskew": round(cfg["pskew"], 4)}

    sim = _pmap(one, samples)
    betas = [s["beta_to_failure"] for s in sim if s["beta_to_failure"] is not None]
    beta = min(betas) if betas else 3.5   # no failure seen inside the sampled ball
    nearest = min((s for s in sim if s["beta_to_failure"] is not None),
                  key=lambda s: s["beta_to_failure"], default=None)
    yield_pct = 100.0 * 0.5 * (1.0 + math.erf(beta / math.sqrt(2.0)))
    return {"beta_sigma": round(beta, 3), "estimated_yield_pct": round(yield_pct, 4),
            "nearest_failure": nearest, "nominal": nom, "samples": sim, "targets": t,
            "note": "WCD proxy over pskew/VDD/temp; beta clamps at 3.5 when no sampled failure"}


_DELVTO_RE = re.compile(r"W=([\d.]+)u L=(\d+)n M=(\d+) delvto=\{(dvtn|dvtp)\}")


def _netlist_with_mismatch(p, rng, tstop_ns=18.0):
    """Generated netlist with an independent Pelgrom Vth draw per device line.

    This is the VCO analog of the comparator's Monte-Carlo offset injection:
    every MOSFET (both rails, bias mirror, cross-couple, reset) gets its own
    delvto sample sigma = AVT/sqrt(W*L*M), instead of the global corner skew."""
    avt = float(p.get("avt_mv_um", run_sim.DEFAULT_PARAMS.get("avt_mv_um", 2.0)))
    pskew = float(p.get("pskew", 0.0))   # substitution drops the {dvtn}/{dvtp}
    nl = vco_sim.gen_vco_netlist(p, tstop_ns=tstop_ns)   # refs, so re-add the corner skew here

    def sub(mt):
        w, l_nm, m = float(mt.group(1)), int(mt.group(2)), int(mt.group(3))
        sigma_v = (avt / math.sqrt(max(w * (l_nm / 1000.0) * m, 1e-12))) / 1000.0
        base = pskew if mt.group(4) == "dvtn" else -pskew
        return f"W={mt.group(1)}u L={mt.group(2)}n M={mt.group(3)} delvto={base + rng.gauss(0.0, sigma_v):.6g}"

    return _DELVTO_RE.sub(sub, nl)


def mismatch_mc(params, n=16, seed=7):
    """Per-device Vth mismatch Monte Carlo: sigma_f/f and start-up failures.

    For the xcpl topology this is the key robustness check — mismatch that
    strengthens P1 against a weakened tail can latch a stage (oscillates
    False), which no global-corner analysis reveals."""
    p = _full(params)
    rng = random.Random(seed)
    vdd = p["vdd"]
    nets = [_netlist_with_mismatch(p, rng) for _ in range(max(2, int(n)))]

    def one(nl):
        out = run_sim._run(nl)
        per = run_sim._parse(out, "per")
        vpp = run_sim._parse(out, "vpp")
        iavg = run_sim._parse(out, "iavg")
        osc = per is not None and per > 0 and vpp is not None and vpp > 0.4 * vdd
        return {"f_osc_ghz": round(5.0 / per / 1e9, 4) if (osc and per) else None,
                "power_uw": round(abs(iavg) * vdd * 1e6, 3) if iavg is not None else None,
                "oscillates": bool(osc)}

    samples = _pmap(one, nets)
    fs = [s["f_osc_ghz"] for s in samples if s["f_osc_ghz"] is not None]
    fails = sum(1 for s in samples if not s["oscillates"])
    mean_f = sum(fs) / len(fs) if fs else None
    sigma_f = (math.sqrt(sum((f - mean_f) ** 2 for f in fs) / len(fs)) if fs and len(fs) > 1 else None)
    return {"n": len(samples), "mean_f_ghz": round(mean_f, 4) if mean_f else None,
            "sigma_f_mhz": round(sigma_f * 1e3, 3) if sigma_f is not None else None,
            "sigma_f_pct": round(100.0 * sigma_f / mean_f, 3) if (sigma_f is not None and mean_f) else None,
            "osc_failures": fails, "startup_yield_pct": round(100.0 * (1 - fails / len(samples)), 2),
            "samples": samples,
            "note": "independent Pelgrom delvto per MOSFET; osc_failures flags mismatch-induced latch-up/start-up loss"}


def yield_sweep(params, targets=None, n_points=7, n_mc=6, seed=53):
    """Yield vs global process skew, compact mismatch MC at each point."""
    p, t = _full(params), _targets(targets)
    rng = random.Random(seed)
    lo, hi = _band(t)
    vdd0 = float(p["vdd"])
    skews = [round(-0.06 + 0.12 * i / max(1, n_points - 1), 4) for i in range(n_points)]

    def one_point(skw):
        passes, samples = 0, []
        for _ in range(n_mc):
            cfg = {**p, "pskew": skw, "temp": rng.choice([-40, 27, 125]),
                   "vdd": round(vdd0 * rng.uniform(0.9, 1.1), 3)}
            nl = _netlist_with_mismatch(cfg, rng)
            out = run_sim._run(nl)
            per = run_sim._parse(out, "per")
            vpp = run_sim._parse(out, "vpp")
            f = 5.0 / per / 1e9 if (per and per > 0) else None
            osc = f is not None and vpp is not None and vpp > 0.4 * cfg["vdd"]
            ok = osc and lo <= f <= hi
            passes += 1 if ok else 0
            samples.append({"f_ghz": round(f, 4) if f else None, "pass": bool(ok)})
        return {"pskew": skw, "yield_pct": round(100.0 * passes / n_mc, 1), "n": n_mc, "samples": samples}

    points = _pmap(one_point, skews)
    return {"points": points, "n_mc_per_point": n_mc, "targets": t,
            "note": "mismatch+PVT MC per process-skew point; pass = oscillates inside the f band"}


def dno_refine(params, targets=None, iterations=4):
    """Sensitivity-guided nominal sizing loop (WiCkeD DNO style).

    Feasibility first (restore oscillation — for xcpl weaken P1 and strengthen
    the inverters), then center the frequency using the starve widths, then
    trim power with the width that moves f least."""
    p, t = _full(params), _targets(targets)
    lo, hi = _band(t)
    history = []
    for it in range(max(1, int(iterations))):
        v = nominal_verdict(p, t)
        m = v["nominal"]
        action = "hold"
        if not m.get("oscillates"):
            if p.get("topology", "starved") == "xcpl":
                p = _scale_width(p, "xcplp", 0.75)
                for k in ("invp", "invn"):
                    p = _scale_width(p, k, 1.15)
                action = "feasibility: weaken cross-coupled P1, strengthen inverters"
            else:
                for k in ("invp", "invn"):
                    p = _scale_width(p, k, 1.2)
                action = "feasibility: strengthen inverters"
        elif m["f_osc_ghz"] < lo:
            for k in ("starvep", "starven"):
                p = _scale_width(p, k, 1.18)
            action = "DNO: widen starve devices to raise f"
        elif m["f_osc_ghz"] > hi:
            for k in ("starvep", "starven"):
                p = _scale_width(p, k, 0.88)
            action = "DNO: narrow starve devices to lower f"
        elif m.get("power_uw") is not None and m["power_uw"] > t["power_uw"]:
            r = parameter_screening(p, t, delta=0.10)["rankings"]
            fsens = {x["key"]: x["sensitivity"] for x in r["f_osc_ghz"]}
            # trim a width that actually saves power, disturbing f as little as
            # possible (e.g. the xcpl reset PMOS is off while oscillating — its
            # power sensitivity ~0, so it must never be the trim target)
            eff = [x for x in r["power_uw"] if not x["kills_osc"] and x["sensitivity"] >= 0.05]
            key = (min(eff, key=lambda x: fsens.get(x["key"], 1e9))["key"] if eff
                   else max(r["power_uw"], key=lambda x: x["sensitivity"])["key"])
            p = _scale_width(p, key, 0.90)
            action = f"DNO: trim {key} to reduce power"
        history.append({"iter": it, "action": action, "nominal": m,
                        "devices": copy.deepcopy(p["devices"])})
        if action == "hold":
            break
    final = nominal_verdict(p, t)
    return {"initial_params": _full(params), "final_params": p, "history": history,
            "final": final, "success": final["pass"]}


def yop_optimize(params=None, targets=None, iterations=3, seed=71):
    """YOP-like design centering: coordinate search that maximizes WCD beta."""
    p, t = _full(params), _targets(targets)
    rng = random.Random(seed)
    hist = []
    cur = p
    keys = dev_keys(p)
    for it in range(max(1, int(iterations))):
        beta_cur = worst_case_distance(cur, t, n_samples=4, seed=rng.randrange(10**9))["beta_sigma"]
        moves = [("hold", cur, beta_cur)]
        for k in keys:
            for f in (1.15, 0.90):
                cand = _scale_width(cur, k, f)
                b = worst_case_distance(cand, t, n_samples=4, seed=rng.randrange(10**9))["beta_sigma"]
                moves.append((f"{k}{'+' if f > 1 else '-'}", cand, b))
        best = max(moves, key=lambda x: x[2])
        cur = best[1]
        hist.append({"iter": it, "selected": best[0], "beta_before": round(beta_cur, 4),
                     "beta_after": round(best[2], 4),
                     "candidates": [{"move": m[0], "beta": round(m[2], 4)} for m in moves]})
        if best[0] == "hold" and it > 0:
            break
    final = worst_case_distance(cur, t, n_samples=8, seed=seed)
    return {"history": hist, "final_beta_sigma": final["beta_sigma"],
            "final_yield_pct": final["estimated_yield_pct"], "final_params": cur,
            "final_wcd": final, "targets": t}


def postlayout_wcd(params, targets=None, n_samples=8, seed=91):
    """WCD re-evaluation with the layout-extracted node capacitance added."""
    import layout
    p, t = _full(params), _targets(targets)
    pc = layout.extract_vco_parasitics(p)
    p_pl = {**p, "cload_ff": p["cload_ff"] + pc["c_node_ff"]}
    pre = worst_case_distance(p, t, n_samples=n_samples, seed=seed)
    post = worst_case_distance(p_pl, t, n_samples=n_samples, seed=seed)
    return {"pre_layout": {"nominal": pre["nominal"], "beta_sigma": pre["beta_sigma"]},
            "post_layout": {"nominal": post["nominal"], "beta_sigma": post["beta_sigma"]},
            "par_caps": pc,
            "f_delta_ghz": round((post["nominal"].get("f_osc_ghz") or 0) - (pre["nominal"].get("f_osc_ghz") or 0), 4),
            "beta_delta": round(post["beta_sigma"] - pre["beta_sigma"], 4),
            "note": "layout parasitic proxy -> cload increase -> WCD re-evaluation"}


def wicked_flow(params=None, targets=None, dno_iterations=4, wcd_samples=16, mc_samples=8, seed=19):
    """End-to-end VCO flow: FEO -> DNO -> WCO -> WCD -> mismatch MC -> report."""
    p, t = _full(params), _targets(targets)
    stages = []
    initial = nominal_verdict(p, t)
    stages.append({"name": "FEO feasibility check", "ok": bool(initial["nominal"].get("oscillates")),
                   "detail": initial["nominal"], "margins": initial["margins"]})
    dno = dno_refine(p, t, iterations=dno_iterations)
    fin = dno["final_params"]
    stages.append({"name": "DNO sensitivity-guided nominal refinement", "ok": bool(dno["success"]),
                   "detail": dno["final"]["nominal"], "margins": dno["final"]["margins"]})
    wco = wco_operating(fin, t)
    wco_ok = (not wco["worst"]["any_nonosc"]) and \
             (wco["worst"]["min_f_margin"] is not None and wco["worst"]["min_f_margin"] >= 0)
    stages.append({"name": "WCO PVT worst-case operation", "ok": bool(wco_ok), "detail": wco["worst"]})
    wcd = worst_case_distance(fin, t, n_samples=wcd_samples, seed=seed)
    yield_ok = wcd["estimated_yield_pct"] >= float(t.get("yield_pct", 0.0))
    stages.append({"name": "WCD sigma/yield proxy", "ok": bool(yield_ok),
                   "detail": {"beta_sigma": wcd["beta_sigma"],
                              "estimated_yield_pct": wcd["estimated_yield_pct"]}})
    mc = mismatch_mc(fin, n=mc_samples, seed=seed + 1)
    mc_ok = mc["osc_failures"] == 0
    stages.append({"name": "Per-device mismatch Monte Carlo", "ok": bool(mc_ok),
                   "detail": {"sigma_f_pct": mc["sigma_f_pct"], "osc_failures": mc["osc_failures"],
                              "startup_yield_pct": mc["startup_yield_pct"]}})
    scr = parameter_screening(fin, t, delta=0.12)
    stages.append({"name": "Parameter screening", "ok": True,
                   "detail": {m: scr["rankings"][m][:2] for m in scr["rankings"]}})
    wcc = worst_case_corners(fin, t)
    stages.append({"name": "Worst-case corner extraction", "ok": wcc["n_failing"] == 0,
                   "detail": {"n_failing": wcc["n_failing"], "worst_5": wcc["worst_5"]}})
    plw = postlayout_wcd(fin, t, n_samples=4, seed=seed + 2)
    stages.append({"name": "Post-layout WCD re-evaluation", "ok": plw["post_layout"]["beta_sigma"] > 0,
                   "detail": {"beta_pre": plw["pre_layout"]["beta_sigma"],
                              "beta_post": plw["post_layout"]["beta_sigma"],
                              "f_delta_ghz": plw["f_delta_ghz"]}})
    return {"stages": stages, "overall": all(s["ok"] for s in stages),
            "initial": initial, "dno": dno, "wco": wco, "wcd": wcd,
            "mismatch_mc": mc, "parameter_screening": scr,
            "worst_case_corners": wcc, "postlayout_wcd": plw,
            "final_params": fin, "targets": t}


if __name__ == "__main__":
    import json
    import sys
    body = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    print(json.dumps(wicked_flow(body.get("params"), body.get("targets")), indent=2))

#!/usr/bin/env python3
"""
server.py -- dependency-free HTTP bridge exposing the StrongARM run_sim backend
to the web frontend. No fastapi/flask needed; uses the stdlib http.server.

Endpoints:
    GET  /api/health              -> {"ok": true, "ngspice": "<path>"}
    GET  /api/defaults            -> default params + P1 spec targets
    POST /api/simulate            -> body {params, do_offset} -> run_sim result

Run:  python3 server.py [port]     (default 8770)
The Vite dev server proxies /api to this port (see vite.config.ts).
"""
import copy
import json
import math
import mimetypes
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ngspice runs as a subprocess (releases the GIL), so independent evaluations
# parallelize for real. Cap workers so a big DE/PVT sweep can't fork-bomb.
_WORKERS = max(2, min(8, (os.cpu_count() or 4)))


def _pmap(fn, items):
    """Parallel map preserving order; exceptions propagate as in a serial map."""
    items = list(items)
    if len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        return list(ex.map(fn, items))

# import the sizing backend from the parent project dir (strongarm_sim/)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import run_sim  # noqa: E402
import layout  # noqa: E402
import vco_sim  # noqa: E402

def _arg_port(default=8770):
    if len(sys.argv) > 1:
        try:
            return int(sys.argv[1])
        except ValueError:
            pass   # e.g. imported under pytest where argv[1] is a test path
    return default


PORT = _arg_port()
DIST = os.path.join(HERE, "dist")  # production build (npm run build)

# P1_SAR_ADC spec targets the UI checks against
SPEC_TARGETS = {
    "decision_time_ps": {"limit": 400, "cmp": "<=", "unit": "ps", "label": "Decision time"},
    "power_uw":         {"limit": 100, "cmp": "<=", "unit": "µW", "label": "Power"},
    "offset_sigma_mv":  {"limit": 5,   "cmp": "<=", "unit": "mV", "label": "Offset σ"},
    "noise_uv_rms":     {"limit": 250, "cmp": "<=", "unit": "µV", "label": "Input noise"},
}


def _predict_offset_mv(params):
    """Analytic input-referred offset from Pelgrom (no simulation needed).
    Matches run_sim: per-device sigma_vth = AVT/sqrt(W*L*M); pair ~ sqrt(2)x."""
    d = params["devices"]["input"]
    area = d["w_um"] * (d["l_nm"] / 1000.0) * d["m"]
    sigma_vth = params["avt_mv_um"] / math.sqrt(max(area, 1e-9))
    return math.sqrt(2) * sigma_vth


def _size_input_for_offset(params, off_target_mv):
    """Pick input W (and M if needed) so predicted offset lands ~10% under target,
    without over-sizing. Only W and M change; L is fixed."""
    d = params["devices"]["input"]
    aim = off_target_mv * 0.9
    avt = params["avt_mv_um"]
    req_area = (math.sqrt(2) * avt / aim) ** 2          # um^2 needed
    l_um = d["l_nm"] / 1000.0
    m = max(int(d["m"]), 1)
    w = req_area / (l_um * m)
    while w > 40 and m < 16:                             # too wide -> add fingers
        m *= 2
        w = req_area / (l_um * m)
    w = max(round(math.ceil(w / 0.5) * 0.5, 2), 0.5)     # round up to 0.5 um, floor 0.5
    d["w_um"], d["m"] = w, m


def _verdicts(nominal, offset, targets):
    meas = {
        "decision_time_ps": nominal.get("decision_time_ps"),
        "power_uw": nominal.get("power_uw"),
        "offset_sigma_mv": (offset or {}).get("offset_sigma_mv"),
        "noise_uv_rms": nominal.get("noise_uv_rms"),
    }
    v = {}
    for k, lim in targets.items():
        mv = meas.get(k)
        v[k] = None if mv is None else (mv <= lim)
    return meas, v


DEV_KEYS = ["input", "tail", "ncc", "pcc", "pre"]


def _pred_offset_mv(p):
    d = p["devices"]["input"]
    area = d["w_um"] * (d["l_nm"] / 1000.0) * d["m"]
    return math.sqrt(2) * p["avt_mv_um"] / math.sqrt(max(area, 1e-9))


def _total_w(p):
    return round(sum(d["w_um"] * d["m"] for d in p["devices"].values()), 1)


def optimize(base, targets, pop=12, gens=8, seed=1234, use_surrogate=True):
    """Global sizing via log-space **Differential Evolution**.

    Minimizes power subject to offset + decision-time + functional constraints
    (penalty method). The five device-group widths are searched in log10 space
    (log-space handles the wide dynamic range and gives a more even power
    spread). Offset is the analytic Pelgrom prediction (free); decision, power,
    and functionality come from one fast ngspice transient per candidate. The
    best-of-generation history is returned as the trajectory so the UI can
    replay the search. `evaluate_hook` lets a surrogate pre-screen candidates."""
    import random
    rng = random.Random(seed)
    off_t = targets["offset_sigma_mv"]
    dec_t = targets["decision_time_ps"]
    LO, HI = math.log10(0.5), math.log10(40.0)

    # optional GP surrogate to pre-screen clearly-bad candidates (fewer SPICE calls)
    X_train, Y_train = [], []
    gp = {"m": None}
    try:
        import numpy as _np
        from sklearn.gaussian_process import GaussianProcessRegressor as _GPR
        from sklearn.gaussian_process.kernels import RBF as _RBF, WhiteKernel as _WK, ConstantKernel as _CK
        _have_gp = bool(use_surrogate)
    except Exception:
        _have_gp = False
    n_skip = [0]

    def _fit_gp():
        if not _have_gp or len(X_train) < 12:
            return
        k = _CK(1.0) * _RBF(length_scale=[0.6] * len(DEV_KEYS)) + _WK(0.02)
        gp["m"] = _GPR(kernel=k, normalize_y=True, alpha=1e-6, n_restarts_optimizer=0).fit(_np.array(X_train), _np.array(Y_train))

    def _reject(x, incumbent_cost):
        # True => GP is confident this candidate is worse than the incumbent
        if gp["m"] is None:
            return False
        mu, sd = gp["m"].predict(_np.array([x]), return_std=True)
        return (mu[0] - 1.0 * sd[0]) > math.log10(max(incumbent_cost, 1e-3))

    def make(x):
        p = copy.deepcopy(base)
        for i, dv in enumerate(DEV_KEYS):
            p["devices"][dv]["w_um"] = round(10 ** x[i], 2)
        return p

    cache = {}
    n_sims = [0]

    def _eval_raw(x):
        # pure: runs one ngspice sim, touches no shared state (thread-safe)
        p = make(x)
        offp = _pred_offset_mv(p)
        nom = run_sim.run_sim(p, do_offset=False)["nominal"]
        dec = nom.get("decision_time_ps")
        pw = nom.get("power_uw") or 1e6
        fn = bool(nom.get("functional")) and dec is not None
        cost = pw  # objective: minimize power
        if not fn:
            cost += 1e6
            dec = dec or 1e4
        if dec > dec_t:
            cost += 5000.0 * (dec / dec_t - 1.0)      # decision-time penalty
        if offp > off_t:
            cost += 5000.0 * (offp / off_t - 1.0)     # offset penalty (Pelgrom)
        return {"cost": cost, "x": list(x), "p": p, "nom": nom, "offp": offp}

    def _merge(out):
        # single-thread bookkeeping after a (possibly parallel) evaluation
        cache[tuple(round(v, 3) for v in out["x"])] = out
        n_sims[0] += 1
        X_train.append(out["x"])
        Y_train.append(math.log10(max(out["cost"], 1e-3)))
        return out

    def evaluate_many(xs):
        """Evaluate a batch of candidates in parallel; cache hits are free.
        Returns results in the same order as xs."""
        results = [None] * len(xs)
        todo = []
        for i, x in enumerate(xs):
            hit = cache.get(tuple(round(v, 3) for v in x))
            if hit is not None:
                results[i] = hit
            else:
                todo.append(i)
        for i, out in zip(todo, _pmap(_eval_raw, [xs[i] for i in todo])):
            results[i] = _merge(out)
        return results

    base_x = [max(LO, min(HI, math.log10(base["devices"][dv]["w_um"]))) for dv in DEV_KEYS]
    pop_x = [base_x] + [[rng.uniform(LO, HI) for _ in DEV_KEYS] for _ in range(pop - 1)]
    pop_e = evaluate_many(pop_x)
    traj = []

    def record(gen):
        bi = min(range(len(pop_e)), key=lambda i: pop_e[i]["cost"])
        e = pop_e[bi]
        meas, v = _verdicts(e["nom"], None, targets)
        traj.append({
            "action": f"DE gen {gen}: best power {round(e['nom'].get('power_uw') or 0, 1)}µW (cost {round(e['cost'], 1)})",
            "measured": meas, "verdicts": v, "predicted_offset_mv": round(e["offp"], 3),
            "total_w_um": _total_w(e["p"]), "params": copy.deepcopy(e["p"]["devices"]),
        })
        return bi

    record(0)
    F, CR = 0.6, 0.9
    for g in range(1, gens + 1):
        _fit_gp()  # refit surrogate on all SPICE-evaluated points so far
        survivors = []  # (target index, trial vector) that clear the surrogate gate
        for i in range(pop):
            a, b, c = rng.sample([j for j in range(pop) if j != i], 3)
            jr = rng.randrange(len(DEV_KEYS))
            trial = []
            for j in range(len(DEV_KEYS)):
                if rng.random() < CR or j == jr:
                    val = pop_x[a][j] + F * (pop_x[b][j] - pop_x[c][j])
                    trial.append(max(LO, min(HI, val)))
                else:
                    trial.append(pop_x[i][j])
            if _reject(trial, pop_e[i]["cost"]):
                n_skip[0] += 1          # surrogate is confident it's worse — skip SPICE
                continue
            survivors.append((i, trial))
        # evaluate this generation's surviving trials in parallel, then select
        for (i, trial), te in zip(survivors, evaluate_many([t for _, t in survivors])):
            if te["cost"] <= pop_e[i]["cost"]:
                pop_x[i], pop_e[i] = trial, te
        record(g)

    bi = min(range(len(pop_e)), key=lambda i: pop_e[i]["cost"])
    best = pop_e[bi]["p"]
    r = run_sim.run_sim(best, do_offset=True, with_noise=True)   # confirm the winner's offset (MC) + report noise
    meas, v = _verdicts(r["nominal"], r.get("offset"), targets)
    surrogate_note = f", {n_skip[0]} surrogate-skipped" if n_skip[0] else ""
    traj.append({"action": f"confirm best (Monte-Carlo offset) · {n_sims[0]} SPICE evals{surrogate_note}",
                 "measured": meas, "verdicts": v, "total_w_um": _total_w(best),
                 "params": copy.deepcopy(best["devices"])})
    success = v.get("offset_sigma_mv") is True and v.get("decision_time_ps") is True
    return {"trajectory": traj, "final_params": best, "final_result": r, "verdicts": v,
            "success": success, "targets": targets, "n_sims": n_sims[0], "n_surrogate_skips": n_skip[0],
            "final_power_uw": r["nominal"].get("power_uw"), "final_total_w_um": _total_w(best)}


def optimize_pareto(base, targets, pop=16, gens=6, seed=7):
    """Multi-objective **NSGA-II**: the power–speed trade-off as a Pareto front
    (minimize [power, decision-time]) subject to offset (Pelgrom) + functional
    feasibility. Returns the non-dominated front so the UI can plot it."""
    import random
    rng = random.Random(seed)
    off_t = targets["offset_sigma_mv"]
    LO, HI = math.log10(0.5), math.log10(40.0)

    def make(x):
        p = copy.deepcopy(base)
        for i, dv in enumerate(DEV_KEYS):
            p["devices"][dv]["w_um"] = round(10 ** x[i], 2)
        return p

    def ev(x):
        p = make(x)
        offp = _pred_offset_mv(p)
        nom = run_sim.run_sim(p, do_offset=False)["nominal"]
        dec = nom.get("decision_time_ps")
        pw = nom.get("power_uw") or 1e6
        fn = bool(nom.get("functional")) and dec is not None
        cv = (0.0 if fn else 1.0) + max(0.0, offp / off_t - 1.0)   # constraint violation
        return {"x": list(x), "p": p, "f": [pw, dec if dec else 1e5], "cv": cv, "offp": offp, "nom": nom}

    def dominates(a, b):  # Deb constraint-domination
        if a["cv"] != b["cv"]:
            return a["cv"] < b["cv"]
        le = all(af <= bf for af, bf in zip(a["f"], b["f"]))
        lt = any(af < bf for af, bf in zip(a["f"], b["f"]))
        return le and lt

    def nondom_sort(P):
        fronts, S, n = [[]], {}, {}
        for i, pi in enumerate(P):
            S[i] = [j for j, pj in enumerate(P) if dominates(pi, pj)]
            n[i] = sum(1 for j, pj in enumerate(P) if dominates(pj, pi))
            if n[i] == 0:
                fronts[0].append(i)
        k = 0
        while fronts[k]:
            nxt = []
            for i in fronts[k]:
                for j in S[i]:
                    n[j] -= 1
                    if n[j] == 0:
                        nxt.append(j)
            k += 1
            fronts.append(nxt)
        return [f for f in fronts if f]

    def crowding(P, idxs):
        dist = {i: 0.0 for i in idxs}
        for m in range(2):
            order = sorted(idxs, key=lambda i: P[i]["f"][m])
            dist[order[0]] = dist[order[-1]] = float("inf")
            lo, hi = P[order[0]]["f"][m], P[order[-1]]["f"][m]
            span = (hi - lo) or 1.0
            for r in range(1, len(order) - 1):
                dist[order[r]] += (P[order[r + 1]]["f"][m] - P[order[r - 1]]["f"][m]) / span
        return dist

    init_x = [[max(LO, min(HI, math.log10(base["devices"][dv]["w_um"]))) for dv in DEV_KEYS]]
    init_x += [[rng.uniform(LO, HI) for _ in DEV_KEYS] for _ in range(pop - 1)]
    pop_e = _pmap(ev, init_x)
    for _ in range(gens):
        trials = []
        for _ in range(pop):
            a, b, c = rng.sample(range(pop), 3)
            trials.append([max(LO, min(HI, pop_e[a]["x"][j] + 0.6 * (pop_e[b]["x"][j] - pop_e[c]["x"][j]))) for j in range(len(DEV_KEYS))])
        kids = _pmap(ev, trials)  # evaluate this generation's offspring in parallel
        comb = pop_e + kids
        fronts = nondom_sort(comb)
        newp = []
        for fr in fronts:
            if len(newp) + len(fr) <= pop:
                newp += [comb[i] for i in fr]
            else:
                cd = crowding(comb, fr)
                newp += [comb[i] for i in sorted(fr, key=lambda i: -cd[i])[: pop - len(newp)]]
                break
        pop_e = newp

    front = [pop_e[i] for i in nondom_sort(pop_e)[0] if pop_e[i]["cv"] == 0.0]
    front.sort(key=lambda e: e["f"][0])
    pts = [{"power_uw": e["nom"].get("power_uw"), "decision_time_ps": e["nom"].get("decision_time_ps"),
            "offp": round(e["offp"], 3), "devices": copy.deepcopy(e["p"]["devices"])} for e in front]
    allpts = [{"power_uw": e["nom"].get("power_uw"), "decision_time_ps": e["nom"].get("decision_time_ps"),
               "feasible": e["cv"] == 0.0} for e in pop_e]
    return {"front": pts, "all": allpts, "targets": targets}


def ber_curve(params, ber_target=1e-3):
    """Decision error-rate vs input amplitude, from the SPICE-measured
    input-referred noise (gm-based) and offset σ (Monte-Carlo). For a balanced
    comparator the error probability at differential input Vin is
    0.5·erfc(Vin/(σ·√2)); noise sets the per-decision floor, and adding the
    chip-to-chip offset broadens it (σ_tot = √(σ_vn²+σ_os²))."""
    r = run_sim.run_sim(params, do_offset=True, with_noise=True)
    nz_uv = r["nominal"].get("noise_uv_rms")
    os_mv = (r.get("offset") or {}).get("offset_sigma_mv")
    if not nz_uv:
        return {"error": "noise not available (comparator did not resolve)"}
    sig_vn = nz_uv * 1e-6                       # V
    sig_os = (os_mv or 0.0) * 1e-3              # V
    sig_tot = math.sqrt(sig_vn ** 2 + sig_os ** 2)
    amps = [1e-6 * (10 ** (i / 4.0)) for i in range(0, 21)]   # 1 µV .. 100 mV
    def _ber(v, s):
        return 0.5 * math.erfc(v / (s * math.sqrt(2))) if s > 0 else 0.0
    pts = [{"vin_v": round(v, 9), "ber_noise": _ber(v, sig_vn), "ber_total": _ber(v, sig_tot)} for v in amps]
    # min detectable input at the BER target: Vin = σ·√2·erfcinv(2·target)
    k = _erfcinv(2 * ber_target) * math.sqrt(2)
    return {"points": pts, "noise_uv_rms": nz_uv, "offset_sigma_mv": os_mv,
            "sigma_total_uv": round(sig_tot * 1e6, 1), "ber_target": ber_target,
            "min_input_noise_uv": round(sig_vn * k * 1e6, 2),
            "min_input_total_uv": round(sig_tot * k * 1e6, 2)}


def _erfcinv(y):
    """Inverse complementary error function via bisection (y in (0,2))."""
    if y <= 0:
        return 6.0
    if y >= 2:
        return -6.0
    lo, hi = -6.0, 6.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if math.erfc(mid) > y:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def sensitivity(base, delta=0.10):
    """One-at-a-time sensitivity: perturb each device width by ±delta and
    measure Δ{decision, power, offset}. offset is the free analytic Pelgrom
    prediction; decision/power come from ngspice. Evaluated in parallel."""
    def _metrics(p):
        nom = run_sim.run_sim(p, do_offset=False)["nominal"]
        return {"decision_time_ps": nom.get("decision_time_ps"),
                "power_uw": nom.get("power_uw"),
                "offset_sigma_mv": round(_pred_offset_mv(p), 4)}

    def _scaled(key, factor):
        p = copy.deepcopy(base)
        p["devices"][key]["w_um"] = round(p["devices"][key]["w_um"] * factor, 3)
        return p

    jobs = [(k, f) for k in DEV_KEYS for f in (1 - delta, 1 + delta)]
    results = _pmap(lambda kf: _metrics(_scaled(kf[0], kf[1])), jobs)
    base_m = _metrics(copy.deepcopy(base))
    by_dev = {}
    for (k, f), m in zip(jobs, results):
        by_dev.setdefault(k, {})["low" if f < 1 else "high"] = m
    devices = [{"key": k, "base_w_um": base["devices"][k]["w_um"],
                "low": by_dev[k]["low"], "high": by_dev[k]["high"]} for k in DEV_KEYS]
    return {"base": base_m, "delta_pct": round(delta * 100), "devices": devices}


def parametric_yield(base, targets, n=48, seed=11):
    """Parametric yield: Monte-Carlo over BOTH input-pair Vth mismatch (offset)
    AND a random PVT operating point (process skew / temp / VDD). A chip passes
    if it resolves in the correct direction, meets the decision-time target at
    its corner, and its offset is within spec. Yield = fraction passing — the
    production metric that couples mismatch and process variation."""
    import random
    n = max(1, int(n))                       # guard against n<=0 (would divide by zero)
    rng = random.Random(seed)
    p = copy.deepcopy(run_sim.DEFAULT_PARAMS)
    p.update({k: v for k, v in base.items() if k != "devices"})
    p["devices"] = run_sim.merge_devices(base.get("devices"))
    d = p["devices"]["input"]
    area = d["w_um"] * (d["l_nm"] / 1000.0) * d["m"]
    sig_vth = (p["avt_mv_um"] / math.sqrt(max(area, 1e-9))) / 1000.0   # V, per device
    sky = p.get("model") == "sky130"
    dec_t = targets["decision_time_ps"]
    off_t = targets["offset_sigma_mv"]        # used here as the |offset| limit (mV)
    base_vdd = float(p["vdd"])

    samples = []
    for _ in range(n):
        dvth1, dvth2 = rng.gauss(0, sig_vth), rng.gauss(0, sig_vth)
        proc = {"corner": rng.choice(["ss", "tt", "ff"])} if sky else {"pskew": rng.gauss(0, 0.03)}
        samples.append((dvth1, dvth2, (dvth1 - dvth2) * 1000.0,
                        rng.choice([-40, 27, 125]), round(base_vdd * rng.uniform(0.9, 1.1), 3), proc))

    def _one(s):
        dvth1, dvth2, offset_mv, temp, vdd, proc = s
        cfg = {**p, "vdd": vdd, "temp": temp, **proc}
        out = run_sim._run(run_sim.gen_netlist(cfg, vdiff=0.05, dvth1=dvth1, dvth2=dvth2))
        tdec, fdiff = run_sim._parse(out, "tdec"), run_sim._parse(out, "fdiff")
        functional = tdec is not None and fdiff is not None and abs(fdiff) > 0.7 * vdd
        dec_ps = tdec * 1e12 if tdec else None
        correct = fdiff is not None and fdiff < 0          # matches the zero-offset polarity
        speed_ok = bool(functional and dec_ps is not None and dec_ps <= dec_t)
        off_ok = abs(offset_mv) <= off_t
        return {"offset_mv": round(offset_mv, 3), "decision_ps": round(dec_ps, 2) if dec_ps else None,
                "temp": temp, "vdd": vdd, "functional": bool(functional), "correct": bool(correct),
                "speed_ok": speed_ok, "offset_ok": off_ok,
                "pass": bool(functional and correct and speed_ok and off_ok)}

    res = _pmap(_one, samples)
    npass = sum(1 for r in res if r["pass"])
    fails = {"offset": sum(1 for r in res if not r["offset_ok"]),
             "speed": sum(1 for r in res if not r["speed_ok"]),
             "decision_wrong": sum(1 for r in res if not (r["functional"] and r["correct"]))}
    return {"n": n, "yield_pct": round(100.0 * npass / n, 1), "pass": npass,
            "fail_breakdown": fails, "samples": res[:60],
            "targets": {"decision_time_ps": dec_t, "offset_mv": off_t}}


def optimize_vco(base, targets, pop=12, gens=7, seed=41):
    """Size the ring VCO's four device groups (log-space Differential Evolution)
    to hit a target oscillation frequency at the nominal V_ctrl while minimizing
    power — the same simulate->evaluate->optimize loop used for the comparator.
    Objective: minimize power_uw + penalty(|f-f_target|) + big penalty if it does
    not oscillate. The winner is re-characterized with a full V_ctrl tuning sweep."""
    import random
    rng = random.Random(seed)
    f_t = float(targets.get("f_ghz", 1.5))
    LO, HI = math.log10(0.5), math.log10(40.0)
    keys = vco_sim.DEV_KEYS

    def make(x):
        p = copy.deepcopy(base)
        for i, k in enumerate(keys):
            p["devices"][k]["w_um"] = round(10 ** x[i], 2)
        return p

    cache, n_sims = {}, [0]

    def _eval_raw(x):
        p = make(x)
        m = vco_sim.measure_vco(p)
        f, pw, osc = m["f_osc_ghz"], m["power_uw"] or 1e6, m["oscillates"]
        cost = pw
        if not osc or f is None:
            cost += 1e6
        else:
            df = abs(f - f_t) / f_t                       # frequency-match penalty:
            cost += 20000.0 * df + 60000.0 * df * df      # steep so f is hit, then min power
        return {"cost": cost, "x": list(x), "p": p, "m": m}

    def evaluate_many(xs):
        res = [None] * len(xs)
        todo = []
        for i, x in enumerate(xs):
            hit = cache.get(tuple(round(v, 3) for v in x))
            if hit is not None:
                res[i] = hit
            else:
                todo.append(i)
        for i, out in zip(todo, _pmap(_eval_raw, [xs[i] for i in todo])):
            cache[tuple(round(v, 3) for v in out["x"])] = out
            n_sims[0] += 1
            res[i] = out
        return res

    base_x = [max(LO, min(HI, math.log10(base["devices"][k]["w_um"]))) for k in keys]
    pop_x = [base_x] + [[rng.uniform(LO, HI) for _ in keys] for _ in range(pop - 1)]
    pop_e = evaluate_many(pop_x)
    traj = []

    def record(gen):
        e = min(pop_e, key=lambda z: z["cost"])
        m = e["m"]
        traj.append({"action": f"DE gen {gen}: {m['f_osc_ghz']}GHz, {m['power_uw']}µW"
                                + ("" if m["oscillates"] else " (no osc)"),
                     "f_osc_ghz": m["f_osc_ghz"], "power_uw": m["power_uw"],
                     "oscillates": m["oscillates"], "params": copy.deepcopy(e["p"]["devices"])})

    record(0)
    F, CR = 0.6, 0.9
    for g in range(1, gens + 1):
        trials = []
        for i in range(pop):
            a, b, c = rng.sample([j for j in range(pop) if j != i], 3)
            jr = rng.randrange(len(keys))
            trial = [max(LO, min(HI, pop_x[a][j] + F * (pop_x[b][j] - pop_x[c][j]))) if (rng.random() < CR or j == jr) else pop_x[i][j]
                     for j in range(len(keys))]
            trials.append((i, trial))
        for (i, trial), te in zip(trials, evaluate_many([t for _, t in trials])):
            if te["cost"] <= pop_e[i]["cost"]:
                pop_x[i], pop_e[i] = trial, te
        record(g)

    best = min(pop_e, key=lambda z: z["cost"])
    fin = best["p"]
    tuning = vco_sim.vco_tuning(fin)
    m = best["m"]
    success = bool(m["oscillates"] and m["f_osc_ghz"] is not None
                   and abs(m["f_osc_ghz"] - f_t) / f_t <= 0.1)
    traj.append({"action": f"confirm + tuning sweep · {n_sims[0]} SPICE evals",
                 "f_osc_ghz": m["f_osc_ghz"], "power_uw": m["power_uw"],
                 "oscillates": m["oscillates"], "params": copy.deepcopy(fin["devices"])})
    return {"trajectory": traj, "final_params": fin, "nominal": m, "tuning": tuning,
            "success": success, "target_f_ghz": f_t, "n_sims": n_sims[0]}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._json({"ok": True, "ngspice": run_sim.NGSPICE})
        elif path == "/api/defaults":
            self._json({"defaults": run_sim.DEFAULT_PARAMS, "targets": SPEC_TARGETS})
        elif path.startswith("/api/"):
            self._json({"error": "not found"}, 404)
        else:
            self._serve_static(path)

    def _serve_static(self, path):
        # serve the production build; single origin => no Vite, no HMR, no flicker
        if not os.path.isdir(DIST):
            self._json({"error": "no build; run: npm run build"}, 503)
            return
        rel = "index.html" if path == "/" else path.lstrip("/")
        target = os.path.normpath(os.path.join(DIST, rel))
        if not target.startswith(DIST):  # path traversal guard
            self._json({"error": "forbidden"}, 403)
            return
        if not os.path.isfile(target):
            target = os.path.join(DIST, "index.html")  # SPA fallback
        try:
            with open(target, "rb") as fh:
                body = fh.read()
        except OSError:
            self._json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        try:
            if self.path == "/api/simulate":
                payload = self._read_json()
                result = run_sim.run_sim(payload.get("params", {}),
                                         do_offset=bool(payload.get("do_offset", True)),
                                         with_noise=True)
                nom, off = result.get("nominal", {}), result.get("offset", {})
                result["verdicts"] = {
                    k: (None if nom.get(k, off.get(k)) is None
                        else (nom.get(k, off.get(k)) <= spec["limit"]))
                    for k, spec in SPEC_TARGETS.items()
                }
                self._json(result)
            elif self.path == "/api/waveform":
                payload = self._read_json()
                self._json(run_sim.capture_waveform(payload.get("params", {})))
            elif self.path == "/api/layout":
                payload = self._read_json()
                base = payload.get("params", {})
                full = copy.deepcopy(run_sim.DEFAULT_PARAMS)
                full["devices"] = run_sim.merge_devices(base.get("devices"))
                self._json(layout.generate_layout(full))
            elif self.path == "/api/metastability":
                payload = self._read_json()
                self._json(run_sim.metastability_sweep(payload.get("params", {})))
            elif self.path == "/api/ber":
                payload = self._read_json()
                full = copy.deepcopy(run_sim.DEFAULT_PARAMS)
                full.update({k: v for k, v in payload.get("params", {}).items() if k != "devices"})
                full["devices"] = run_sim.merge_devices(payload.get("params", {}).get("devices"))
                self._json(ber_curve(full))
            elif self.path == "/api/sensitivity":
                payload = self._read_json()
                full = copy.deepcopy(run_sim.DEFAULT_PARAMS)
                full.update({k: v for k, v in payload.get("params", {}).items() if k != "devices"})
                full["devices"] = run_sim.merge_devices(payload.get("params", {}).get("devices"))
                self._json(sensitivity(full))
            elif self.path == "/api/maxfclk":
                payload = self._read_json()
                self._json(run_sim.max_fclk_sweep(payload.get("params", {})))
            elif self.path == "/api/vco/simulate":
                payload = self._read_json()
                self._json(vco_sim.run_vco(payload.get("params", {}),
                                           do_tuning=bool(payload.get("do_tuning", False))))
            elif self.path == "/api/vco/tuning":
                payload = self._read_json()
                self._json(vco_sim.vco_tuning(payload.get("params", {})))
            elif self.path == "/api/vco/optimize":
                payload = self._read_json()
                base = vco_sim._full(payload.get("params", {}))
                self._json(optimize_vco(base, payload.get("targets") or {"f_ghz": 1.5}))
            elif self.path == "/api/yield":
                payload = self._read_json()
                targets = payload.get("targets") or {k: s["limit"] for k, s in SPEC_TARGETS.items()}
                self._json(parametric_yield(payload.get("params", {}), targets, n=int(payload.get("n", 48))))
            elif self.path == "/api/postlayout":
                payload = self._read_json()
                prm = payload.get("params", {})
                pc = layout.extract_parasitics({**run_sim.DEFAULT_PARAMS, **prm,
                                                "devices": run_sim.merge_devices(prm.get("devices"))})
                plp = {**prm, "parasitic": True, "par_caps": pc}
                sch = run_sim.run_sim({**prm, "parasitic": False}, do_offset=False)
                pl = run_sim.run_sim(plp, do_offset=False)
                self._json({
                    "schematic": {"nominal": sch["nominal"], "waveform": run_sim.capture_waveform({**prm, "parasitic": False})},
                    "postlayout": {"nominal": pl["nominal"], "waveform": run_sim.capture_waveform(plp)},
                    "par_caps": pc,
                })
            elif self.path == "/api/pvt":
                payload = self._read_json()
                prm = payload.get("params", {})
                base_vdd = float(prm.get("vdd", run_sim.DEFAULT_PARAMS["vdd"]))
                sky = prm.get("model") == "sky130"
                cmap = {"SS": "ss", "TT": "tt", "FF": "ff"}
                specs = []
                for pl, ps in (("SS", 0.05), ("TT", 0.0), ("FF", -0.05)):
                    for t in (-40, 27, 125):
                        for vf in (0.9, 1.0, 1.1):
                            vdd = round(base_vdd * vf, 3)
                            proc = {"corner": cmap[pl]} if sky else {"pskew": ps}   # real PDK corner vs Vth skew
                            specs.append((pl, t, vf, vdd, proc))

                def _corner(s):
                    pl, t, vf, vdd, proc = s
                    nom = run_sim.run_sim({**prm, "vdd": vdd, "temp": t, **proc}, do_offset=False)["nominal"]
                    return {"process": pl, "temp": t, "v_frac": vf, "vdd": vdd,
                            "decision_time_ps": nom.get("decision_time_ps"),
                            "power_uw": nom.get("power_uw"),
                            "functional": bool(nom.get("functional"))}

                corners = _pmap(_corner, specs)   # 27 independent corners, parallel
                decs = [c["decision_time_ps"] for c in corners if c["decision_time_ps"] is not None]
                pws = [c["power_uw"] for c in corners if c["power_uw"] is not None]
                self._json({"corners": corners, "base_vdd": base_vdd, "worst": {
                    "decision_time_ps": max(decs) if decs else None,
                    "power_uw": max(pws) if pws else None,
                    "any_nonfunctional": any(not c["functional"] for c in corners),
                }})
            elif self.path == "/api/pareto":
                payload = self._read_json()
                base = payload.get("params", {})
                full = copy.deepcopy(run_sim.DEFAULT_PARAMS)
                full.update({k: v for k, v in base.items() if k != "devices"})
                full["devices"] = run_sim.merge_devices(base.get("devices"))
                targets = payload.get("targets") or {k: s["limit"] for k, s in SPEC_TARGETS.items()}
                self._json(optimize_pareto(full, targets))
            elif self.path == "/api/fullflow":
                payload = self._read_json()
                base = payload.get("params", {})
                full = copy.deepcopy(run_sim.DEFAULT_PARAMS)
                full.update({k: v for k, v in base.items() if k != "devices"})
                full["devices"] = run_sim.merge_devices(base.get("devices"))
                targets = payload.get("targets") or {k: s["limit"] for k, s in SPEC_TARGETS.items()}
                stages = []
                # 1) sizing (DE + surrogate) with MC-confirmed offset
                opt = optimize(full, targets)
                fin = opt["final_params"]
                off = (opt["final_result"].get("offset") or {}).get("offset_sigma_mv")
                stages.append({"name": "Sizing — DE + GP surrogate", "ok": bool(opt["success"]),
                               "detail": f"{opt['final_power_uw']}µW, offset {off}mV, {opt['n_sims']} SPICE evals"})
                # 2) post-layout parasitic re-sim (schematic vs layout-extracted, in parallel)
                pc = layout.extract_parasitics(fin)
                sch, pl = _pmap(lambda cfg: run_sim.run_sim({**fin, **cfg}, do_offset=False)["nominal"],
                                [{"parasitic": False}, {"parasitic": True, "par_caps": pc}])
                pl_ok = bool(pl["functional"]) and pl["decision_time_ps"] is not None and pl["decision_time_ps"] <= targets["decision_time_ps"]
                stages.append({"name": "Post-layout parasitics", "ok": pl_ok,
                               "detail": f"decision {sch['decision_time_ps']}→{pl['decision_time_ps']}ps"})
                # 3) PVT sign-off (representative worst corners, in parallel)
                sky = fin.get("model") == "sky130"
                bv = float(fin.get("vdd", 1.0))
                reps = [("SS", 0.05, "ss", 125, 0.9), ("TT", 0.0, "tt", 27, 1.0), ("FF", -0.05, "ff", -40, 1.1)]

                def _rep(r):
                    pl_, ps, cn, t, vf = r
                    proc = {"corner": cn} if sky else {"pskew": ps}
                    n = run_sim.run_sim({**fin, "vdd": round(bv * vf, 3), "temp": t, **proc}, do_offset=False)["nominal"]
                    return {"process": pl_, "temp": t, "v_frac": vf, "decision_time_ps": n.get("decision_time_ps"), "power_uw": n.get("power_uw"), "functional": bool(n.get("functional"))}

                pvt_c = _pmap(_rep, reps)
                wd = max((c["decision_time_ps"] for c in pvt_c if c["decision_time_ps"] is not None), default=None)
                pvt_ok = wd is not None and wd <= targets["decision_time_ps"] and all(c["functional"] for c in pvt_c)
                stages.append({"name": "PVT sign-off (3 corners)", "ok": pvt_ok,
                               "detail": f"worst decision {wd}ps across SS/TT/FF"})
                # 4) layout synthesis + rule DRC (GDSII)
                lay = layout.generate_layout(fin)
                lay_ok = bool(lay["drc"]["clean"])
                stages.append({"name": "Layout + DRC (GDSII)", "ok": lay_ok,
                               "detail": f"cell {lay['area_um2']}µm², {'DRC clean' if lay_ok else str(lay['drc']['n_violations']) + ' DRC violations'}, GDS written"})
                self._json({"stages": stages, "final_params": fin, "verdicts": opt["verdicts"],
                            "overall": all(s["ok"] for s in stages), "pvt": pvt_c,
                            "final_power_uw": opt["final_power_uw"], "layout": lay})
            elif self.path == "/api/optimize":
                payload = self._read_json()
                base = payload.get("params", {})
                # merge base over DEFAULT_PARAMS so every device/field is present
                full = copy.deepcopy(run_sim.DEFAULT_PARAMS)
                full.update({k: v for k, v in base.items() if k != "devices"})
                full["devices"] = {**run_sim.DEFAULT_PARAMS["devices"],
                                   **base.get("devices", {})}
                targets = payload.get("targets") or {k: s["limit"] for k, s in SPEC_TARGETS.items()}
                self._json(optimize(full, targets))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:  # surface errors to the UI
            self._json({"error": str(e)}, 500)

    def log_message(self, *args):  # quieter console
        pass


if __name__ == "__main__":
    print(f"StrongARM sizing API on http://127.0.0.1:{PORT}  (ngspice: {run_sim.NGSPICE})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

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
import wicked  # noqa: E402
import vco_wicked  # noqa: E402

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


DEV_KEYS = ["input", "tail", "ncc", "pcc", "pre", "prei"]


def _pred_offset_mv(p):
    d = p["devices"]["input"]
    area = d["w_um"] * (d["l_nm"] / 1000.0) * d["m"]
    return math.sqrt(2) * p["avt_mv_um"] / math.sqrt(max(area, 1e-9))


def _total_w(p):
    return round(sum(d["w_um"] * d["m"] for d in p["devices"].values()), 1)


def _snap_w(p):
    # W 그리드 모델(gaa2nm: 시트 0.2µ, asap7: 핀 0.07µ) — 옵티마이저 후보의
    # 표시값이 넷리스트 양자화(run_sim.quantize_devices) 결과와 일치하도록 스냅.
    s = run_sim.w_unit(p)
    if s:
        for d in p["devices"].values():
            d["w_um"] = max(s, round(round(d["w_um"] / s) * s, 3))
    return p


def _stacks(p):
    # 그리드 모델의 소자별 정수 단위 수(gaa2nm: 스택 W/0.2, asap7: 핀 W/0.07)
    # — 자동 사이징이 실제로 찾는 것은 연속 W 가 아니라 이 정수다.
    s = run_sim.w_unit(p) or 1.0
    return {k: int(round(d["w_um"] / s)) for k, d in p["devices"].items()}


def _xkey(base, x):
    # 후보 캐시 키. W 그리드 모델(gaa2nm/asap7)은 정수(스택/핀 수) 공간으로
    # 키를 잡는다 — 같은 그리드 점으로 스냅되는 연속 후보들이 ngspice 를 다시
    # 돌지 않으므로, log-공간 DE/CD 는 사실상 정수 탐색이 된다.
    s = run_sim.w_unit(base)
    if s:
        return tuple(max(1, round((10 ** v) / s)) for v in x)
    return tuple(round(v, 3) for v in x)


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
        return _snap_w(p)

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
        cache[_xkey(base, out["x"])] = out
        n_sims[0] += 1
        X_train.append(out["x"])
        Y_train.append(math.log10(max(out["cost"], 1e-3)))
        return out

    def evaluate_many(xs):
        """Evaluate a batch of candidates in parallel; cache hits are free.
        Returns results in the same order as xs."""
        results = [None] * len(xs)
        todo, seen = [], {}
        for i, x in enumerate(xs):
            key = _xkey(base, x)
            hit = cache.get(key)
            if hit is not None:
                results[i] = hit
            elif key in seen:
                results[i] = ("dup", seen[key])   # 같은 그리드 점 — 배치 내 중복
            else:
                seen[key] = i
                todo.append(i)
        for i, out in zip(todo, _pmap(_eval_raw, [xs[i] for i in todo])):
            results[i] = _merge(out)
        # 배치 내 중복(같은 그리드 점) 참조 해소
        for i, r in enumerate(results):
            if isinstance(r, tuple) and r[0] == "dup":
                results[i] = results[r[1]]
        return results

    traj = []

    if run_sim.w_unit(base):
        # ---- 그리드 모델: 정수 스택/핀 좌표 하강(coordinate descent) ------
        # W 가 0.2µ 그리드 위에만 있으므로 탐색 공간은 소자당 정수 스택 수다.
        # DE(연속 완화) 대신 정수 공간을 직접 걷는다: 소자별로 거친 배수 이동
        # (×0.5…×2)을 병렬 평가해 최선을 채택, 전 소자 수렴 후 ±1 미세 단계.
        # 캐시 키가 스택 튜플이라 재방문 점은 SPICE 를 다시 돌지 않는다.
        s0 = run_sim.w_unit(base)
        NMAX = int(round(10 ** HI / s0))     # W 상한(40µm) → 최대 스택/핀 수
        budget = pop * gens + pop            # DE 와 같은 SPICE 예산
        cur = [min(NMAX, max(1, round(base["devices"][dv]["w_um"] / s0))) for dv in DEV_KEYS]

        def x_of(ns):
            return [math.log10(v * s0) for v in ns]

        cur_e = evaluate_many([x_of(cur)])[0]

        def rec(tag, e, ns):
            meas, v = _verdicts(e["nom"], None, targets)
            stacks_note = " ".join(f"{dv} {n}" for dv, n in zip(DEV_KEYS, ns))
            traj.append({
                "action": f"{tag}: power {round(e['nom'].get('power_uw') or 0, 1)}µW (cost {round(e['cost'], 1)}) · stacks {stacks_note}",
                "measured": meas, "verdicts": v, "predicted_offset_mv": round(e["offp"], 3),
                "total_w_um": _total_w(e["p"]), "params": copy.deepcopy(e["p"]["devices"]),
            })

        rec("CD start", cur_e, cur)
        coarse = True
        for pass_i in range(1, 13):
            improved = False
            for ci in range(len(DEV_KEYS)):
                b_n = cur[ci]
                if coarse:
                    cands = sorted({max(1, min(NMAX, round(b_n * f)))
                                    for f in (0.5, 0.67, 0.8, 1.25, 1.5, 2.0)} - {b_n})
                else:
                    cands = [v for v in (b_n - 1, b_n + 1) if 1 <= v <= NMAX]
                if not cands:
                    continue
                trials = []
                for v in cands:
                    t = list(cur)
                    t[ci] = v
                    trials.append(x_of(t))
                evs = evaluate_many(trials)   # 한 좌표의 이동 후보들을 병렬 평가
                bi2 = min(range(len(evs)), key=lambda i: evs[i]["cost"])
                if evs[bi2]["cost"] < cur_e["cost"]:
                    cur[ci], cur_e, improved = cands[bi2], evs[bi2], True
                if n_sims[0] >= budget:
                    break
            rec(f"CD pass {pass_i} ({'coarse ×' if coarse else 'fine ±1'})", cur_e, cur)
            if n_sims[0] >= budget:
                break
            if not improved:
                if coarse:
                    coarse = False           # 거친 배수 단계 수렴 → ±1 미세 단계
                else:
                    break                    # 정수 국소 최적 도달
        best = cur_e["p"]
    else:
        base_x = [max(LO, min(HI, math.log10(base["devices"][dv]["w_um"]))) for dv in DEV_KEYS]
        pop_x = [base_x] + [[rng.uniform(LO, HI) for _ in DEV_KEYS] for _ in range(pop - 1)]
        pop_e = evaluate_many(pop_x)

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
            "final_power_uw": r["nominal"].get("power_uw"), "final_total_w_um": _total_w(best),
            # gaa2nm: 자동 사이징이 실제로 찾은 것 = 소자별 나노시트 스택 수(정수)
            "final_stacks": _stacks(best) if run_sim.w_unit(base) else None}


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
        return _snap_w(p)

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


NETLIST_MOS_RE = None  # lazy re


AGENT_PROFILE_CFG = os.path.expanduser("~/.hermes/profiles/strong-arm/config.yaml")


def _agent_endpoint():
    """hermes strong-arm 프로파일의 api_server 주소·토큰(설정 파일에서 발견).

    실패 시 (None, None) — 프록시 엔드포인트가 503 으로 안내한다.
    """
    import re
    url = os.environ.get("STRONGARM_AGENT_URL")
    tok = os.environ.get("STRONGARM_AGENT_TOKEN")
    if url and tok:
        return url, tok
    try:
        cfg = open(AGENT_PROFILE_CFG, encoding="utf-8").read()
        port = re.search(r"api_server:.*?port:\s*(\d+)", cfg, re.S)
        token = re.search(r"platforms:.*?api_server:.*?token:\s*([0-9a-f]{32,})", cfg, re.S)
        if port and token:
            return f"http://127.0.0.1:{port.group(1)}/v1/chat/completions", token.group(1)
    except OSError:
        pass
    return None, None


def agent_chat(message, session_id=None, timeout=600):
    """hermes strong-arm 에이전트(OpenAI 호환)로 한 턴 — MCP 로 SPICE 실행 가능."""
    import json as _json
    import urllib.request
    url, tok = _agent_endpoint()
    if not url:
        return {"error": "hermes strong-arm 프로파일을 찾지 못했습니다 — "
                          "~/.hermes/profiles/strong-arm 게이트웨이가 필요합니다."}
    sid = session_id or ("console-" + os.urandom(8).hex())
    body = _json.dumps({"model": "hermes-agent",
                        "messages": [{"role": "user", "content": message}]}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {tok}",
        "X-Hermes-Session-Id": sid})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = _json.loads(r.read().decode())
        return {"answer": d["choices"][0]["message"]["content"], "sessionId": sid}
    except Exception as e:  # 연결 실패/타임아웃 → UI 에 그대로 안내
        return {"error": f"에이전트 호출 실패: {e}", "sessionId": sid}


def run_raw_netlist(netlist):
    """임의 SPICE 덱을 ngspice -b 로 실행 — 자연어 회로 변경 루프의 검증 단계.

    반환: 모든 .meas 결과(이름→값), 콘솔 로그 꼬리. `shell` 명령은 차단
    (로컬 도구지만 ngspice control 의 셸 이스케이프는 막는다).
    """
    import re
    if re.search(r"^\s*shell\b", netlist, re.M | re.I):
        return {"error": "netlist 에 shell 명령은 허용되지 않습니다."}
    out = run_sim._run(netlist)
    meas = {}
    for m in re.finditer(r"^(\w+)\s*=\s*([-+0-9.eE]+)", out, re.M):
        try:
            meas[m.group(1)] = float(m.group(2))
        except ValueError:
            pass
    tail = "\n".join(out.strip().splitlines()[-25:])
    return {"measures": meas, "log_tail": tail}


def parse_netlist_text(text):
    """SPICE 덱에서 MOS/전원/커패시터를 파싱해 소자 표 + (가능하면) 파라미터로.

    이 콘솔이 내보내는 덱의 명명 규칙을 안다:
      comparator — M1/M2=input, Mt=tail, M3/M4=ncc, M5/M6=pcc, M7..M10=pre
      vco(xcpl)  — Mbp*/Mbpb*=starvep, Mp*/Mpb*=invp, Mn*/Mnb*=invn,
                   Mbn*/Mbnb*=starven, Mx*/Mxb*=xcplp, Mrst=rstp (스테이지 번호로 N)
    규칙 밖 넷리스트도 소자 표/노드는 반환한다(kind='unknown').
    """
    import re
    mos_re = re.compile(r"^(M\S*)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(nmos|pmos)\s+W=([\d.]+)u\s+L=([\d.]+)n?\s+M=(\d+)", re.I)
    # asap7(BSIM-CMG OSDI): NM1 d g s b nmos_lvt l=21n nfin=16 — 이름의 N 접두를
    # 벗겨 M* 역할 매핑을 재사용, W 는 핀 수 × 0.07µ 로 환산(m=1)
    osdi_re = re.compile(r"^N(M\S*)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(nmos|pmos)_\w+\s+l=([\d.]+)n\s+nfin=(\d+)", re.I)
    v_re = re.compile(r"^V(\S*)\s+(\S+)\s+(\S+)\s+([\d.]+)\s*$", re.I)
    c_re = re.compile(r"^C(\S*)\s+(\S+)\s+(\S+)\s+([\d.]+)f", re.I)
    devices, sources, caps = [], {}, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("*", ".")):
            continue
        m = mos_re.match(line)
        if m:
            name, d, g, s, b, kind, w, l, mult = m.groups()
            devices.append({"name": name, "type": kind.lower(), "w_um": float(w),
                            "l_nm": float(l), "m": int(mult), "nodes": {"d": d, "g": g, "s": s, "b": b}})
            continue
        mo = osdi_re.match(line)
        if mo:
            name, d, g, s, b, kind, l, nfin = mo.groups()
            devices.append({"name": name, "type": kind.lower(),
                            "w_um": round(int(nfin) * run_sim.W_FIN_UM, 3),
                            "l_nm": float(l), "m": 1, "nodes": {"d": d, "g": g, "s": s, "b": b}})
            continue
        mv = v_re.match(line)
        if mv:
            sources[mv.group(1).lower() or mv.group(2).lower()] = float(mv.group(4))
            continue
        mc = c_re.match(line)
        if mc:
            caps.append({"name": "C" + mc.group(1), "node": mc.group(2), "ff": float(mc.group(4))})
    names = {d["name"] for d in devices}
    # 모델 백엔드 감지 — 이 콘솔이 내보내는 .include/.lib 헤더 기준(왕복 보존)
    model = ("gaa2nm" if "gaa2nm_approx" in text
             else ("asap7" if ("asap7" in text or "bsimcmg" in text) else
                   ("sky130" if "sky130" in text.lower() else None)))
    out = {"devices": devices, "n_mos": len(devices), "caps": caps, "sources": sources}
    if any(n.startswith("Mx") for n in names) and any(n.startswith("Mbp") for n in names):
        # ── VCO(xcpl) ──
        import re as _re
        stages = [int(mm.group(1)) for n in names for mm in [_re.match(r"Mp(\d+)$", n)] if mm]
        role_of = [("Mbpb", "starvep"), ("Mbp", "starvep"), ("Mpb", "invp"), ("Mp", "invp"),
                   ("Mnb", "invn"), ("Mn", "invn"), ("Mbnb", "starven"), ("Mbn", "starven"),
                   ("Mxb", "xcplp"), ("Mx", "xcplp"), ("Mrst", "rstp")]
        dev_params = {}
        for d in devices:
            for prefix, key in role_of:
                if d["name"].startswith(prefix) and key not in dev_params and d["name"] not in ("Mpref", "Mnref"):
                    dev_params[key] = {"w_um": d["w_um"], "l_nm": d["l_nm"], "m": d["m"]}
                    break
        params = {"devices": dev_params}
        if model in ("gaa2nm", "asap7"): params["model"] = model
        if "dd" in sources: params["vdd"] = sources["dd"]
        if "c" in sources: params["vctrl"] = sources["c"]
        if stages: params["n_stages"] = max(stages)
        node_caps = [c for c in caps if c["node"].startswith("o")]
        if node_caps: params["cload_ff"] = node_caps[0]["ff"]
        out.update({"kind": "vco", "params": params})
        return out
    if {"Mt1", "Mt2"} <= names:
        # ── comparator (double-tail) ──
        role = {"M1": "input", "M2": "input", "Mt1": "tail", "M3": "pre", "M4": "pre",
                "M5": "pcc", "M6": "pcc", "M7": "ncc", "M8": "ncc"}
        dev_params = {}
        for d in devices:
            key = role.get(d["name"])
            if key and key not in dev_params:
                dev_params[key] = {"w_um": d["w_um"], "l_nm": d["l_nm"], "m": d["m"]}
        params = {"devices": dev_params, "topology": "doubletail"}
        if model: params["model"] = model
        if "dd" in sources: params["vdd"] = sources["dd"]
        out_caps = [c for c in caps if c["node"] in ("outp", "outn")]
        if out_caps: params["cload_ff"] = out_caps[0]["ff"]
        out.update({"kind": "comparator", "params": params})
        return out
    if "Mt" in names and {"M1", "M3", "M5"} <= names:
        # ── comparator (single-tail strongarm) ──
        role = {"M1": "input", "M2": "input", "Mt": "tail", "M3": "ncc", "M4": "ncc",
                "M5": "pcc", "M6": "pcc", "M7": "pre", "M8": "pre", "M9": "prei", "M10": "prei"}
        dev_params = {}
        for d in devices:
            key = role.get(d["name"])
            if key and key not in dev_params:
                dev_params[key] = {"w_um": d["w_um"], "l_nm": d["l_nm"], "m": d["m"]}
        params = {"devices": dev_params, "topology": "strongarm"}
        if model: params["model"] = model
        if "dd" in sources: params["vdd"] = sources["dd"]
        out_caps = [c for c in caps if c["node"] in ("outp", "outn")]
        if out_caps: params["cload_ff"] = out_caps[0]["ff"]
        out.update({"kind": "comparator", "params": params})
        return out
    out["kind"] = "unknown"
    return out


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

    # GP surrogate on log10(cost) to pre-screen clearly-worse candidates (fewer SPICE runs)
    X_train, Y_train, gp, n_skip = [], [], {"m": None}, [0]
    try:
        import numpy as _np
        from sklearn.gaussian_process import GaussianProcessRegressor as _GPR
        from sklearn.gaussian_process.kernels import RBF as _RBF, WhiteKernel as _WK, ConstantKernel as _CK
        _have_gp = True
    except Exception:
        _have_gp = False

    def _fit_gp():
        if not _have_gp or len(X_train) < 12:
            return
        k = _CK(1.0) * _RBF(length_scale=[0.6] * len(keys)) + _WK(0.02)
        gp["m"] = _GPR(kernel=k, normalize_y=True, alpha=1e-6, n_restarts_optimizer=0).fit(_np.array(X_train), _np.array(Y_train))

    def _reject(x, incumbent_cost):
        if gp["m"] is None:
            return False
        mu, sd = gp["m"].predict(_np.array([x]), return_std=True)
        return (mu[0] - 1.0 * sd[0]) > math.log10(max(incumbent_cost, 1e-3))

    def make(x):
        p = copy.deepcopy(base)
        for i, k in enumerate(keys):
            p["devices"][k]["w_um"] = round(10 ** x[i], 2)
        return _snap_w(p)   # gaa2nm: 시트 그리드 스냅 — 표시값 = 시뮬값

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
        todo, seen = [], {}
        for i, x in enumerate(xs):
            key = _xkey(base, x)                 # gaa2nm: 스택 수(정수) 공간 키
            hit = cache.get(key)
            if hit is not None:
                res[i] = hit
            elif key in seen:
                res[i] = ("dup", seen[key])      # 같은 그리드 점 — 배치 내 중복
            else:
                seen[key] = i
                todo.append(i)
        for i, out in zip(todo, _pmap(_eval_raw, [xs[i] for i in todo])):
            cache[_xkey(base, out["x"])] = out
            n_sims[0] += 1
            X_train.append(out["x"])
            Y_train.append(math.log10(max(out["cost"], 1e-3)))
            res[i] = out
        for i, r in enumerate(res):
            if isinstance(r, tuple) and r[0] == "dup":
                res[i] = res[r[1]]
        return res

    traj = []

    if run_sim.w_unit(base):
        # ---- 그리드 모델: 정수 좌표 하강 — comparator 쪽과 같은 패턴 -------
        s0 = run_sim.w_unit(base)
        NMAX = int(round(10 ** HI / s0))
        budget = pop * gens + pop
        cur = [min(NMAX, max(1, round(base["devices"][k]["w_um"] / s0))) for k in keys]

        def x_of(ns):
            return [math.log10(v * s0) for v in ns]

        cur_e = evaluate_many([x_of(cur)])[0]

        def rec(tag, e, ns):
            m = e["m"]
            stacks_note = " ".join(f"{k} {n}" for k, n in zip(keys, ns))
            traj.append({"action": f"{tag}: {m['f_osc_ghz']}GHz, {m['power_uw']}µW"
                                    + ("" if m["oscillates"] else " (no osc)") + f" · stacks {stacks_note}",
                         "f_osc_ghz": m["f_osc_ghz"], "power_uw": m["power_uw"],
                         "oscillates": m["oscillates"], "params": copy.deepcopy(e["p"]["devices"])})

        rec("CD start", cur_e, cur)
        coarse = True
        for pass_i in range(1, 13):
            improved = False
            for ci in range(len(keys)):
                b_n = cur[ci]
                if coarse:
                    cands = sorted({max(1, min(NMAX, round(b_n * f)))
                                    for f in (0.5, 0.67, 0.8, 1.25, 1.5, 2.0)} - {b_n})
                else:
                    cands = [v for v in (b_n - 1, b_n + 1) if 1 <= v <= NMAX]
                if not cands:
                    continue
                trials = []
                for v in cands:
                    t = list(cur)
                    t[ci] = v
                    trials.append(x_of(t))
                evs = evaluate_many(trials)   # 한 좌표의 이동 후보들을 병렬 평가
                bi2 = min(range(len(evs)), key=lambda i: evs[i]["cost"])
                if evs[bi2]["cost"] < cur_e["cost"]:
                    cur[ci], cur_e, improved = cands[bi2], evs[bi2], True
                if n_sims[0] >= budget:
                    break
            rec(f"CD pass {pass_i} ({'coarse ×' if coarse else 'fine ±1'})", cur_e, cur)
            if n_sims[0] >= budget:
                break
            if not improved:
                if coarse:
                    coarse = False
                else:
                    break
        best = cur_e
    else:
        base_x = [max(LO, min(HI, math.log10(base["devices"][k]["w_um"]))) for k in keys]
        pop_x = [base_x] + [[rng.uniform(LO, HI) for _ in keys] for _ in range(pop - 1)]
        pop_e = evaluate_many(pop_x)

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
            _fit_gp()   # refit surrogate on all SPICE-evaluated points so far
            trials = []
            for i in range(pop):
                a, b, c = rng.sample([j for j in range(pop) if j != i], 3)
                jr = rng.randrange(len(keys))
                trial = [max(LO, min(HI, pop_x[a][j] + F * (pop_x[b][j] - pop_x[c][j]))) if (rng.random() < CR or j == jr) else pop_x[i][j]
                         for j in range(len(keys))]
                if _reject(trial, pop_e[i]["cost"]):
                    n_skip[0] += 1          # surrogate is confident it's worse — skip SPICE
                    continue
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
    skip_note = f", {n_skip[0]} surrogate-skipped" if n_skip[0] else ""
    traj.append({"action": f"confirm + tuning sweep · {n_sims[0]} SPICE evals{skip_note}",
                 "f_osc_ghz": m["f_osc_ghz"], "power_uw": m["power_uw"],
                 "oscillates": m["oscillates"], "params": copy.deepcopy(fin["devices"])})
    return {"trajectory": traj, "final_params": fin, "nominal": m, "tuning": tuning,
            "success": success, "target_f_ghz": f_t, "n_sims": n_sims[0], "n_surrogate_skips": n_skip[0],
            # gaa2nm: 자동 사이징이 실제로 찾은 것 = 소자별 나노시트 스택 수(정수)
            "final_stacks": _stacks(fin) if run_sim.w_unit(base) else None}


def vco_pvt(params):
    """VCO across 27 PVT corners: process SS/TT/FF (±50mV Vth via delvto) ×
    temp −40/27/125 × VDD 0.9/1.0/1.1×. Frequency + does-it-oscillate per corner."""
    p = vco_sim._full(params)
    base_vdd = float(p["vdd"])
    _sk = 0.05 * run_sim.skew_scale(params)
    specs = []
    for proc, ns, ps in (("SS", _sk, _sk), ("TT", 0.0, 0.0), ("FF", -_sk, -_sk), ("SF", _sk, -_sk), ("FS", -_sk, _sk)):
        for t in (-40, 27, 125):
            for vf in (0.9, 1.0, 1.1):
                specs.append((proc, t, vf, round(base_vdd * vf, 3), ns, ps))

    def _corner(s):
        proc, t, vf, vdd, ns, ps = s
        m = vco_sim.measure_vco({**params, "vdd": vdd, "temp": t, "nskew": ns, "pskew_p": ps})
        return {"process": proc, "temp": t, "v_frac": vf, "vdd": vdd,
                "f_osc_ghz": m["f_osc_ghz"], "oscillates": m["oscillates"], "power_uw": m["power_uw"]}

    corners = _pmap(_corner, specs)
    fs = [c["f_osc_ghz"] for c in corners if c["f_osc_ghz"] is not None]
    return {"corners": corners, "base_vdd": base_vdd,
            "f_min_ghz": min(fs) if fs else None, "f_max_ghz": max(fs) if fs else None,
            "any_nonosc": any(not c["oscillates"] for c in corners)}


def optimize_vco_pareto(base, pop=16, gens=6, seed=9):
    """Multi-objective **NSGA-II** for the ring VCO: the power ↔ frequency
    trade-off (minimize [power, -f_osc]) subject to must-oscillate. Returns the
    non-dominated front so the UI can plot best-power-per-frequency."""
    import random
    rng = random.Random(seed)
    LO, HI = math.log10(0.5), math.log10(40.0)
    keys = vco_sim.DEV_KEYS

    def make(x):
        p = copy.deepcopy(base)
        for i, k in enumerate(keys):
            p["devices"][k]["w_um"] = round(10 ** x[i], 2)
        return _snap_w(p)   # gaa2nm: 시트 그리드 스냅 — 표시값 = 시뮬값

    def ev(x):
        p = make(x)
        m = vco_sim.measure_vco(p)
        f, pw, osc = m["f_osc_ghz"], m["power_uw"] or 1e6, m["oscillates"]
        cv = 0.0 if (osc and f is not None) else 1.0
        return {"x": list(x), "p": p, "f": [pw, -(f or 0.0)], "cv": cv, "m": m}

    def dominates(a, b):
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

    init = [[max(LO, min(HI, math.log10(base["devices"][k]["w_um"]))) for k in keys]]
    init += [[rng.uniform(LO, HI) for _ in keys] for _ in range(pop - 1)]
    pop_e = _pmap(ev, init)
    for _ in range(gens):
        trials = []
        for _ in range(pop):
            a, b, c = rng.sample(range(pop), 3)
            trials.append([max(LO, min(HI, pop_e[a]["x"][j] + 0.6 * (pop_e[b]["x"][j] - pop_e[c]["x"][j]))) for j in range(len(keys))])
        kids = _pmap(ev, trials)
        comb = pop_e + kids
        fronts = nondom_sort(comb)
        newp = []
        for fr in fronts:
            if len(newp) + len(fr) <= pop:
                newp += fr
            else:
                d = crowding(comb, fr)
                newp += sorted(fr, key=lambda i: -d[i])[:pop - len(newp)]
                break
        pop_e = [comb[i] for i in newp]

    front = [pop_e[i] for i in nondom_sort(pop_e)[0] if pop_e[i]["cv"] == 0.0]
    front.sort(key=lambda e: e["f"][0])
    pts = [{"power_uw": e["m"]["power_uw"], "f_osc_ghz": e["m"]["f_osc_ghz"],
            "devices": copy.deepcopy(e["p"]["devices"])} for e in front]
    allpts = [{"power_uw": e["m"]["power_uw"], "f_osc_ghz": e["m"]["f_osc_ghz"], "feasible": e["cv"] == 0.0} for e in pop_e]
    return {"front": pts, "all": allpts}


def vco_fullflow(base, targets):
    """End-to-end VCO sign-off: DE+GP auto-size → post-layout parasitic re-sim →
    PVT sign-off → GDSII layout + rule DRC — mirrors the comparator full flow."""
    opt = optimize_vco(base, targets)
    fin = opt["final_params"]
    stages = [{"name": "Auto-size — DE + GP surrogate", "ok": bool(opt["success"]),
               "detail": f"{opt['nominal']['f_osc_ghz']}GHz, {opt['nominal']['power_uw']}µW, {opt['n_sims']} SPICE evals"}]
    # post-layout parasitic re-sim
    pc = layout.extract_vco_parasitics(fin)
    sch = vco_sim.measure_vco(fin)
    pl = vco_sim.measure_vco({**fin, "cload_ff": fin["cload_ff"] + pc["c_node_ff"]})
    stages.append({"name": "Post-layout parasitics", "ok": bool(pl["oscillates"]),
                   "detail": f"f {sch['f_osc_ghz']}→{pl['f_osc_ghz']}GHz (+{pc['c_node_ff']}fF/node)"})
    # PVT sign-off (representative corners)
    reps = [("SS", 0.05, 125, 0.9), ("TT", 0.0, 27, 1.0), ("FF", -0.05, -40, 1.1)]
    bv = float(fin["vdd"])

    def _rep(r):
        proc, ps, t, vf = r
        m = vco_sim.measure_vco({**fin, "vdd": round(bv * vf, 3), "temp": t, "pskew": ps})
        return {"process": proc, "temp": t, "v_frac": vf, "f_osc_ghz": m["f_osc_ghz"], "oscillates": m["oscillates"]}

    pvt_c = _pmap(_rep, reps)
    pvt_ok = all(c["oscillates"] for c in pvt_c)
    stages.append({"name": "PVT sign-off (3 corners)", "ok": pvt_ok,
                   "detail": "oscillates at all corners" if pvt_ok else "fails to oscillate at a corner"})
    # layout + DRC
    lay = layout.generate_vco_layout(fin)
    lay_ok = bool(lay["drc"]["clean"])
    stages.append({"name": "Layout + DRC (GDSII)", "ok": lay_ok,
                   "detail": f"cell {lay['area_um2']}µm², {'DRC clean' if lay_ok else str(lay['drc']['n_violations']) + ' DRC violations'}"})
    return {"stages": stages, "final_params": fin, "nominal": opt["nominal"], "tuning": opt["tuning"],
            "overall": all(s["ok"] for s in stages), "layout": lay, "pvt": pvt_c, "par_caps": pc}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _text(self, s, code=200):
        body = s.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            if self.path == "/api/spice/run":
                payload = self._read_json()
                self._json(run_raw_netlist(str(payload.get("netlist", ""))))
            elif self.path == "/api/agent/chat":
                payload = self._read_json()
                self._json(agent_chat(str(payload.get("message", "")),
                                      payload.get("sessionId")))
            elif self.path == "/api/netlist/parse":
                payload = self._read_json()
                self._json(parse_netlist_text(str(payload.get("netlist", ""))))
            elif self.path == "/api/netlist":
                # 현재 파라미터의 SPICE 덱(.sp)을 그대로 반환 — 직접 ngspice 실행용
                payload = self._read_json()
                base = payload.get("params", {})
                full = copy.deepcopy(run_sim.DEFAULT_PARAMS)
                full.update({k: v for k, v in base.items() if k != "devices"})
                full["devices"] = run_sim.merge_devices(base.get("devices"))
                self._text(run_sim.gen_netlist(full, vdiff=float(payload.get("vdiff", 0.01))))
            elif self.path == "/api/simulate":
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
                # _full 로 model 등 비소자 파라미터까지 병합(gaa2nm 나노시트 그리드 룰 선택)
                self._json(layout.generate_layout(run_sim._full(payload.get("params", {}))))
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
            elif self.path == "/api/wicked/wcd":
                payload = self._read_json()
                self._json(wicked.worst_case_distance(payload.get("params", {}),
                                                      payload.get("targets"),
                                                      n_samples=int(payload.get("n_samples", 24)),
                                                      seed=int(payload.get("seed", 19))))
            elif self.path == "/api/wicked/mismatch":
                payload = self._read_json()
                self._json(wicked.mismatch_budget(payload.get("params", {})))
            elif self.path == "/api/wicked/importance":
                payload = self._read_json()
                self._json(wicked.importance_sampling_yield(payload.get("params", {}),
                                                            payload.get("targets"),
                                                            n=int(payload.get("n", 24)),
                                                            shift_beta=payload.get("shift_beta"),
                                                            seed=int(payload.get("seed", 31))))
            elif self.path == "/api/wicked/optimize":
                payload = self._read_json()
                self._json(wicked.robust_optimize(payload.get("params", {}),
                                                  payload.get("targets"),
                                                  rounds=int(payload.get("rounds", 3)),
                                                  seed=int(payload.get("seed", 47))))
            elif self.path == "/api/wicked/screening":
                payload = self._read_json()
                self._json(wicked.parameter_screening(payload.get("params", {}),
                                                      payload.get("targets"),
                                                      delta=float(payload.get("delta", 0.15))))
            elif self.path == "/api/wicked/yieldsweep":
                payload = self._read_json()
                self._json(wicked.yield_sweep(payload.get("params", {}),
                                             payload.get("targets"),
                                             n_points=int(payload.get("n_points", 7)),
                                             seed=int(payload.get("seed", 53))))
            elif self.path == "/api/wicked/yop":
                payload = self._read_json()
                self._json(wicked.yop_optimize(payload.get("params", {}),
                                               payload.get("targets"),
                                               iterations=int(payload.get("iterations", 3)),
                                               seed=int(payload.get("seed", 71))))
            elif self.path == "/api/wicked/postlayout":
                payload = self._read_json()
                self._json(wicked.postlayout_wcd(payload.get("params", {}),
                                                 payload.get("targets"),
                                                 n_samples=int(payload.get("n_samples", 12)),
                                                 seed=int(payload.get("seed", 91))))
            elif self.path == "/api/wicked/corners":
                payload = self._read_json()
                self._json(wicked.worst_case_corners(payload.get("params", {}),
                                                     payload.get("targets")))
            elif self.path == "/api/wicked/dno":
                payload = self._read_json()
                self._json(wicked.dno_refine(payload.get("params", {}),
                                             payload.get("targets"),
                                             iterations=int(payload.get("iterations", 4))))
            elif self.path == "/api/wicked/fullflow":
                payload = self._read_json()
                self._json(wicked.wicked_flow(payload.get("params", {}),
                                              payload.get("targets"),
                                              dno_iterations=int(payload.get("dno_iterations", 4)),
                                              wcd_samples=int(payload.get("wcd_samples", 24)),
                                              seed=int(payload.get("seed", 19)),
                                              importance_samples=int(payload.get("importance_samples", 8))))
            elif self.path == "/api/vco/wicked/verdict":
                payload = self._read_json()
                self._json(vco_wicked.nominal_verdict(payload.get("params", {}), payload.get("targets")))
            elif self.path == "/api/vco/wicked/screening":
                payload = self._read_json()
                self._json(vco_wicked.parameter_screening(payload.get("params", {}),
                                                          payload.get("targets"),
                                                          delta=float(payload.get("delta", 0.15))))
            elif self.path == "/api/vco/wicked/wcd":
                payload = self._read_json()
                self._json(vco_wicked.worst_case_distance(payload.get("params", {}),
                                                          payload.get("targets"),
                                                          n_samples=int(payload.get("n_samples", 24)),
                                                          seed=int(payload.get("seed", 19))))
            elif self.path == "/api/vco/wicked/mismatch":
                payload = self._read_json()
                self._json(vco_wicked.mismatch_mc(payload.get("params", {}),
                                                  n=int(payload.get("n", 16)),
                                                  seed=int(payload.get("seed", 7))))
            elif self.path == "/api/vco/wicked/yieldsweep":
                payload = self._read_json()
                self._json(vco_wicked.yield_sweep(payload.get("params", {}),
                                                  payload.get("targets"),
                                                  n_points=int(payload.get("n_points", 7)),
                                                  n_mc=int(payload.get("n_mc", 6)),
                                                  seed=int(payload.get("seed", 53))))
            elif self.path == "/api/vco/wicked/dno":
                payload = self._read_json()
                self._json(vco_wicked.dno_refine(payload.get("params", {}),
                                                 payload.get("targets"),
                                                 iterations=int(payload.get("iterations", 4))))
            elif self.path == "/api/vco/wicked/yop":
                payload = self._read_json()
                self._json(vco_wicked.yop_optimize(payload.get("params", {}),
                                                   payload.get("targets"),
                                                   iterations=int(payload.get("iterations", 3)),
                                                   seed=int(payload.get("seed", 71))))
            elif self.path == "/api/vco/wicked/postlayout":
                payload = self._read_json()
                self._json(vco_wicked.postlayout_wcd(payload.get("params", {}),
                                                     payload.get("targets"),
                                                     n_samples=int(payload.get("n_samples", 8)),
                                                     seed=int(payload.get("seed", 91))))
            elif self.path == "/api/vco/wicked/corners":
                payload = self._read_json()
                self._json(vco_wicked.worst_case_corners(payload.get("params", {}),
                                                         payload.get("targets")))
            elif self.path == "/api/vco/wicked/fullflow":
                payload = self._read_json()
                self._json(vco_wicked.wicked_flow(payload.get("params", {}),
                                                  payload.get("targets"),
                                                  dno_iterations=int(payload.get("dno_iterations", 4)),
                                                  wcd_samples=int(payload.get("wcd_samples", 16)),
                                                  mc_samples=int(payload.get("mc_samples", 8)),
                                                  seed=int(payload.get("seed", 19))))
            elif self.path == "/api/maxfclk":
                payload = self._read_json()
                self._json(run_sim.max_fclk_sweep(payload.get("params", {})))
            elif self.path == "/api/vco/netlist":
                payload = self._read_json()
                self._text(vco_sim.gen_vco_netlist(vco_sim._full(payload.get("params", {}))))
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
            elif self.path == "/api/vco/waveform":
                payload = self._read_json()
                self._json(vco_sim.capture_vco_waveform(payload.get("params", {})))
            elif self.path == "/api/vco/pvt":
                payload = self._read_json()
                self._json(vco_pvt(payload.get("params", {})))
            elif self.path == "/api/vco/pushing":
                payload = self._read_json()
                self._json(vco_sim.vco_pushing(payload.get("params", {})))
            elif self.path == "/api/vco/phasenoise":
                payload = self._read_json()
                self._json(vco_sim.phase_noise(payload.get("params", {})))
            elif self.path == "/api/vco/layout":
                payload = self._read_json()
                self._json(layout.generate_vco_layout(vco_sim._full(payload.get("params", {}))))
            elif self.path == "/api/vco/postlayout":
                payload = self._read_json()
                p = vco_sim._full(payload.get("params", {}))
                pc = layout.extract_vco_parasitics(p)
                sch = vco_sim.capture_vco_waveform(p)
                pl = vco_sim.capture_vco_waveform({**p, "cload_ff": p["cload_ff"] + pc["c_node_ff"]})
                self._json({"schematic": sch, "postlayout": pl, "par_caps": pc})
            elif self.path == "/api/vco/pareto":
                payload = self._read_json()
                self._json(optimize_vco_pareto(vco_sim._full(payload.get("params", {}))))
            elif self.path == "/api/vco/fullflow":
                payload = self._read_json()
                self._json(vco_fullflow(vco_sim._full(payload.get("params", {})), payload.get("targets") or {"f_ghz": 1.5}))
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
                cmap = {"SS": "ss", "TT": "tt", "FF": "ff", "SF": "sf", "FS": "fs"}
                # 5개 공정 코너 — 정렬(SS/TT/FF) + 교차(SF=slow N/fast P, FS=fast N/slow P)
                # gaa2nm(|Vth|=0.20V)은 ±25mV, 45nm 급은 ±50mV 스큐
                _sk = 0.05 * run_sim.skew_scale(prm)
                specs = []
                for pl, ns, ps in (("SS", _sk, _sk), ("TT", 0.0, 0.0), ("FF", -_sk, -_sk),
                                   ("SF", _sk, -_sk), ("FS", -_sk, _sk)):
                    for t in (-40, 27, 125):
                        for vf in (0.9, 1.0, 1.1):
                            vdd = round(base_vdd * vf, 3)
                            proc = {"corner": cmap[pl]} if sky else {"nskew": ns, "pskew_p": ps}   # real PDK corner vs Vth skew
                            specs.append((pl, t, vf, vdd, proc))

                def _corner(s):
                    pl, t, vf, vdd, proc = s
                    nom = run_sim.run_sim({**prm, "vdd": vdd, "temp": t, **proc}, do_offset=False)["nominal"]
                    return {"process": pl, "temp": t, "v_frac": vf, "vdd": vdd,
                            "decision_time_ps": nom.get("decision_time_ps"),
                            "power_uw": nom.get("power_uw"),
                            "functional": bool(nom.get("functional"))}

                corners = _pmap(_corner, specs)   # 45 independent corners (5 process x 3T x 3V), parallel
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

#!/usr/bin/env python3
"""
vco_sim.py -- MOSFET current-starved ring VCO backend, sharing the run_sim
ngspice plumbing so the same "simulate -> evaluate -> optimize" loop that sizes
the StrongARM comparator also sizes a VCO.

Topology: an N-stage (odd) ring of current-starved CMOS inverters. Each stage is
  vdd - Mbp(vbp) - Mp(in) - out - Mn(in) - Mbn(vctrl) - gnd
The control voltage V_ctrl sets the tail current (via an NMOS ref mirrored to a
diode PMOS -> vbp), which sets the per-stage delay t_d ~ C_L*VDD/I_D, hence the
oscillation frequency f = 1/(2*N*t_d). So V_ctrl -> frequency = a real VCO.

Measured metrics:
    f_osc_ghz   - oscillation frequency (from the period of V(o1))
    oscillates  - did it actually swing rail-to-rail and give a valid period
    power_uw    - average supply power
Plus a V_ctrl tuning sweep -> tuning range, Kvco.

PTM 45 nm bulk model (nmos/pmos), like run_sim's default. (sky130 subckt support
is a documented extension: swap the M-lines for X-subckt instantiation.)
"""
import copy
import math

import run_sim  # reuse _run, _parse, _model_header, MODEL_PATH, NGSPICE

VCO_DEFAULTS = {
    "vdd": 1.0,
    "vctrl": 0.6,          # nominal control voltage (V)
    "n_stages": 5,         # odd number of ring stages
    "cload_ff": 3.0,       # per-stage load capacitance
    "devices": {
        "invp":    {"w_um": 2.0, "l_nm": 45, "m": 2},   # core PMOS
        "invn":    {"w_um": 1.0, "l_nm": 45, "m": 2},   # core NMOS
        "starvep": {"w_um": 2.0, "l_nm": 45, "m": 2},   # PMOS current-starve
        "starven": {"w_um": 1.0, "l_nm": 45, "m": 1},   # NMOS current-starve
    },
}
DEV_KEYS = ["invp", "invn", "starvep", "starven"]


def _full(params):
    p = dict(VCO_DEFAULTS)
    p.update({k: v for k, v in (params or {}).items() if k != "devices"})
    base = VCO_DEFAULTS["devices"]
    ov = (params or {}).get("devices") or {}
    p["devices"] = {k: {**base[k], **(ov.get(k) or {})} for k in base}
    return p


def _dev(d):
    return f"W={d['w_um']}u L={d['l_nm']}n M={d['m']}"


def gen_vco_netlist(p, vctrl=None, tstop_ns=25.0, tstep_ps=2.0):
    d = p["devices"]
    vdd = p["vdd"]
    vc = p["vctrl"] if vctrl is None else vctrl
    N = int(p["n_stages"])
    cl = p["cload_ff"]
    hdr = run_sim._model_header(p)          # PTM .include (or sky130 .lib)
    invp, invn = _dev(d["invp"]), _dev(d["invn"])
    sp, sn = _dev(d["starvep"]), _dev(d["starven"])

    lines = [
        "MOSFET current-starved ring VCO (generated)",
        f".option temp={p.get('temp', 27)}",
        hdr,
        f"Vdd vdd 0 {vdd}",
        f"Vc vctrl 0 {vc}",
        "* bias: Vctrl -> tail current, mirrored to a diode PMOS -> vbp",
        f"Mpref vbp vbp vdd vdd pmos {sp}",
        f"Mnref vbp vctrl 0 0 nmos {sn}",
    ]
    for i in range(1, N + 1):
        prev = N if i == 1 else i - 1      # ring: in_1 = o_N
        lines += [
            f"Mbp{i} a{i} vbp vdd vdd pmos {sp}",
            f"Mp{i}  o{i} o{prev} a{i} vdd pmos {invp}",
            f"Mn{i}  o{i} o{prev} b{i} 0 nmos {invn}",
            f"Mbn{i} b{i} vctrl 0 0 nmos {sn}",
            f"Co{i} o{i} 0 {cl}f",
        ]
    # kick-start: alternate node initial conditions
    ic = " ".join(f"v(o{i})={vdd if i % 2 else 0}" for i in range(1, N + 1))
    lines += [
        f".ic {ic}",
        ".control",
        "set noaskquit",
        f"tran {tstep_ps}p {tstop_ns}n uic",
        # period across 5 cycles (rise 3..8) of o1, measured after startup settles
        f"meas tran per TRIG v(o1) VAL='{vdd/2.0}' RISE=3 TARG v(o1) VAL='{vdd/2.0}' RISE=8",
        "meas tran vpp PP v(o1)",
        f"meas tran iavg AVG i(Vdd) FROM={tstop_ns*0.2}n TO={tstop_ns}n",
        ".endc",
        ".end",
    ]
    return "\n".join(lines) + "\n"


def measure_vco(params, vctrl=None):
    """Oscillation frequency / power / did-it-oscillate at one V_ctrl."""
    p = _full(params)
    vdd = p["vdd"]
    out = run_sim._run(gen_vco_netlist(p, vctrl=vctrl))
    per = run_sim._parse(out, "per")        # time for 5 periods
    vpp = run_sim._parse(out, "vpp")
    iavg = run_sim._parse(out, "iavg")
    osc = per is not None and per > 0 and vpp is not None and vpp > 0.4 * vdd
    f_ghz = round(5.0 / per / 1e9, 4) if (osc and per) else None
    return {
        "f_osc_ghz": f_ghz,
        "oscillates": bool(osc),
        "power_uw": round(abs(iavg) * vdd * 1e6, 3) if iavg is not None else None,
        "vpp_v": round(vpp, 3) if vpp is not None else None,
        "n_stages": int(p["n_stages"]),
        "vctrl_v": round(p["vctrl"] if vctrl is None else vctrl, 4),
    }


def vco_tuning(params, points=9):
    """Sweep V_ctrl across its usable range -> f(V_ctrl), tuning range, Kvco."""
    p = _full(params)
    vdd = p["vdd"]
    vlo, vhi = 0.30 * vdd, 0.98 * vdd
    vs = [round(vlo + (vhi - vlo) * i / (points - 1), 4) for i in range(points)]
    pts = []
    for v in vs:
        m = measure_vco(params, vctrl=v)
        pts.append({"vctrl_v": v, "f_osc_ghz": m["f_osc_ghz"],
                    "power_uw": m["power_uw"], "oscillates": m["oscillates"]})
    fs = [(pt["vctrl_v"], pt["f_osc_ghz"]) for pt in pts if pt["f_osc_ghz"]]
    out = {"points": pts, "f_min_ghz": None, "f_max_ghz": None,
           "tuning_pct": None, "kvco_ghz_per_v": None, "center_ghz": None}
    if len(fs) >= 2:
        fmin, fmax = fs[0][1], fs[-1][1]
        for _, f in fs:
            fmin, fmax = min(fmin, f), max(fmax, f)
        center = 0.5 * (fmin + fmax)
        # Kvco from the linear fit over the oscillating points
        n = len(fs)
        sx = sum(v for v, _ in fs); sy = sum(f for _, f in fs)
        sxx = sum(v * v for v, _ in fs); sxy = sum(v * f for v, f in fs)
        denom = n * sxx - sx * sx
        kvco = (n * sxy - sx * sy) / denom if abs(denom) > 1e-12 else None
        out.update({
            "f_min_ghz": round(fmin, 4), "f_max_ghz": round(fmax, 4),
            "center_ghz": round(center, 4),
            "tuning_pct": round(100.0 * (fmax - fmin) / center, 1) if center else None,
            "kvco_ghz_per_v": round(kvco, 3) if kvco is not None else None,
        })
    return out


def run_vco(params, do_tuning=False):
    p = _full(params)
    r = {"nominal": measure_vco(params), "params": p}
    if do_tuning:
        r["tuning"] = vco_tuning(params)
    return r


if __name__ == "__main__":
    import json
    import sys
    if "--tune" in sys.argv:
        print(json.dumps(vco_tuning({}), indent=2))
    else:
        print(json.dumps(measure_vco({}), indent=2))

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
import os
import re
import statistics
import tempfile
from concurrent.futures import ThreadPoolExecutor

import run_sim  # reuse _run, _parse, _model_header, MODEL_PATH, NGSPICE

_WORKERS = max(2, min(8, (os.cpu_count() or 4)))


def _pmap(fn, items):
    """Parallel map (ngspice subprocess releases the GIL) preserving order."""
    items = list(items)
    if len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        return list(ex.map(fn, items))

VCO_DEFAULTS = {
    "vdd": 1.0,
    "vctrl": 0.6,          # nominal control voltage (V)
    "n_stages": 3,         # odd number of ring stages
    "cload_ff": 3.0,       # per-stage load capacitance
    "topology": "xcpl",    # 기본: 교차결합+리셋(xcpl). "starved" 는 레거시 호환용
    "trst_ns": 2.0,        # xcpl only: reset (rstb low) release time
    "devices": {
        "invp":    {"w_um": 2.0, "l_nm": 45, "m": 2},   # core PMOS (P0)
        "invn":    {"w_um": 1.0, "l_nm": 45, "m": 2},   # core NMOS (N0)
        "starvep": {"w_um": 2.0, "l_nm": 45, "m": 2},   # PMOS current-starve
        "starven": {"w_um": 1.0, "l_nm": 45, "m": 1},   # NMOS current-starve
        "xcplp":   {"w_um": 0.4, "l_nm": 45, "m": 1},   # P1 cross-coupled PMOS (xcpl)
        "rstp":    {"w_um": 2.0, "l_nm": 45, "m": 2},   # reset PMOS (xcpl)
    },
}
DEV_KEYS = ["invp", "invn", "starvep", "starven"]   # optimizer dims (starved topology)


def _full(params):
    p = dict(VCO_DEFAULTS)
    p.update({k: v for k, v in (params or {}).items() if k != "devices"})
    base = VCO_DEFAULTS["devices"]
    ov = (params or {}).get("devices") or {}
    p["devices"] = {k: {**base[k], **(ov.get(k) or {})} for k in base}
    return p


def _dev(d, vt):
    # delvto = process-corner Vth shift (0 nominal), set via .param dvtn/dvtp
    return f"W={d['w_um']}u L={d['l_nm']}n M={d['m']} delvto={{{vt}}}"


def _dev2(p, dd, kind):
    """모델명을 포함한 소자 우변. asap7 은 BSIM-CMG(OSDI): NFIN 핀 양자화 +
    delvtrand(+가 Vth ↓ — delvto 관례와 부호 반대, .param 에서 반전됨)."""
    vt = "dvtn" if kind == "n" else "dvtp"
    if p.get("model") == "asap7":
        mdl = "nmos_lvt" if kind == "n" else "pmos_lvt"
        return f"{mdl} l={dd['l_nm']}n nfin={run_sim.nfin_of(dd)} delvtrand={{{vt}}}"
    return f"{'nmos' if kind == 'n' else 'pmos'} {_dev(dd, vt)}"


def _mp(p):
    """OSDI 소자(asap7)의 인스턴스 접두('N') — ngspice OSDI 소자 문자."""
    return "N" if p.get("model") == "asap7" else ""


def _osdi_line(p):
    return f"pre_osdi {run_sim.ASAP7_OSDI}" if p.get("model") == "asap7" else "* no osdi"


def gen_vco_netlist(p, vctrl=None, tstop_ns=18.0, tstep_ps=2.0, wavefile=None):
    if p.get("topology", "starved") == "xcpl":
        return _gen_xcpl_netlist(p, vctrl, tstop_ns, tstep_ps, wavefile)
    d = run_sim.quantize_devices(p)   # gaa2nm: W → 시트 단위(0.5µ) × finger
    vdd = p["vdd"]
    vc = p["vctrl"] if vctrl is None else vctrl
    N = int(p["n_stages"])
    cl = p["cload_ff"]
    pskew = p.get("pskew", 0.0)             # process corner: +slow (SS), -fast (FF)
    nskew = p.get("nskew", pskew)           # 교차 코너(SF/FS)용 독립 스큐 — 첫 글자=N, 둘째=P
    pskew_p = p.get("pskew_p", pskew)
    hdr = run_sim._model_header(p)          # PTM .include (or sky130 .lib)
    invp, invn = _dev2(p, d["invp"], "p"), _dev2(p, d["invn"], "n")
    sp_p, sn_n = _dev2(p, d["starvep"], "p"), _dev2(p, d["starven"], "n")
    mp = _mp(p)
    wave = f"wrdata {wavefile} v(o1) v(o2)" if wavefile else ""

    lines = [
        "MOSFET current-starved ring VCO (generated)",
        f".option temp={p.get('temp', 27)}",
        f".param dvtn={-nskew if p.get('model') == 'asap7' else nskew} dvtp={-pskew_p}",
        hdr,
        f"Vdd vdd 0 {vdd}",
        f"Vc vctrl 0 {vc}",
        "* bias: Vctrl -> tail current, mirrored to a diode PMOS -> vbp",
        f"{mp}Mpref vbp vbp vdd vdd {sp_p}",
        f"{mp}Mnref vbp vctrl 0 0 {sn_n}",
    ]
    for i in range(1, N + 1):
        prev = N if i == 1 else i - 1      # ring: in_1 = o_N
        lines += [
            f"{mp}Mbp{i} a{i} vbp vdd vdd {sp_p}",
            f"{mp}Mp{i}  o{i} o{prev} a{i} vdd {invp}",
            f"{mp}Mn{i}  o{i} o{prev} b{i} 0 {invn}",
            f"{mp}Mbn{i} b{i} vctrl 0 0 {sn_n}",
            f"Co{i} o{i} 0 {cl}f",
        ]
    # kick-start: alternate node initial conditions
    ic = " ".join(f"v(o{i})={vdd if i % 2 else 0}" for i in range(1, N + 1))
    lines += [
        f".ic {ic}",
        ".control",
        "set noaskquit",
        _osdi_line(p),
        f"tran {tstep_ps}p {tstop_ns}n uic",
        # period across 5 CYCLES (rise 3..8): f_osc = 5/per — NOT 1/per
        f"meas tran per TRIG v(o1) VAL='{vdd/2.0}' RISE=3 TARG v(o1) VAL='{vdd/2.0}' RISE=8",
        "meas tran vpp PP v(o1)",
        f"meas tran iavg AVG i(Vdd) FROM={tstop_ns*0.2}n TO={tstop_ns}n",
        wave,
        ".endc",
        ".end",
    ]
    return "\n".join(lines) + "\n"


def _gen_xcpl_netlist(p, vctrl=None, tstop_ns=18.0, tstep_ps=2.0, wavefile=None):
    """Cross-coupled pseudo-differential ring VCO with a hardware reset start-up
    (topology="xcpl"; cf. the Mansuri-style CCO cell, plus a reset PMOS).

    Two current-starved inverter rings (odd N per rail: o1..oN and ob1..obN)
    run in anti-phase, tied at every stage by a weak cross-coupled PMOS pair.
    Per stage and rail (schematic naming):
        N0 -> Mn*/Mnb*   core inverter NMOS
        P0 -> Mp*/Mpb*   core inverter PMOS
        P1 -> Mx*/Mxb*   cross-coupled PMOS (drain = own node, gate = complement)
    One reset PMOS (Mrst, gate = rstb) clamps o1 high while rstb is low; the
    rings then settle to the unique complementary pattern (only stage 1 fights
    the clamp, and P1 of stage 1 reinforces it), so oscillation starts
    deterministically when rstb rises at trst_ns — no .ic kick-start, and the
    t=0 DC operating point IS the reset state. V_ctrl tunes the frequency via
    the same vbp/vctrl starve rails as the "starved" topology. Size P1 weak
    relative to the starved inverter drive: an oversized P1 latches the stage
    and stops the oscillation (it shows up as oscillates=False)."""
    d = run_sim.quantize_devices(p)   # gaa2nm: W → 시트 단위(0.5µ) × finger
    vdd = p["vdd"]
    vc = p["vctrl"] if vctrl is None else vctrl
    N = int(p["n_stages"])
    cl = p["cload_ff"]
    trst = p.get("trst_ns", 2.0)
    pskew = p.get("pskew", 0.0)
    nskew = p.get("nskew", pskew)
    pskew_p = p.get("pskew_p", pskew)
    hdr = run_sim._model_header(p)
    invp, invn = _dev2(p, d["invp"], "p"), _dev2(p, d["invn"], "n")
    sp_p, sn_n = _dev2(p, d["starvep"], "p"), _dev2(p, d["starven"], "n")
    xp, rp = _dev2(p, d["xcplp"], "p"), _dev2(p, d["rstp"], "p")
    mp = _mp(p)
    wave = f"wrdata {wavefile} v(o1) v(ob1)" if wavefile else ""

    lines = [
        "cross-coupled pseudo-differential ring VCO with reset (generated)",
        f".option temp={p.get('temp', 27)}",
        f".param dvtn={-nskew if p.get('model') == 'asap7' else nskew} dvtp={-pskew_p}",
        hdr,
        f"Vdd vdd 0 {vdd}",
        f"Vc vctrl 0 {vc}",
        "* bias: Vctrl -> tail current, mirrored to a diode PMOS -> vbp",
        f"{mp}Mpref vbp vbp vdd vdd {sp_p}",
        f"{mp}Mnref vbp vctrl 0 0 {sn_n}",
        f"* reset: rstb low clamps o1 to vdd, released at {trst}ns",
        f"Vrst rstb 0 PULSE(0 {vdd} {trst}n 0.05n 0.05n {tstop_ns*2}n {tstop_ns*4}n)",
        f"{mp}Mrst o1 rstb vdd vdd {rp}",
    ]
    for i in range(1, N + 1):
        prev = N if i == 1 else i - 1      # ring: in_1 = o_N (both rails)
        lines += [
            f"* stage {i}: starved inverters (N0/P0) x2 + cross-coupled P1 pair",
            f"{mp}Mbp{i}  ap{i} vbp vdd vdd {sp_p}",
            f"{mp}Mp{i}   o{i} o{prev} ap{i} vdd {invp}",
            f"{mp}Mn{i}   o{i} o{prev} bp{i} 0 {invn}",
            f"{mp}Mbn{i}  bp{i} vctrl 0 0 {sn_n}",
            f"{mp}Mbpb{i} an{i} vbp vdd vdd {sp_p}",
            f"{mp}Mpb{i}  ob{i} ob{prev} an{i} vdd {invp}",
            f"{mp}Mnb{i}  ob{i} ob{prev} bn{i} 0 {invn}",
            f"{mp}Mbnb{i} bn{i} vctrl 0 0 {sn_n}",
            f"{mp}Mx{i}   o{i} ob{i} vdd vdd {xp}",
            f"{mp}Mxb{i}  ob{i} o{i} vdd vdd {xp}",
            f"Co{i}  o{i} 0 {cl}f",
            f"Cob{i} ob{i} 0 {cl}f",
        ]
    lines += [
        ".control",
        "set noaskquit",
        _osdi_line(p),
        f"tran {tstep_ps}p {tstop_ns}n",
        # rising edges only exist after the reset release; RISE=3..8 spans 5 CYCLES
        # of settled oscillation: f_osc = 5/per — NOT 1/per
        f"meas tran per TRIG v(o1) VAL='{vdd/2.0}' RISE=3 TARG v(o1) VAL='{vdd/2.0}' RISE=8",
        "meas tran vpp PP v(o1)",
        f"meas tran iavg AVG i(Vdd) FROM={tstop_ns*0.2}n TO={tstop_ns}n",
        wave,
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
    ms = _pmap(lambda v: measure_vco(params, vctrl=v), vs)   # points are independent
    pts = [{"vctrl_v": v, "f_osc_ghz": m["f_osc_ghz"], "power_uw": m["power_uw"], "oscillates": m["oscillates"]}
           for v, m in zip(vs, ms)]
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


def capture_vco_waveform(params, npoints=400, tstop_ns=8.0):
    """Real transient of two ring nodes so the UI can plot the actual
    oscillation (starved: o1/o2; xcpl: the complementary pair o1/ob1, returned
    under the same o1/o2 keys). Returns downsampled arrays + measured period."""
    import os
    import tempfile as _tf
    p = _full(params)
    vdd = p["vdd"]
    if p.get("topology", "starved") == "xcpl":
        # the reset phase eats the head of the transient; keep the same
        # oscillation window so the RISE 3..8 period measurement still fits
        tstop_ns = tstop_ns + p.get("trst_ns", 2.0)
    fd, wf = _tf.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        out = run_sim._run(gen_vco_netlist(p, tstop_ns=tstop_ns, wavefile=wf))
        per = run_sim._parse(out, "per")
        rows = []
        with open(wf) as fh:
            for line in fh:
                c = line.split()
                if len(c) >= 4:
                    try:
                        rows.append((float(c[0]), float(c[1]), float(c[3])))
                    except ValueError:
                        continue
    finally:
        try:
            os.unlink(wf)
        except OSError:
            pass
    if not rows:
        return {"error": "no oscillation captured", "t_ns": [], "o1": [], "o2": []}
    step = max(1, len(rows) // npoints)
    s = rows[::step]
    return {
        "vdd": vdd,
        "t_ns": [round(r[0] * 1e9, 4) for r in s],
        "o1": [round(r[1], 4) for r in s],
        "o2": [round(r[2], 4) for r in s],
        "period_ns": round(per / 5.0 * 1e9, 4) if per else None,
        "f_osc_ghz": round(5.0 / per / 1e9, 4) if per else None,
    }


def vco_pushing(params, points=7, span=0.15):
    """Supply pushing: oscillation frequency vs VDD at fixed V_ctrl. Reports the
    pushing figure (GHz/V) — how much the supply moves the frequency."""
    p = _full(params)
    v0 = p["vdd"]
    vs = [round(v0 * (1 - span + 2 * span * i / (points - 1)), 4) for i in range(points)]
    ms = _pmap(lambda v: measure_vco({**params, "vdd": v}), vs)   # points are independent
    pts = [{"vdd": v, "f_osc_ghz": m["f_osc_ghz"], "oscillates": m["oscillates"]} for v, m in zip(vs, ms)]
    fs = [(pt["vdd"], pt["f_osc_ghz"]) for pt in pts if pt["f_osc_ghz"]]
    push = None
    if len(fs) >= 2:
        n = len(fs)
        sx = sum(v for v, _ in fs); sy = sum(f for _, f in fs)
        sxx = sum(v * v for v, _ in fs); sxy = sum(v * f for v, f in fs)
        denom = n * sxx - sx * sx
        push = (n * sxy - sx * sy) / denom if abs(denom) > 1e-12 else None
    return {"points": pts, "nominal_vdd": v0,
            "pushing_ghz_per_v": round(push, 3) if push is not None else None}


def phase_noise(params, offsets_hz=None, measured=True, flicker_corner_hz=1e5):
    """First-order thermal phase-noise / jitter estimate for the ring VCO.

    Each stage transition crosses threshold with timing uncertainty
    sigma_t = sqrt(kT*C)/I (thermal noise / slew rate); 2N uncorrelated
    transitions per period give period jitter sigma_T = sqrt(2N)*sigma_t. The
    single-sideband phase noise follows L(Δf) = 10log10(f0^3 * sigma_T^2 / Δf^2)
    (white-noise / 1-f^2 region). The effective node cap is derived self-
    consistently from the measured frequency (C = I*t_d/VDD, t_d = 1/(2N*f0)),
    so it needs no extra guess. Thermal-only, first-order — not a PSS/pnoise
    sign-off, but tracks the right dependence on power, f0 and N."""
    p = _full(params)
    m = measure_vco(p)
    f0g, pw = m["f_osc_ghz"], m["power_uw"]
    if not (m["oscillates"] and f0g and pw):
        return {"error": "no oscillation", "nominal": m}
    f0 = f0g * 1e9
    P = pw * 1e-6
    N = int(p["n_stages"])
    vdd = p["vdd"]
    kT = 1.380649e-23 * (p.get("temp", 27) + 273.15)
    i_stage = (P / vdd) / N                      # avg per-stage current
    t_d = 1.0 / (2 * N * f0)                      # per-stage delay
    c_eff = i_stage * t_d / vdd                   # node cap consistent with f0
    sigma_t = math.sqrt(kT * c_eff) / i_stage     # per-edge timing jitter (s)
    sigma_T = math.sqrt(2 * N) * sigma_t          # per-period jitter (s)
    if offsets_hz is None:
        offsets_hz = [1e4 * (10 ** (i / 2.0)) for i in range(0, 9)]   # 10 kHz .. 100 MHz
    fc = float(flicker_corner_hz or 0.0)   # 1/f^3 corner (assumed): flicker adds (1 + fc/Δf)
    def _L(fo):
        return 10.0 * math.log10(f0 ** 3 * sigma_T ** 2 / fo ** 2 * (1.0 + fc / fo))
    pts = [{"offset_hz": round(fo), "L_dbc": round(_L(fo), 1)} for fo in offsets_hz]
    L_1m = _L(1e6)
    fom = L_1m - 20 * math.log10(f0 / 1e6) + 10 * math.log10(P * 1e3)   # P in mW
    out = {"f0_ghz": round(f0 / 1e9, 4), "power_uw": round(pw, 2), "n_stages": N,
           "period_jitter_fs": round(sigma_T * 1e15, 2), "c_eff_ff": round(c_eff * 1e15, 3),
           "points": pts, "L_1mhz_dbc": round(L_1m, 1), "fom_db": round(fom, 1),
           "flicker_corner_hz": round(fc)}
    # SPICE-measured cross-check (trnoise jitter); best-effort
    if measured:
        try:
            m = phase_noise_measured(params)
            if "error" not in m:
                out["measured"] = m
        except Exception:
            pass
    return out


def _ring_gm(p):
    """Finite-difference gm (S) of the core inverter NMOS at mid-transition."""
    d = p["devices"]["invn"]
    vdd = p["vdd"]

    def idn(vg):
        out = run_sim._run(f'.include "{run_sim.MODEL_PATH}"\nVd d 0 {vdd/2.0}\nVg g 0 {vg}\n'
                           f'M1 d g 0 0 nmos W={d["w_um"]}u L={d["l_nm"]}n M={d["m"]}\n'
                           '.control\nop\nprint i(Vd)\n.endc\n.end\n')
        m = re.search(r"i\(vd\)\s*=\s*([-\d.eE+]+)", out, re.IGNORECASE)
        return abs(float(m.group(1))) if m else None

    i0, i1 = idn(vdd / 2.0), idn(vdd / 2.0 + 0.005)
    return (i1 - i0) / 0.005 if (i0 is not None and i1 is not None and i1 > i0) else None


def _gen_noisy_ring(p, na, tstop_ns, ntstep_ps, seed, wavefile):
    """Ring VCO netlist with a per-stage input-referred trnoise voltage source
    (amplitude `na`) in series with each inverter gate — for measured jitter."""
    d = run_sim.quantize_devices(p)   # gaa2nm: W → 시트 단위(0.5µ) × finger
    vdd, N = p["vdd"], int(p["n_stages"])
    invp, invn = _dev(d["invp"], "dvtp"), _dev(d["invn"], "dvtn")
    sp_p, sn_n = _dev(d["starvep"], "dvtp"), _dev(d["starven"], "dvtn")
    lines = ["ring VCO + per-stage input-referred trnoise",
             f".option temp={p.get('temp', 27)}", ".param dvtn=0 dvtp=0",
             run_sim._model_header(p), f"Vdd vdd 0 {vdd}", f"Vc vctrl 0 {p['vctrl']}",
             f"Mpref vbp vbp vdd vdd pmos {sp_p}", f"Mnref vbp vctrl 0 0 nmos {sn_n}"]
    for i in range(1, N + 1):
        prev = N if i == 1 else i - 1
        lines += [f"Vn{i} og{i} o{prev} 0 trnoise({na} {ntstep_ps}p 0 0)",
                  f"Mbp{i} a{i} vbp vdd vdd pmos {sp_p}",
                  f"Mp{i}  o{i} og{i} a{i} vdd pmos {invp}",
                  f"Mn{i}  o{i} og{i} b{i} 0 nmos {invn}",
                  f"Mbn{i} b{i} vctrl 0 0 nmos {sn_n}",
                  f"Co{i} o{i} 0 {p['cload_ff']}f"]
    ic = " ".join(f"v(o{i})={vdd if i % 2 else 0}" for i in range(1, N + 1))
    lines += [f".ic {ic}", ".control", "set noaskquit", f"setseed {seed}",
              f"tran {ntstep_ps}p {tstop_ns}n uic", f"wrdata {wavefile} v(o1)", ".endc", ".end"]
    return "\n".join(lines) + "\n"


def _measure_jitter_once(p, na, tstop_ns, ntstep_ps, seed):
    """One noisy transient → (f0, period-jitter σ_T) or None."""
    vdd = p["vdd"]
    fd, wf = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        run_sim._run(_gen_noisy_ring(p, na, tstop_ns, ntstep_ps, seed, wf))
        ts, vs = [], []
        with open(wf) as fh:
            for line in fh:
                c = line.split()
                if len(c) >= 2:
                    try:
                        ts.append(float(c[0])); vs.append(float(c[1]))
                    except ValueError:
                        pass
    finally:
        try:
            os.unlink(wf)
        except OSError:
            pass
    th = vdd / 2.0
    cross = [ts[k - 1] + (th - vs[k - 1]) * (ts[k] - ts[k - 1]) / (vs[k] - vs[k - 1])
             for k in range(1, len(vs)) if vs[k - 1] < th <= vs[k]]
    cross = [c for c in cross if c > 0.15 * tstop_ns * 1e-9]   # drop startup
    periods = [cross[i + 1] - cross[i] for i in range(len(cross) - 1)]
    if len(periods) < 10:
        return None
    return 1.0 / (sum(periods) / len(periods)), statistics.pstdev(periods), len(periods), cross


def _jitter_accum(cross, T0):
    """Accumulated timing jitter σ_Δt(τ) over intervals of m cycles (τ=m·T0):
    σ_Δt(m) = std of (t_{k+m} − t_k − m·T0). Its log-log slope discriminates the
    noise type — 0.5 = white (→ 1/f² phase noise), 1.0 = flicker (→ 1/f³)."""
    n = len(cross)
    mmax = max(4, n // 4)   # keep enough independent windows; beyond ~N/4 the
    out = {}                # finite-record / mean-removal bias corrupts σ(τ)
    for m in (1, 2, 4, 8, 16, 32, 64, 128):
        if m > mmax:
            break
        diffs = [cross[i + m] - cross[i] - m * T0 for i in range(n - m)]
        if len(diffs) >= 8:
            out[m] = statistics.pstdev(diffs)
    return out


def phase_noise_measured(params, tstop_ns=60.0, ntstep_ps=2.0, seeds=(1, 2, 3, 4)):
    """SPICE-measured phase noise (thermal / 1-f^2 region): inject the physical
    per-stage input-referred device noise (S_v = 4kTγ/gm, γ=2/3, via ngspice
    trnoise) and measure the period jitter directly. Averaged over several noise
    seeds (run in parallel) to tame the stochastic spread. A real cross-check of
    the analytic estimate — the circuit converts the injected noise through its
    actual switching. Starved topology only (the trnoise injection netlist
    models the single-ended starved ring)."""
    p = _full(params)
    if p.get("topology", "starved") != "starved":
        return {"error": "measured jitter supports the starved topology only"}
    gm = _ring_gm(p)
    if not gm:
        return {"error": "gm extraction failed"}
    kT = 1.380649e-23 * (p.get("temp", 27) + 273.15)
    na = math.sqrt(4 * kT * (2.0 / 3.0) / gm / (ntstep_ps * 1e-12))   # trnoise amplitude for S_v
    runs = _pmap(lambda s: _measure_jitter_once(p, na, tstop_ns, ntstep_ps, s), list(seeds))
    runs = [r for r in runs if r]
    if not runs:
        return {"error": "too few cycles measured"}
    f0 = sum(r[0] for r in runs) / len(runs)
    T0 = 1.0 / f0
    sig = [r[1] for r in runs]
    sigma_T = sum(sig) / len(sig)                       # mean period jitter over seeds
    spread = statistics.pstdev(sig) if len(sig) > 1 else 0.0
    cycles = sum(r[2] for r in runs)
    # jitter accumulation σ_Δt(τ), averaged over seeds → slope (0.5 white / 1.0 flicker)
    accs = [_jitter_accum(r[3], T0) for r in runs]
    ms = sorted(set().union(*[set(a) for a in accs])) if accs else []
    accum = []
    for m in ms:
        vals = [a[m] for a in accs if m in a]
        if vals:
            accum.append({"tau_ns": round(m * T0 * 1e9, 4), "sigma_fs": round(sum(vals) / len(vals) * 1e15, 2)})
    slope = None
    if len(accum) >= 3:
        xs = [math.log10(pt["tau_ns"]) for pt in accum]
        ys = [math.log10(pt["sigma_fs"]) for pt in accum]
        n = len(xs); sx = sum(xs); sy = sum(ys); sxx = sum(x * x for x in xs); sxy = sum(x * y for x, y in zip(xs, ys))
        denom = n * sxx - sx * sx
        slope = round((n * sxy - sx * sy) / denom, 3) if abs(denom) > 1e-12 else None
    offs = [1e4 * (10 ** (i / 2.0)) for i in range(0, 9)]
    pts = [{"offset_hz": round(fo), "L_dbc": round(10 * math.log10(f0 ** 3 * sigma_T ** 2 / fo ** 2), 1)} for fo in offs]
    return {"f0_ghz": round(f0 / 1e9, 4), "period_jitter_fs": round(sigma_T * 1e15, 2),
            "jitter_spread_fs": round(spread * 1e15, 2), "n_seeds": len(runs), "cycles": cycles, "points": pts,
            "L_1mhz_dbc": round(10 * math.log10(f0 ** 3 * sigma_T ** 2 / 1e12), 1),
            "accum": accum, "accum_slope": slope,
            "noise_type": ("thermal (1/f²)" if slope is not None and slope < 0.7 else
                           "flicker-influenced (1/f³)" if slope is not None else "n/a"),
            "method": f"SPICE trnoise measured jitter + accumulation slope, avg of {len(runs)} seeds"}


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

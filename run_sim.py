#!/usr/bin/env python3
"""
run_sim.py -- programmatic SPICE backend for StrongARM latch comparator sizing.

This is the "method 1" wrapper: it exposes a run_sim(params) -> measurements
interface that an agent (or the CLI) can call to close the sizing loop against
ngspice. It generates a parameterized StrongARM netlist, runs ngspice in batch
mode, and returns measured metrics as JSON:

    decision_time_ps  - clk edge -> outputs split to 0.7*VDD (regeneration speed)
    power_uw          - average supply power over the evaluation window
    offset_sigma_mv   - input-referred offset sigma via Monte Carlo Vth mismatch
    functional        - did the latch actually resolve to a rail

MODEL NOTE: uses a real published BSIM4 (level=54) model card -- the PTM
(Predictive Technology Model) 45 nm bulk process, models/ptm_45nm_bulk.txt.
Source: ASU Predictive Technology Model (ptm.asu.edu), ngspice-ready copy from
github.com/indra-ipd/bag_deep_ckt-1 (eval_engines/NGspice/.../45nm_bulk.txt).
PTM is a predictive academic model, not a specific foundry PDK, but it is a
genuine BSIM4 card that ngspice runs natively -- absolute numbers are 45 nm-class
realistic. (Raw SkyWater sky130 models are spectre-format and reference instance
params l/w/mult inside .model cards, which ngspice rejects; they need an
open_pdks conversion first. To use them, point MODEL_PATH at a converted
sky130 ngspice .lib and instantiate the devices as subckts.)

Usage:
    python3 run_sim.py params.json           # read params from file
    echo '{...}' | python3 run_sim.py -      # read params from stdin
    python3 run_sim.py --demo                # run with the P1_SAR_ADC seed sizing
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

def _find_ngspice():
    import shutil
    for c in ("ngspice", "/opt/homebrew/bin/ngspice", "/usr/local/bin/ngspice"):
        p = shutil.which(c) or (c if os.path.exists(c) else None)
        if p:
            return p
    return "ngspice"  # last resort; will error clearly if missing


NGSPICE = _find_ngspice()

# ---- real BSIM4 device model: PTM 45nm bulk (models nmos/pmos, level=54) ----
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "models", "ptm_45nm_bulk.txt")

# default seed = P1_SAR_ADC first-cut sizing, adapted to PTM 45nm bulk
# (VDD 0.7 V nominal, minimum L = 45 nm for this node)
DEFAULT_PARAMS = {
    "vdd": 0.7,
    "topology": "strongarm",   # "strongarm"(단일 테일) | "doubletail"(Schinkel 2단)
    "vcm_frac": 0.62,     # input common mode as fraction of vdd
    "cload_ff": 15.0,
    "avt_mv_um": 2.0,     # Pelgrom coefficient (mV*um), ~45nm-class
    "n_mc": 16,           # Monte Carlo samples for offset
    "devices": {
        "input": {"w_um": 8.0, "l_nm": 80.0, "m": 4},
        "tail":  {"w_um": 12.0, "l_nm": 45.0, "m": 6},
        "ncc":   {"w_um": 4.0, "l_nm": 45.0, "m": 2},
        "pcc":   {"w_um": 9.0, "l_nm": 45.0, "m": 4},
        "pre":   {"w_um": 4.0, "l_nm": 45.0, "m": 2},
    },
}


def _dev(d, vt="dvtn"):
    # delvto = process-corner Vth shift (0 nominal); dvtn/dvtp set via .param
    return f"W={d['w_um']}u L={d['l_nm']}n M={d['m']} delvto={{{vt}}}"


def gen_netlist(p, vdiff, dvth1=0.0, dvth2=0.0, wavefile=None):
    d = p["devices"]
    vdd = p["vdd"]
    vcm = p["vcm_frac"] * vdd
    cl = p["cload_ff"]
    wave_line = f"wrdata {wavefile} v(clk) v(outp) v(outn)" if wavefile else ""
    # estimated layout parasitics: routing/junction cap at each node scales with
    # the total width of the devices connected to it (a schematic-level proxy for
    # post-extraction R/C — no real GDS, but shows the regeneration slowdown)
    par_lines = ""
    if p.get("parasitic"):
        pc = p.get("par_caps")
        if pc:   # layout-extracted node caps (fF) from the actual drawn geometry
            c_out, c_int = round(pc["c_out_ff"], 3), round(pc["c_int_ff"], 3)
        else:    # schematic-level proxy: cap scales with connected device width
            def _sw(*ks):
                return sum(d[k]["w_um"] * d[k]["m"] for k in ks)
            c_out = round(0.25 * _sw("pcc", "ncc", "pre") + 1.5, 3)   # fF at outp/outn
            c_int = round(0.25 * _sw("input", "ncc") + 1.0, 3)        # fF at internal nodes
        _in1, _in2 = ("fp", "fn") if p.get("topology") == "doubletail" else ("nX", "nY")
        par_lines = ("* --- extracted layout parasitics ---\n"
                     f"Cpo outp 0 {c_out}f\nCpn outn 0 {c_out}f\n"
                     f"Cpx {_in1} 0 {c_int}f\nCpy {_in2} 0 {c_int}f")
    temp = p.get("temp", 27)
    pskew = p.get("pskew", 0.0)   # process corner: +slow (SS), -fast (FF), 0 typical
    # model backend: generic PTM 45nm (.model) or REAL SkyWater SKY130 (.lib subckts)
    sky = p.get("model") == "sky130"
    if sky:
        corner = p.get("corner", "tt")
        # one-corner trimmed lib: ~1.4s/sim vs ~19s for the full 51-corner .lib
        model_header = f'.lib "{sky130_corner_lib(corner)}" {corner}'   # process via PDK corner
        param_line = ""

        def dline(label, nodes, dk, kind):
            dd = d[dk]
            l_um = max(dd["l_nm"] / 1000.0, 0.15)                # SKY130 min L
            sub = "sky130_fd_pr__nfet_01v8" if kind == "n" else "sky130_fd_pr__pfet_01v8"
            return f"X{label} {nodes} {sub} w={dd['w_um']} l={round(l_um, 3)} nf=1 mult={dd['m']}"
    else:
        model_header = f'.include "{MODEL_PATH}"'
        param_line = f".param dvtn={pskew} dvtp={-pskew}"

        def dline(label, nodes, dk, kind):
            return f"{label} {nodes} {'nmos' if kind == 'n' else 'pmos'} {_dev(d[dk], 'dvtn' if kind == 'n' else 'dvtp')}"

    if p.get("topology") == "doubletail":
        # Schinkel(ISSCC'07) 계열 double-tail — 기존 5개 사이징 키에 매핑:
        #   input=1단 입력쌍, tail=Mt1(NMOS)·Mt2(PMOS, 동일 W·M), pre=1단 프리차지
        #   PMOS(fp/fn 로드), pcc=2단 래치 PMOS, ncc=2단 래치 NMOS + 결합/리셋
        #   NMOS(M9/M10, 게이트=fp/fn — 리셋 때 출력들을 L로 클램프).
        # 극성: inp>inn → fp 먼저 방전 → M10(게이트 fp) 먼저 꺼짐 → outn 상승
        #        → outdiff<0 (strongarm 과 동일 극성).
        dev_block = "\n".join([
            "* === stage 1: input pair + tail1, PMOS precharge loads (fp/fn) ===",
            dline("M1", "fp g1 tail1 0", "input", "n"),
            dline("M2", "fn g2 tail1 0", "input", "n"),
            dline("Mt1", "tail1 clk 0 0", "tail", "n"),
            dline("M3", "fp clk vdd vdd", "pre", "p"),
            dline("M4", "fn clk vdd vdd", "pre", "p"),
            "* === stage 2: latch (X-coupled) + coupling NMOS + PMOS tail2 (clkb) ===",
            dline("Mt2", "tail2 clkb vdd vdd", "tail", "p"),
            dline("M5", "outp outn tail2 vdd", "pcc", "p"),
            dline("M6", "outn outp tail2 vdd", "pcc", "p"),
            dline("M7", "outp outn 0 0", "ncc", "n"),
            dline("M8", "outn outp 0 0", "ncc", "n"),
            "* coupling/reset: fp/fn high during reset -> both outputs clamped low",
            dline("M9", "outp fn 0 0", "ncc", "n"),
            dline("M10", "outn fp 0 0", "ncc", "n"),
        ])
        clkb_line = f"Vclkb clkb 0 PULSE({vdd} 0 200p 12p 12p {p.get('clk_high_ns', 3.0)}n {p.get('clk_period_ns', 6.0)}n)"
    else:
        clkb_line = ""
        dev_block = None
    if dev_block is None:
        dev_block = "\n".join([
        "* --- input differential pair ---",
        dline("M1", "nX g1 tail 0", "input", "n"),
        dline("M2", "nY g2 tail 0", "input", "n"),
        "* --- tail switch ---",
        dline("Mt", "tail clk 0 0", "tail", "n"),
        "* --- cross-coupled NMOS latch ---",
        dline("M3", "outp outn nX 0", "ncc", "n"),
        dline("M4", "outn outp nY 0", "ncc", "n"),
        "* --- cross-coupled PMOS latch ---",
        dline("M5", "outp outn vdd vdd", "pcc", "p"),
        dline("M6", "outn outp vdd vdd", "pcc", "p"),
        "* --- precharge PMOS (on when clk low) ---",
        dline("M7", "outp clk vdd vdd", "pre", "p"),
        dline("M8", "outn clk vdd vdd", "pre", "p"),
        dline("M9", "nX clk vdd vdd", "pre", "p"),
        dline("M10", "nY clk vdd vdd", "pre", "p"),
    ])
    # clock timing (defaults reproduce the original 200p/3n-high/6n-period run)
    clk_hi = p.get("clk_high_ns", 3.0)
    clk_per = p.get("clk_period_ns", 6.0)
    tstop = p.get("tstop_ns", 2.2)
    # transient step: 1 ps is over-resolved-enough (decision time bit-identical to
    # 0.2 ps) yet ~4x faster; ngspice adapts finer as needed via reltol
    tstep = p.get("tstep_ps", 1.0)
    meas_at = p.get("meas_at_ns", 2.15)     # sample fdiff at end of eval phase
    iavg_to = p.get("iavg_to_ns", 2.2)
    reset_at = p.get("reset_at_ns")          # optional: probe outputs during 2nd precharge
    reset_lines = (f"meas tran vrstp FIND v(outp) AT={reset_at}n\n"
                   f"meas tran vrstn FIND v(outn) AT={reset_at}n") if reset_at else ""
    return f"""StrongARM latch comparator (generated)
.option temp={temp}
{param_line}
{model_header}
Vdd vdd 0 {vdd}
* clock: precharge (clk=0) for 200ps, then evaluate
Vclk clk 0 PULSE(0 {vdd} 200p 12p 12p {clk_hi}n {clk_per}n)\n{clkb_line}
* differential input around common mode
Vinp inpx 0 {vcm + vdiff/2.0}
Vinn innx 0 {vcm - vdiff/2.0}
* per-device Vth mismatch injected as series gate offsets (input pair)
Vos1 g1 inpx {dvth1}
Vos2 g2 innx {dvth2}

{dev_block}
* --- load ---
Cp outp 0 {cl}f
Cn outn 0 {cl}f
{par_lines}
* --- measurement helpers ---
Bdiff outdiff 0 V=V(outp)-V(outn)
Babs  outabs  0 V=abs(V(outp)-V(outn))

.control
set noaskquit
tran {tstep}p {tstop}n
meas tran tdec TRIG v(clk) VAL='{vdd/2.0}' RISE=1 TARG v(outabs) VAL='{0.7*vdd}' CROSS=1
meas tran fdiff FIND v(outdiff) AT={meas_at}n
meas tran iavg AVG i(Vdd) FROM=200p TO={iavg_to}n
{reset_lines}
{wave_line}
.endc
.end
"""


def _run(netlist):
    with tempfile.NamedTemporaryFile("w", suffix=".sp", delete=False) as f:
        f.write(netlist)
        path = f.name
    try:
        r = subprocess.run([NGSPICE, "-b", path], capture_output=True,
                            text=True, timeout=60)
        return r.stdout + "\n" + r.stderr
    finally:
        os.unlink(path)


def _parse(out, key):
    m = re.search(rf"^{key}\s*=\s*([-\d.eE+]+)", out, re.MULTILINE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _sky130_lib_path():
    return os.path.expanduser(os.environ.get(
        "SKY130_NGSPICE_LIB", "~/pdk/sky130A/libs.tech/ngspice/sky130.lib.spice"))


# cache of one-corner libs (keeps ngspice from re-parsing all 51 corners each run)
_SKY_CACHE = os.path.join(tempfile.gettempdir(), "strongarm_sky130_corners")


def sky130_corner_lib(corner="tt"):
    """The full sky130 .lib bundles 51 corner sections; ngspice re-parses ALL of
    them (the entire binned BSIM4 corpus) on every process launch — ~19s — even
    when one corner is used. This extracts just the requested `.lib <corner>`
    block into a standalone one-corner file (relative .includes rewritten to
    absolute so it can live anywhere), cutting each sim to ~1.4s. Cached on disk
    and reused; regenerated only if the source lib is newer. Falls back to the
    full lib if the corner block isn't found."""
    full = _sky130_lib_path()
    libdir = os.path.dirname(full)
    # cache key includes a hash of the source lib path so repointing
    # SKY130_NGSPICE_LIB to a different PDK can't reuse the wrong corner block
    tag = hashlib.sha1(os.path.abspath(full).encode()).hexdigest()[:8]
    out = os.path.join(_SKY_CACHE, f"sky130_{corner}_{tag}_v2.lib.spice")  # v2: drops R/C banks
    try:
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(full):
            return out
    except OSError:
        pass
    try:
        with open(full) as f:
            lines = f.readlines()
    except OSError:
        return full
    block, inblk = [], False
    for ln in lines:
        s = ln.strip()
        if not inblk and re.match(rf"^\.lib\s+{re.escape(corner)}\b", s):
            inblk = True
        if inblk:
            m = re.match(r'^(\s*\.include\s+)"([^"]+)"(.*)$', ln)
            if m:
                inc = m.group(2)
                # skip passive/special-cell model banks — this tool instantiates
                # only the nfet/pfet subckts, so R/C + specialized-cell parsing
                # (~1s of the ~1.3s) is pure waste and dropping it is bit-identical
                if re.search(r"(^|/)(r\+c|specialized_cells)", inc):
                    continue
                if not os.path.isabs(inc):
                    ln = f'{m.group(1)}"{os.path.join(libdir, inc)}"{m.group(3)}\n'
            block.append(ln)
            if re.match(r"^\.endl\b", s):
                break
    if not block:
        return full  # corner not present — use the full lib rather than break
    try:
        os.makedirs(_SKY_CACHE, exist_ok=True)
        # tmp name is unique per process AND thread — several ThreadPool workers
        # can build the same cold-cache corner at once without clobbering one
        # another's partial write before the atomic replace
        tmp = f"{out}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w") as f:
            f.writelines(block)
        os.replace(tmp, out)  # atomic promote
        return out
    except OSError:
        return full


def _model_header(p):
    if p.get("model") == "sky130":
        corner = p.get("corner", "tt")
        return f'.lib "{sky130_corner_lib(corner)}" {corner}'
    return f'.include "{MODEL_PATH}"'


def _input_id(p, vg):
    """|Id| (A) of one input device biased at (Vgs=vg, Vds=vdd/2, Vs=0) — op point."""
    d = p["devices"]["input"]
    vdd = p["vdd"]
    if p.get("model") == "sky130":
        dev = f"XM d g 0 0 sky130_fd_pr__nfet_01v8 w={d['w_um']} l={round(max(d['l_nm'] / 1000.0, 0.15), 3)} nf=1 mult={d['m']}"
    else:
        dev = f"M d g 0 0 nmos W={d['w_um']}u L={d['l_nm']}n M={d['m']}"
    out = _run(f".option temp={p.get('temp', 27)}\n{_model_header(p)}\n"
               f"Vd d 0 {vdd / 2.0}\nVg g 0 {vg}\n{dev}\n.control\nop\nprint i(Vd)\n.endc\n.end\n")
    m = re.search(r"i\(vd\)\s*=\s*([-\d.eE+]+)", out, re.IGNORECASE)
    return abs(float(m.group(1))) if m else None


def _estimate_noise(p, decision_ps):
    """First-order input-referred noise (µVrms): input-pair thermal noise
    integrated over the (short) integration phase — sqrt(2·γ·kT/(gm·t_int)).
    gm is a finite-difference of the input device Id (model-agnostic)."""
    if not decision_ps:
        return None
    vcm = p["vcm_frac"] * p["vdd"]
    i0, i1 = _input_id(p, vcm), _input_id(p, vcm + 0.005)
    if i0 is None or i1 is None or i1 <= i0:
        return None
    gm = (i1 - i0) / 0.005
    kT = 1.380649e-23 * (p.get("temp", 27) + 273.15)
    t_int = decision_ps * 1e-12 * 0.6
    return round(math.sqrt(2.0 * (2.0 / 3.0) * kT / (gm * t_int)) * 1e6, 1)


def measure_nominal(p, with_noise=False):
    """Speed / power / functionality at a small fixed differential input."""
    vdd = p["vdd"]
    out = _run(gen_netlist(p, vdiff=0.01))  # 10 mV differential
    tdec = _parse(out, "tdec")
    fdiff = _parse(out, "fdiff")
    iavg = _parse(out, "iavg")
    decided = fdiff is not None and abs(fdiff) > 0.7 * vdd
    dec_ps = round(tdec * 1e12, 2) if tdec else None
    return {
        "decision_time_ps": dec_ps,
        "power_uw": round(abs(iavg) * vdd * 1e6, 3) if iavg is not None else None,
        "final_diff_v": round(fdiff, 4) if fdiff is not None else None,
        "functional": bool(decided and tdec),
        "noise_uv_rms": _estimate_noise(p, dec_ps) if with_noise else None,
    }


def _decide_sign(p, vdiff, dvth1, dvth2):
    # offset bisection only needs the *polarity* of the resolved output, so run a
    # shorter transient (latch settles well before ~1.3 ns) — halves each of the
    # many bisection sims vs the full 2.2 ns window.
    fast = {**p, "tstop_ns": 1.3, "meas_at_ns": 1.25, "iavg_to_ns": 1.3}
    out = _run(gen_netlist(fast, vdiff=vdiff, dvth1=dvth1, dvth2=dvth2))
    fdiff = _parse(out, "fdiff")
    if fdiff is None:
        return 0.0
    return fdiff


def _offset_sample(p, dvth1, dvth2):
    """Input-referred offset for one Vth-mismatch draw: bisect the differential
    input to the decision-flip point. No RNG here — deterministic per draw."""
    lo, hi = -0.06, 0.06
    s_lo = _decide_sign(p, lo, dvth1, dvth2)
    s_hi = _decide_sign(p, hi, dvth1, dvth2)
    if s_lo == 0.0 or s_hi == 0.0:
        return None                      # sim/parse failure — skip, don't fake a rail sample
    if (s_lo > 0) == (s_hi > 0):
        return hi if s_lo > 0 else lo    # offset beyond ±60mV range; clamp
    for _ in range(7):
        mid = 0.5 * (lo + hi)
        s_mid = _decide_sign(p, mid, dvth1, dvth2)
        if (s_mid > 0) == (s_lo > 0):
            lo, s_lo = mid, s_mid
        else:
            hi, s_hi = mid, s_mid
    return 0.5 * (lo + hi)


def measure_offset(p, rng):
    """Input-referred offset sigma via Monte Carlo input-pair Vth mismatch.

    For each sample we perturb the input-pair threshold voltages (Pelgrom:
    sigma_vth = AVT / sqrt(W*L*M)) and bisect the differential input to find
    the metastable point; that input value is the input-referred offset for
    the sample. Sigma over samples is the reported offset. (Input-pair
    mismatch is the dominant term; latch/tail mismatch is a documented
    extension point.)"""
    d = p["devices"]["input"]
    area_um2 = d["w_um"] * (d["l_nm"] / 1000.0) * d["m"]
    sigma_vth = (p["avt_mv_um"] / math.sqrt(area_um2)) / 1000.0  # volts, per device
    # pre-draw all mismatch pairs in-order (keeps the RNG sequence / reproducibility
    # identical to the serial version), then bisect each sample in parallel — the
    # samples are independent and each ngspice call releases the GIL.
    pairs = [(rng.gauss(0.0, sigma_vth), rng.gauss(0.0, sigma_vth)) for _ in range(p["n_mc"])]
    workers = max(1, min(8, (os.cpu_count() or 4)))
    if workers > 1 and len(pairs) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            offsets = list(ex.map(lambda ab: _offset_sample(p, ab[0], ab[1]), pairs))
    else:
        offsets = [_offset_sample(p, a, b) for a, b in pairs]
    offsets = [o for o in offsets if o is not None]  # drop failed-sim samples (#5)
    n = len(offsets)
    if n == 0:                                       # no usable sample
        return {"offset_mean_mv": None, "offset_sigma_mv": None,
                "pelgrom_sigma_vth_mv": round(sigma_vth * 1000.0, 3),
                "n_mc": 0, "samples_mv": []}
    mean = sum(offsets) / n
    var = sum((o - mean) ** 2 for o in offsets) / max(n - 1, 1)
    return {
        "offset_mean_mv": round(mean * 1000.0, 3),
        "offset_sigma_mv": round(math.sqrt(var) * 1000.0, 3),
        "pelgrom_sigma_vth_mv": round(sigma_vth * 1000.0, 3),
        "n_mc": n,
        "samples_mv": [round(o * 1000.0, 3) for o in offsets],
    }


def run_sim(params, seed=12345, do_offset=True, with_noise=False):
    import random
    p = dict(DEFAULT_PARAMS)
    p.update({k: v for k, v in params.items() if k != "devices"})
    p["devices"] = merge_devices(params.get("devices"))
    rng = random.Random(seed)
    result = {"nominal": measure_nominal(p, with_noise=with_noise)}
    if do_offset:
        result["offset"] = measure_offset(p, rng)
    result["params"] = p
    return result


def merge_devices(override):
    """Field-wise merge of a (possibly partial) device dict over the defaults, so
    a caller sending only e.g. {"input":{"w_um":10}} keeps l_nm/m from the default
    instead of dropping them (which would KeyError in gen_netlist)."""
    override = override or {}
    out = {k: {**dv} for k, dv in DEFAULT_PARAMS["devices"].items()}
    for k, dv in override.items():
        out[k] = {**out.get(k, {}), **(dv or {})}
    return out


def _full(params):
    """Merge caller params over DEFAULT_PARAMS (devices deep-merged field-wise)."""
    p = dict(DEFAULT_PARAMS)
    p.update({k: v for k, v in params.items() if k != "devices"})
    p["devices"] = merge_devices(params.get("devices"))
    return p


def metastability_sweep(params, amps=None):
    """Decision time vs input differential amplitude — the defining StrongARM
    curve. As Vin -> 0 the regeneration time diverges as tau*ln(Vlogic/Vin);
    fitting t_dec against ln(1/Vin) recovers the regeneration time constant tau.
    Returns per-point {vin_v, decision_time_ps, resolved} plus the tau fit."""
    p = _full(params)
    if amps is None:
        # log-spaced 5 uV .. 100 mV differential
        amps = [round(1e-5 * (10 ** (i / 3.0)), 8) for i in range(0, 13)]
    def _one(v):
        out = _run(gen_netlist(p, vdiff=v))
        tdec = _parse(out, "tdec")
        fdiff = _parse(out, "fdiff")
        resolved = tdec is not None and fdiff is not None and abs(fdiff) > 0.7 * p["vdd"]
        return {"vin_v": v, "decision_time_ps": round(tdec * 1e12, 2) if (tdec and resolved) else None,
                "resolved": bool(resolved)}
    points = [_one(v) for v in amps]
    # fit t_dec = tau*ln(1/Vin) + c  over resolved points (regeneration regime)
    fit = _fit_tau(points)
    return {"points": points, "tau_ps": fit[0], "intercept_ps": fit[1],
            "min_resolved_v": next((pt["vin_v"] for pt in points if pt["resolved"]), None)}


def _fit_tau(points):
    xs = [(-math.log(pt["vin_v"]), pt["decision_time_ps"]) for pt in points
          if pt["resolved"] and pt["decision_time_ps"] is not None and pt["vin_v"] > 0]
    if len(xs) < 2:
        return (None, None)
    n = len(xs)
    sx = sum(x for x, y in xs); sy = sum(y for x, y in xs)
    sxx = sum(x * x for x, y in xs); sxy = sum(x * y for x, y in xs)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return (None, None)
    slope = (n * sxy - sx * sy) / denom          # ps per natural-log-unit == tau
    intercept = (sy - slope * sx) / n
    return (round(slope, 2), round(intercept, 2))


def max_fclk_sweep(params, periods_ns=None):
    """Maximum clock rate: sweep the clock period and find the shortest one where
    the comparator both (a) resolves within the evaluate phase and (b) precharges
    back to the rails within the reset phase. Reports max f_clk and the energy per
    conversion (avg power × period) at that rate — the comparator FoM."""
    p = _full(params)
    vdd = p["vdd"]
    if periods_ns is None:
        periods_ns = [4.0, 3.0, 2.0, 1.5, 1.0, 0.8, 0.6, 0.5, 0.4, 0.35, 0.3]

    def _one(T):
        hi = round(T / 2.0, 4)
        cfg = {**p, "clk_high_ns": hi, "clk_period_ns": T,
               "tstop_ns": round(0.2 + T + 0.05, 3),
               "meas_at_ns": round(0.2 + hi - 0.02, 4),
               "iavg_to_ns": round(0.2 + T, 3),
               "reset_at_ns": round(0.2 + T - 0.02, 4)}
        out = _run(gen_netlist(cfg, vdiff=0.01))
        fdiff, iavg = _parse(out, "fdiff"), _parse(out, "iavg")
        vrp, vrn = _parse(out, "vrstp"), _parse(out, "vrstn")
        resolved = fdiff is not None and abs(fdiff) > 0.7 * vdd
        reset_ok = vrp is not None and vrn is not None and vrp > 0.9 * vdd and vrn > 0.9 * vdd
        pw = abs(iavg) * vdd * 1e6 if iavg is not None else None
        return {"period_ns": T, "fclk_ghz": round(1.0 / T, 3), "functional": bool(resolved),
                "reset_ok": bool(reset_ok), "ok": bool(resolved and reset_ok),
                "power_uw": round(pw, 3) if pw is not None else None,
                "energy_fj": round(pw * T, 2) if pw is not None else None}

    pts = [_one(T) for T in periods_ns]
    ok = [pt for pt in pts if pt["ok"]]
    best = min(ok, key=lambda pt: pt["period_ns"]) if ok else None
    return {"points": pts,
            "max_fclk_ghz": best["fclk_ghz"] if best else None,
            "min_period_ns": best["period_ns"] if best else None,
            "energy_fj_at_max": best["energy_fj"] if best else None,
            "power_uw_at_max": best["power_uw"] if best else None}


def capture_waveform(params, npoints=260):
    """Run one transient and return the actual ngspice waveform (clk, outp,
    outn) so the UI can plot the real regeneration event for this sizing."""
    import tempfile as _tf
    p = dict(DEFAULT_PARAMS)
    p.update({k: v for k, v in params.items() if k != "devices"})
    p["devices"] = {**DEFAULT_PARAMS["devices"], **params.get("devices", {})}
    fd, wf = _tf.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        out = _run(gen_netlist(p, vdiff=0.01, wavefile=wf))
        rows = []
        with open(wf) as fh:
            for line in fh:
                c = line.split()
                if len(c) >= 6:
                    try:
                        rows.append((float(c[0]), float(c[1]), float(c[3]), float(c[5])))
                    except ValueError:
                        continue
    finally:
        try:
            os.unlink(wf)
        except OSError:
            pass
    if not rows:
        return {"error": "no waveform captured"}
    step = max(1, len(rows) // npoints)
    ds = rows[::step]
    tdec = _parse(out, "tdec")
    return {
        "vdd": p["vdd"],
        "t_ns": [round(r[0] * 1e9, 4) for r in ds],
        "clk": [round(r[1], 4) for r in ds],
        "outp": [round(r[2], 4) for r in ds],
        "outn": [round(r[3], 4) for r in ds],
        "clk_edge_ns": 0.2,
        "decision_ns": round((0.2e-9 + tdec) * 1e9, 4) if tdec else None,
        "n": len(ds),
    }


def main():
    args = sys.argv[1:]
    do_offset = "--no-offset" not in args
    args = [a for a in args if a != "--no-offset"]
    if not args or args[0] == "--demo":
        params = {}
    elif args[0] == "-":
        params = json.load(sys.stdin)
    else:
        with open(args[0]) as f:
            params = json.load(f)
    print(json.dumps(run_sim(params, do_offset=do_offset), indent=2))


if __name__ == "__main__":
    main()

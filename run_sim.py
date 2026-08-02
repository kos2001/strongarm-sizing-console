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
GAA2NM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "models", "gaa2nm_approx.txt")
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "models", "ptm_45nm_bulk.txt")

# ---- ASAP7 7nm FinFET (진짜 BSIM-CMG 107, ngspice OSDI 로 실행) ----
# openvaf-r 로 컴파일한 bsimcmg107.osdi + ASU ASAP7 예측 PDK 모델 카드(TT/SS/FF,
# scripts/adapt_asap7.py 로 ngspice 형식 변환). 소자는 핀 수(NFIN)로만 사이징.
ASAP7_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "asap7")
ASAP7_OSDI = os.path.join(ASAP7_DIR, "bsimcmg107.osdi")
W_FIN_UM = 0.07     # Weff per fin ≈ 2×HFIN(32n) + TFIN(6.5n) ≈ 70nm


def nfin_of(dd):
    """asap7: 소자의 총 폭(w_um × m)을 핀 수로 양자화 — FinFET 에서 W 는
    연속값이 아니라 핀 개수다(핀 1개 ≈ Weff 0.07µm)."""
    return max(1, round(dd["w_um"] * dd["m"] / W_FIN_UM))

# gaa2nm 에서 W 는 연속값이 아니다 — 나노시트 스택 1개의 등가폭(3시트 ×
# 둘레 ≈ 0.2 µm)의 정수배로만 존재한다(스택 수 = W/0.2). 넷리스트 생성 시
# W 를 이 그리드에 스냅한다.
W_SHEET_UM = 0.2


def skew_scale(p):
    """공정 코너/시그마 Vth 스큐 스케일. gaa2nm(|Vth0| 0.20V)·asap7(LVT
    |Vth|~0.17V)은 45nm급 ±50mV 코너가 과대 — 절반(±25mV)으로 줄인다."""
    return 0.5 if p.get("model") in ("gaa2nm", "asap7") else 1.0


def w_unit(p):
    """모델별 W 그리드 단위(µm): gaa2nm 은 나노시트 스택 0.2, asap7 은 핀 0.07.
    연속-W 모델(ptm/sky130)은 None."""
    if p.get("model") == "gaa2nm":
        return W_SHEET_UM
    if p.get("model") == "asap7":
        return W_FIN_UM
    return None


def quantize_devices(p):
    """W 그리드 모델(gaa2nm/asap7): W 를 단위 그리드(w_unit 정수배, 최소 1)에
    스냅. W 를 단위폭 고정 + M=finger 로 접지 않는 이유(gaa2nm): 카드가
    geoMod=1(비공유 접합 기하 자동계산)이라 finger 수에 비례해 접합 둘레 캡이
    부풀어, 같은 총폭인데 지연이 2배로 나오는 아티팩트가 있다(실 레이아웃은
    확산 공유). asap7 은 넷리스트에서 NFIN=총폭/0.07 로 접힌다(핀은 실제
    병렬 구조라 물리적으로 정확). 연속-W 모델은 그대로 통과."""
    u = w_unit(p)
    if u is None:
        return p["devices"]
    return {k: {**d, "w_um": max(u, round(round(d["w_um"] / u) * u, 3))}
            for k, d in p["devices"].items()}

# default seed = P1_SAR_ADC first-cut sizing, adapted to PTM 45nm bulk
# (VDD 0.7 V nominal, minimum L = 45 nm for this node)
DEFAULT_PARAMS = {
    "vdd": 0.7,
    "vcm_frac": 0.62,     # input common mode as fraction of vdd
    "cload_ff": 15.0,
    "avt_mv_um": 2.0,     # Pelgrom coefficient (mV*um), ~45nm-class
    "n_mc": 16,           # Monte Carlo samples for offset
    "devices": {
        "input": {"w_um": 8.0, "l_nm": 80.0, "m": 4},
        "tail":  {"w_um": 12.0, "l_nm": 45.0, "m": 6},
        "ncc":   {"w_um": 4.0, "l_nm": 45.0, "m": 2},
        "pcc":   {"w_um": 9.0, "l_nm": 45.0, "m": 4},
        "pre":   {"w_um": 4.0, "l_nm": 45.0, "m": 2},   # S3/S4 — 출력 X/Y 프리차지
        "prei":  {"w_um": 4.0, "l_nm": 45.0, "m": 2},   # S1/S2 — 내부 P/Q 프리차지 (부하가 달라 독립 사이징)
    },
}


# Polarity per device group — the latch is NMOS-below / PMOS-above, the
# precharge switches are PMOS. Used to pick the right flavor table.
NMOS_DEVICES = ("input", "tail", "ncc")
PMOS_DEVICES = ("pcc", "pre", "prei")


# --- threshold-voltage flavor as a design variable -----------------------------
# Vth is a real per-device knob on a comparator, not just a corner perturbation:
# measured on asap7 at the node's L=21nm, raising every device one level trades
# 18.1->24.9 ps for 10.9->7.82 uW, and `tail` alone to the low-Vth flavor buys
# 18.1->16.8 ps for 4% more power. Mixed assignments are not dominated by uniform
# ones, so it is worth searching rather than prescribing.
#
# Devices carry a backend-neutral level; each backend maps it to what it really
# has. "svt" is the default everywhere and reproduces the previous netlist
# exactly, so adding this field changes no existing result.
#
# LIMITATION — per-flavor A_VT is not modelled. `avt_mv_um` is one number for the
# whole design, so a flavor change moves offset only through the *simulated* Vth
# (and through W·L·M), never through a different mismatch coefficient. Real
# implants do differ in A_VT, so an offset-critical flavor decision needs the
# foundry's per-flavor Pelgrom data, which none of these cards carry. Speed and
# power effects are simulated and trustworthy; the offset effect is partial.
VT_LEVELS = ("lvt", "svt", "hvt")        # lower Vth (fast) / standard / higher Vth

# ASAP7 ships four flavors in the adapted cards (slvt/lvt/rvt/sram); the code
# used to pin every device to `lvt`, so `lvt` is what "svt" maps to here and the
# neutral "lvt" reaches down to slvt.
_VT_ASAP7 = {"lvt": "slvt", "svt": "lvt", "hvt": "rvt"}

# SKY130 has real LVT devices for both polarities but **no nfet_01v8_hvt** — only
# the PMOS has an HVT variant. An nmos asked for hvt falls back to svt; callers
# are told via `vt_fallbacks` rather than being silently given something else.
_VT_SKY130_N = {"lvt": "sky130_fd_pr__nfet_01v8_lvt", "svt": "sky130_fd_pr__nfet_01v8"}
_VT_SKY130_P = {"lvt": "sky130_fd_pr__pfet_01v8_lvt", "svt": "sky130_fd_pr__pfet_01v8",
                "hvt": "sky130_fd_pr__pfet_01v8_hvt"}

# Minimum usable drawn L per sky130 device. The smallest `lmin` bin edge in each
# device's `.pm3.spice` card is 0.145 µm for most of them, but **pfet_01v8_lvt is
# only characterized from 0.345 µm** — give it a shorter L and no bin matches, so
# ngspice aborts the whole deck.
#
# The values here sit just *above* the bin edge, not on it: the binning compares
# strictly, so l = 0.145 exactly falls through every bin and fails the same way
# a too-short L does (which is why the original code used 0.15, not 0.145).
#
# This is a real PDK restriction, not a modelling choice: picking LVT for a PMOS
# group forces its L up ~2.3x, costing speed and area. The clamp is reported via
# `vt_plan` rather than applied silently.
_SKY_MIN_L_UM = {
    "sky130_fd_pr__nfet_01v8": 0.15,
    "sky130_fd_pr__nfet_01v8_lvt": 0.15,
    "sky130_fd_pr__pfet_01v8": 0.15,
    "sky130_fd_pr__pfet_01v8_hvt": 0.15,
    "sky130_fd_pr__pfet_01v8_lvt": 0.35,
}
_SKY_MIN_L_DEFAULT = 0.15


def sky130_min_l_um(sub):
    return _SKY_MIN_L_UM.get(sub, _SKY_MIN_L_DEFAULT)

# PTM45 / GAA2NM are single generic BSIM4 cards with no flavors, so there the
# level is applied as a delvto implant *proxy* — physically it only shifts Vth,
# it does not carry the mobility/leakage/A_VT differences a real flavor implant
# would. Scaled by skew_scale for the same reason the corner skew is: 50 mV is
# too coarse against gaa2nm's |Vth0| = 0.20 V.
_VT_PROXY_V = {"lvt": -0.05, "svt": 0.0, "hvt": +0.05}


# --- channel length: per-model usable range and the node's nominal --------------
# L was previously taken from the params verbatim on every backend, and the only
# per-model L knowledge lived in the web UI's model buttons. So an API/MCP caller
# asking for `{"model": "asap7"}` got L = 80/45 nm on a 7 nm card — 4x the node's
# gate length — while the same request through the UI got 21 nm. This table is now
# the single source of truth for both.
#
# `min`/`max` are measured, not assumed (sweep in tests/test_l_search.py):
#   ptm45  — the PTM card has no model below 45 nm; the deck errors out. Above
#            ~200 nm the latch stops resolving.
#   sky130 — the per-device bin floor (see _SKY_MIN_L_UM) is the real minimum;
#            beyond ~500 nm it stops resolving.
#   asap7  — BSIM-CMG runs continuously well outside the node, but 21 nm is the
#            characterized gate length, so the search does not go below it.
#   gaa2nm — fails to resolve at 8 nm; non-monotonic above (20 nm is faster than
#            14 nm), which is why the input pair's nominal is 20.
L_RANGE_NM = {
    "ptm45":  {"min": 45.0,  "max": 200.0, "input": 80.0,  "other": 45.0},
    "sky130": {"min": 150.0, "max": 500.0, "input": 150.0, "other": 150.0},
    "asap7":  {"min": 21.0,  "max": 200.0, "input": 21.0,  "other": 21.0},
    "gaa2nm": {"min": 10.0,  "max": 120.0, "input": 20.0,  "other": 14.0},
}
_L_RANGE_DEFAULT = L_RANGE_NM["ptm45"]


def l_range_nm(p):
    """(min, max) usable channel length for this backend."""
    r = L_RANGE_NM.get(p.get("model") or "ptm45", _L_RANGE_DEFAULT)
    return r["min"], r["max"]


def l_nominal_nm(p, dev):
    """The node's nominal L for one device group — the input pair is routinely
    drawn longer than the rest for matching, so it has its own entry."""
    r = L_RANGE_NM.get(p.get("model") or "ptm45", _L_RANGE_DEFAULT)
    return r["input" if dev == "input" else "other"]


def clamp_l_nm(p, dev, l_nm):
    lo, hi = l_range_nm(p)
    return max(lo, min(hi, float(l_nm)))


def l_report(p):
    """Validate the fixed channel lengths. L is a methodology choice here, not a
    searched variable, so the one thing that can silently go wrong is a fixed L
    the backend cannot honour:

      * below the range — on ptm45 the card has no model there and the deck
        errors out, which reads as "non-functional" rather than "bad input";
      * above it — the latch stops resolving;
      * on sky130, between the request and the PDK bin floor, where the deck
        quietly builds a longer device than asked for.

    Returns the requested L, what is actually built, and anything out of range.
    Both judgements are made on the **effective** L, because that is the device
    that exists: a sky130 request below the bin floor is raised and is fine, while
    the same request on ptm45 has nothing to raise it and dies."""
    lo, hi = l_range_nm(p)
    req, eff, out, raised = {}, {}, {}, {}
    for dev, d in p["devices"].items():
        r = float(d["l_nm"])
        e = effective_l_nm(p, dev)
        req[dev], eff[dev] = r, e
        if e != r:
            raised[dev] = f"{r:g}→{e:g}nm (PDK bin floor)"
        if e < lo:
            out[dev] = f"L {e:g}nm below {lo:g}nm — this backend has no model there, the deck will error"
        elif e > hi:
            out[dev] = f"L {e:g}nm above {hi:g}nm — the latch stops resolving"
    return {"l_nm": req, "effective_nm": eff, "range_nm": [lo, hi],
            "out_of_range": out, "raised_by_pdk": raised}


def effective_l_nm(p, dev):
    """The L the device is actually **built with**, which is not always the L in
    the params: on sky130 the netlist raises L to the device's bin floor (0.15 µm,
    or 0.345 µm for pfet_01v8_lvt).

    Every area calculation must use this. They used to read `l_nm` directly, so
    asking for L = 45 nm on sky130 simulated a 150 nm device while the Pelgrom
    offset was computed for a 45 nm one — an offset 1.83x worse than the geometry
    actually drawn, which the optimizer then paid a penalty against."""
    d = p["devices"][dev]
    l_nm = float(d["l_nm"])
    if p.get("model") == "sky130":
        tbl = _VT_SKY130_N if dev in NMOS_DEVICES else _VT_SKY130_P
        sub = tbl.get(vt_of(d)) or tbl["svt"]
        l_nm = max(l_nm, sky130_min_l_um(sub) * 1000.0)
    return l_nm


def gate_area_um2(p, dev):
    """W · L_effective · M in µm² — the area Pelgrom matching scales with."""
    d = p["devices"][dev]
    return d["w_um"] * (effective_l_nm(p, dev) / 1000.0) * d["m"]


def vt_of(d):
    """The requested Vt level for one device dict, defaulting to standard."""
    v = (d or {}).get("vt", "svt")
    return v if v in VT_LEVELS else "svt"


def vt_offset_v(d, p, kind):
    """delvto shift (volts) for the generic-card backends. `kind` is unused for
    now — both polarities use the same implant magnitude — but is kept so an
    asymmetric proxy can be introduced without changing callers."""
    return _VT_PROXY_V[vt_of(d)] * skew_scale(p)


def vt_plan(p):
    """What the Vt request actually turns into: the level applied per device, any
    level the backend could not honour, and any L the PDK forced up. Reported by
    the optimizer/API so neither a fallback nor a geometry change is silent."""
    model, plan, fell, clamps = p.get("model"), {}, {}, {}
    for k, d in p["devices"].items():
        want = vt_of(d)
        got = want
        if model == "sky130" and want == "hvt" and k in NMOS_DEVICES:
            got = "svt"                     # no nfet_01v8_hvt exists in sky130
        plan[k] = got
        if got != want:
            fell[k] = f"{want}->{got} (backend has no {want} for this polarity)"
        if model == "sky130":
            tbl = _VT_SKY130_N if k in NMOS_DEVICES else _VT_SKY130_P
            sub = tbl.get(got) or tbl["svt"]
            floor = sky130_min_l_um(sub)
            if d.get("l_nm", 0) / 1000.0 < floor:
                clamps[k] = (f"L {d['l_nm']}nm -> {floor * 1000:.0f}nm "
                             f"({sub.replace('sky130_fd_pr__', '')} min bin)")
    return {"levels": plan, "fallbacks": fell, "l_clamps": clamps}


def _dev(d, vt="dvtn", vt_shift=0.0):
    # delvto = corner Vth shift (dvtn/dvtp via .param) + the device's own implant
    # level; the two compose rather than overwrite each other.
    shift = f"{vt}{vt_shift:+g}" if vt_shift else vt
    return f"W={d['w_um']}u L={d['l_nm']}n M={d['m']} delvto={{{shift}}}"


def gen_netlist(p, vdiff, dvth1=0.0, dvth2=0.0, wavefile=None):
    d = quantize_devices(p)
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
            c_int = round(0.25 * _sw("input", "ncc", "prei") + 1.0, 3)        # fF at internal nodes
        _in1, _in2 = ("nX", "nY")
        par_lines = ("* --- extracted layout parasitics ---\n"
                     f"Cpo outp 0 {c_out}f\nCpn outn 0 {c_out}f\n"
                     f"Cpx {_in1} 0 {c_int}f\nCpy {_in2} 0 {c_int}f")
    temp = p.get("temp", 27)
    pskew = p.get("pskew", 0.0)   # process corner: +slow (SS), -fast (FF), 0 typical
    # 교차 코너(SF/FS)용 독립 스큐 — 미지정 시 정렬 코너(pskew)로 동작.
    # 표기: 첫 글자=NMOS, 둘째=PMOS. nskew>0 = slow N, pskew_p>0 = slow P.
    nskew = p.get("nskew", pskew)
    pskew_p = p.get("pskew_p", pskew)
    # model backend: generic PTM 45nm (.model), REAL SkyWater SKY130 (.lib subckts),
    # or REAL ASAP7 7nm FinFET (BSIM-CMG 107 via ngspice OSDI)
    sky = p.get("model") == "sky130"
    asap = p.get("model") == "asap7"
    if sky:
        corner = p.get("corner", "tt")
        # one-corner trimmed lib: ~1.4s/sim vs ~19s for the full 51-corner .lib
        model_header = f'.lib "{sky130_corner_lib(corner)}" {corner}'   # process via PDK corner
        param_line = ""

        def dline(label, nodes, dk, kind):
            dd = d[dk]
            tbl = _VT_SKY130_N if kind == "n" else _VT_SKY130_P
            # real PDK devices per Vt level; nmos has no hvt, fall back to svt
            sub = tbl.get(vt_of(dd)) or tbl["svt"]
            # min L is per device — pfet_01v8_lvt starts at 0.345 µm, and a
            # shorter L matches no bin and aborts the deck
            l_um = max(dd["l_nm"] / 1000.0, sky130_min_l_um(sub))
            return f"X{label} {nodes} {sub} w={dd['w_um']} l={round(l_um, 3)} nf=1 mult={dd['m']}"
    elif asap:
        corner = p.get("corner", "TT").upper()
        model_header = f'.include "{os.path.join(ASAP7_DIR, f"7nm_{corner}.sp")}"'
        # BSIM-CMG DELVTRAND 는 + 가 Vth ↓(빠름) — delvto 관례와 부호가 반대라 반전
        param_line = f".param dvtn={-nskew} dvtp={-pskew_p}"

        def dline(label, nodes, dk, kind):
            dd = d[dk]
            # real ASAP7 flavor per Vt level (slvt/lvt/rvt already in the cards);
            # orthogonal to the corner skew, which stays in delvtrand
            mdl = f"{'nmos' if kind == 'n' else 'pmos'}_{_VT_ASAP7[vt_of(dd)]}"
            vt = "dvtn" if kind == "n" else "dvtp"
            return (f"N{label} {nodes} {mdl} l={dd['l_nm']}n "
                    f"nfin={nfin_of(dd)} delvtrand={{{vt}}}")
    else:
        model_header = (f'.include "{GAA2NM_PATH}"' if p.get("model") == "gaa2nm"
                        else f'.include "{MODEL_PATH}"')
        param_line = f".param dvtn={nskew} dvtp={-pskew_p}"

        def dline(label, nodes, dk, kind):
            # no flavors on a generic card — the level becomes a delvto implant
            # proxy, added to (not replacing) the corner skew param
            return (f"{label} {nodes} {'nmos' if kind == 'n' else 'pmos'} "
                    f"{_dev(d[dk], 'dvtn' if kind == 'n' else 'dvtp', vt_offset_v(d[dk], p, kind))}")

    # Clock edge rate. Was hardcoded at 12 ps. It barely moves the decision time at
    # a relaxed clock (1.3% across 2..200 ps, since tdec is referenced to the clk
    # mid-point) but it substantially lowers the maximum usable clock rate — at
    # 2.22 GHz a 12 ps edge resolves and a 50 ps edge does not — and a slow edge
    # breaks the *reset* before it breaks resolution, which is the mechanism behind
    # decision-to-decision hysteresis. Default 12 keeps the deck unchanged.
    #
    # There is no clk/clkb skew to parameterise: this topology is single-clock, with
    # the tail switch and the precharge PMOS both driven from `clk`, so the race is
    # between those two devices on one edge rather than between two clock phases.
    clk_trf = float(p.get("clk_trf_ps", 12.0))
    # Mismatch beyond the input pair. The input pair has always had its Vth
    # mismatch injected as series gate sources (Vos1/Vos2), which works on every
    # backend because it needs no model parameter. The latch and precharge pairs
    # are matched pairs too and their Vth mismatch adds directly to a StrongARM's
    # offset — the cross-coupled pair especially, since it acts right when the
    # regeneration decides. Same mechanism, applied per requested group: +δ/2 on
    # one device of the pair, −δ/2 on the other.
    #
    # Only emitted for groups named in `mismatch_v`, so an unset call produces the
    # original deck unchanged. `tail` is deliberately absent: it is a single device
    # with no differential partner, so its mismatch is common-mode.
    mm = {k: float(v) for k, v in (p.get("mismatch_v") or {}).items() if v}

    def pair(g, la, lb, na, nb, kind, gate_a, gate_b):
        """Two devices of a matched pair, with optional series-gate mismatch."""
        d = mm.get(g)
        if not d:
            return [dline(la, na.format(g=gate_a), g, kind),
                    dline(lb, nb.format(g=gate_b), g, kind)]
        ga, gb = f"gm{la}", f"gm{lb}"
        return [dline(la, na.format(g=ga), g, kind),
                dline(lb, nb.format(g=gb), g, kind),
                f"Vmm{la} {ga} {gate_a} {d / 2.0:.9g}",
                f"Vmm{lb} {gb} {gate_b} {-d / 2.0:.9g}"]

    dev_block = "\n".join([
        "* --- input differential pair ---",
        dline("M1", "nX g1 tail 0", "input", "n"),
        dline("M2", "nY g2 tail 0", "input", "n"),
        "* --- tail switch ---",
        dline("M7", "tail clk 0 0", "tail", "n"),     # 그림 표기: 테일 = M7
        "* --- cross-coupled NMOS latch ---",
        *pair("ncc", "M3", "M4", "outp {g} nX 0", "outn {g} nY 0", "n", "outn", "outp"),
        "* --- cross-coupled PMOS latch ---",
        *pair("pcc", "M5", "M6", "outp {g} vdd vdd", "outn {g} vdd vdd", "p", "outn", "outp"),
        "* --- precharge PMOS (on when clk low) ---",
        # S3/S4 — 출력 X/Y 프리차지, S1/S2 — 내부 P/Q 프리차지
        *pair("pre", "MS3", "MS4", "outp {g} vdd vdd", "outn {g} vdd vdd", "p", "clk", "clk"),
        *pair("prei", "MS1", "MS2", "nX {g} vdd vdd", "nY {g} vdd vdd", "p", "clk", "clk"),
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

    # --- input drive network: what makes kickback observable at all -------------
    # With ideal sources on the gates (rs_ohm = 0, the default) the input nodes are
    # held rigid, so the charge the input pair pushes back through Cgd when the
    # outputs slew produces exactly zero disturbance — kickback is unmeasurable by
    # construction, not merely unmeasured. A real SAR comparator is driven by the
    # DAC's finite output impedance into its own sampling capacitance, and that
    # held node is what kickback corrupts.
    #
    # rs_ohm > 0 inserts that network and enables the kickback measurements. The
    # DC operating point is unchanged (no gate current), so this only affects the
    # transient disturbance — and rs_ohm = 0 emits the original deck verbatim.
    rs = float(p.get("rs_ohm", 0.0) or 0.0)
    cs_ff = float(p.get("cs_ff", 0.0) or 0.0)
    # (kickback measurements are appended to reset_lines below)
    if rs > 0:
        cs_line = (f"Csp inpx 0 {cs_ff}f\nCsn innx 0 {cs_ff}f\n" if cs_ff > 0 else "")
        src_block = (f"Vinp srcp 0 {vcm + vdiff / 2.0}\n"
                     f"Vinn srcn 0 {vcm - vdiff / 2.0}\n"
                     f"* DAC/driver output impedance + held sampling cap\n"
                     f"Rsp srcp inpx {rs}\nRsn srcn innx {rs}\n"
                     f"{cs_line}"
                     f"Bkdiff kdiff 0 V=V(inpx)-V(innx)")
        # peak excursion of each held node and of the differential, over the
        # evaluate window; plus where the differential lands by the end, which is
        # the part that corrupts the next comparison
        kb_from, kb_to = 0.2, min(iavg_to, tstop)
        kick = (
            f"meas tran kbp_max MAX v(inpx) FROM={kb_from}n TO={kb_to}n\n"
            f"meas tran kbp_min MIN v(inpx) FROM={kb_from}n TO={kb_to}n\n"
            f"meas tran kbn_max MAX v(innx) FROM={kb_from}n TO={kb_to}n\n"
            f"meas tran kbn_min MIN v(innx) FROM={kb_from}n TO={kb_to}n\n"
            f"meas tran kbd_max MAX v(kdiff) FROM={kb_from}n TO={kb_to}n\n"
            f"meas tran kbd_min MIN v(kdiff) FROM={kb_from}n TO={kb_to}n\n"
            f"meas tran kbd_end FIND v(kdiff) AT={kb_to}n")
        # appended to reset_lines rather than given its own template slot, so the
        # default (rs_ohm = 0) deck stays byte-identical to before this feature
        reset_lines = f"{reset_lines}\n{kick}" if reset_lines else kick
    else:
        src_block = (f"Vinp inpx 0 {vcm + vdiff / 2.0}\n"
                     f"Vinn innx 0 {vcm - vdiff / 2.0}")

    # --- two-decision sequence, for hysteresis --------------------------------
    # A StrongARM must fully reset between decisions or the previous outcome biases
    # the next one — a data-dependent offset, which in a SAR shows up as bit errors
    # correlated with the code. The default deck evaluates once, so it cannot see
    # this at all. `prime_v` makes the input a two-step PWL: a large priming
    # differential for the first evaluate, then `vdiff` for the second, and the
    # decision is measured on the *second* one.
    prime = p.get("prime_v")
    if prime is not None:
        pr = float(prime)
        # cycle 1 evaluates at 200p..(200p+hi); the input switches during the
        # intervening precharge so the priming edge itself is not what is measured
        t_sw = 0.2 + clk_hi + 0.02          # ns, just after cycle 1's evaluate ends
        rise = 0.01                          # ns, input settling — fast vs the cycle
        vp1, vn1 = vcm + pr / 2.0, vcm - pr / 2.0
        vp2, vn2 = vcm + vdiff / 2.0, vcm - vdiff / 2.0
        src_block = (
            f"* two decisions: cycle 1 primed with {pr:g} V, cycle 2 measured\n"
            f"Vinp inpx 0 PWL(0 {vp1:.9g} {t_sw:g}n {vp1:.9g} "
            f"{t_sw + rise:g}n {vp2:.9g} 100n {vp2:.9g})\n"
            f"Vinn innx 0 PWL(0 {vn1:.9g} {t_sw:g}n {vn1:.9g} "
            f"{t_sw + rise:g}n {vn2:.9g} 100n {vn2:.9g})")
        # second evaluate begins one clock period after the first
        t2 = 0.2 + clk_per
        seq = (f"meas tran fdiff2 FIND v(outdiff) AT={t2 + clk_hi - 0.02:g}n\n"
               f"meas tran fdiff1 FIND v(outdiff) AT={0.2 + clk_hi - 0.02:g}n\n"
               f"meas tran vrst1p FIND v(outp) AT={t2 - 0.02:g}n\n"
               f"meas tran vrst1n FIND v(outn) AT={t2 - 0.02:g}n")
        reset_lines = f"{reset_lines}\n{seq}" if reset_lines else seq
    return f"""StrongARM latch comparator (generated)
.option temp={temp}
{param_line}
{model_header}
Vdd vdd 0 {vdd}
* clock: precharge (clk=0) for 200ps, then evaluate
Vclk clk 0 PULSE(0 {vdd} 200p {clk_trf:g}p {clk_trf:g}p {clk_hi}n {clk_per}n)
* differential input around common mode
{src_block}
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
{f"pre_osdi {ASAP7_OSDI}" if asap else ""}
tran {tstep}p {tstop}n
meas tran tdec TRIG v(clk) VAL='{vdd/2.0}' RISE=1 TARG v(outabs) VAL='{0.7*vdd}' CROSS=1
meas tran fdiff FIND v(outdiff) AT={meas_at}n
meas tran iavg AVG i(Vdd) FROM=200p TO={iavg_to}n
{reset_lines}
{wave_line}
.endc
.end
"""


# --- ngspice invocation: one gate, one memo -----------------------------------
# Every ngspice run is a CPU-bound process, and the thread pools in this codebase
# nest: a 45-corner PVT fan-out calls run_sim, whose offset Monte-Carlo fans out
# again, so per-pool limits multiply (8 x 8 = 64 processes). This bounds the total
# process-wide instead. Measured throughput is flat from 8 to 64 slots — macOS
# absorbs the oversubscription — so this is a resource ceiling for smaller/loaded
# machines and a single knob for it, not a speedup. Default leaves headroom.
_NG_SLOTS = int(os.environ.get("NGSPICE_MAX_PROCS") or 0) or max(8, os.cpu_count() or 8)
_ng_gate = threading.BoundedSemaphore(_NG_SLOTS)

# A deck's output is a deterministic function of its text, so identical decks are
# worth remembering: coordinate descent revisits candidates, the console re-runs
# the same sizing across pages, and sweeps overlap at their endpoints. Bounded
# LRU on sha1(deck) — set NGSPICE_CACHE=0 to disable.
_NG_CACHE_MAX = 4096 if os.environ.get("NGSPICE_CACHE") is None else int(os.environ["NGSPICE_CACHE"])
_ng_cache = {}
_ng_order = []                      # LRU order, newest last; guarded by _ng_lock
_ng_lock = threading.Lock()
_ng_stats = {"hits": 0, "misses": 0}

# Decks that write files (waveform capture, user `wrdata` decks) have a side
# effect beyond their stdout, so a hit would silently skip producing the file.
_NG_SIDE_EFFECT = re.compile(r"^\s*(wrdata|write|print\s*>)", re.MULTILINE)


def pmap(fn, items):
    """Order-preserving parallel map for sim work. Each ngspice call is a
    subprocess that releases the GIL, so threads are the right tool; the total
    process count is bounded by `_ng_gate`, so the pool size here only needs to
    be wide enough to keep that gate fed."""
    items = list(items)
    if len(items) < 2:
        return [fn(i) for i in items]
    with ThreadPoolExecutor(max_workers=min(len(items), _NG_SLOTS)) as ex:
        return list(ex.map(fn, items))


def ngspice_cache_stats():
    """{hits, misses, size} — surfaced by /api/health so the cache is observable
    rather than a silent behaviour change."""
    with _ng_lock:
        return {**_ng_stats, "size": len(_ng_cache), "max": _NG_CACHE_MAX,
                "max_procs": _NG_SLOTS}


def _ng_cache_get(key):
    with _ng_lock:
        if key not in _ng_cache:
            _ng_stats["misses"] += 1
            return None
        _ng_stats["hits"] += 1
        try:
            _ng_order.remove(key)
        except ValueError:
            pass
        _ng_order.append(key)
        return _ng_cache[key]


def _ng_cache_put(key, val):
    with _ng_lock:
        if key not in _ng_cache:
            _ng_order.append(key)
        _ng_cache[key] = val
        while len(_ng_order) > _NG_CACHE_MAX:
            _ng_cache.pop(_ng_order.pop(0), None)


def _run(netlist, cache=True):
    cacheable = cache and _NG_CACHE_MAX > 0 and not _NG_SIDE_EFFECT.search(netlist)
    key = hashlib.sha1(netlist.encode()).hexdigest() if cacheable else None
    if key is not None:
        hit = _ng_cache_get(key)
        if hit is not None:
            return hit
    with _ng_gate:                  # bound total concurrent ngspice, not per pool
        with tempfile.NamedTemporaryFile("w", suffix=".sp", delete=False) as f:
            f.write(netlist)
            path = f.name
        try:
            r = subprocess.run([NGSPICE, "-b", path], capture_output=True,
                               text=True, timeout=60)
            out = r.stdout + "\n" + r.stderr
        finally:
            os.unlink(path)
    if key is not None:
        _ng_cache_put(key, out)
    return out


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

# The only sky130 primitives this tool instantiates (see gen_netlist / _dev_line).
# Everything else in a corner deck is a model bank we pay to parse and never use.
# Derived from the Vt flavor tables rather than written out, so the prune
# whitelist and the set of devices gen_netlist can actually instantiate cannot
# drift apart. They did drift once: the prune landed keeping only the SVT pair,
# and the first LVT deck died on `unknown subckt: …nfet_01v8_lvt`.
_SKY_USED_DEVICES = tuple(sorted(
    {s.replace("sky130_fd_pr__", "")
     for s in list(_VT_SKY130_N.values()) + list(_VT_SKY130_P.values())}))


def _sky130_keep_include(base):
    """Should this include inside a sky130 corner deck be parsed?

    A corner file (`corners/tt.spice`) pulls ~30 model banks: LVT/HVT variants,
    the 3.3/5/16/20 V families, ESD devices, the NPN, the RF cards and the
    passive (`nonfet`) bank. We instantiate only the 1.8 V core nfet/pfet
    subckts, so every other bank is parse time spent on models the netlist never
    references — dropping them is bit-identical, and it is the same argument the
    outer lib already makes for the R/C and specialized-cell banks.

    Kept: the corner + mismatch cards for the devices in `_SKY_USED_DEVICES`,
    and `all.spice` (shared process/statistical `.param`s the subckts read)."""
    if base == "all.spice":
        return True
    return any(f"sky130_fd_pr__{d}__" in base for d in _SKY_USED_DEVICES)


def _sky130_prune_corner_file(path, tag):
    """Rewrite one `corners/<c>.spice` with the unused model banks dropped and
    relative includes made absolute. Returns the cached pruned path, or `path`
    unchanged if pruning is disabled or anything goes wrong."""
    if os.environ.get("SKY130_PRUNE") == "0":   # escape hatch: parse the full deck
        return path
    srcdir = os.path.dirname(os.path.abspath(path))
    out = os.path.join(_SKY_CACHE, f"corner_{os.path.basename(path)}_{tag}_v4.spice")
    try:
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
            return out
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return path
    kept = []
    for ln in lines:
        m = re.match(r'^(\s*\.include\s+)"([^"]+)"(.*)$', ln)
        if m:
            inc = m.group(2)
            if not _sky130_keep_include(os.path.basename(inc)):
                continue
            if not os.path.isabs(inc):
                inc = os.path.normpath(os.path.join(srcdir, inc))
            ln = f'{m.group(1)}"{inc}"{m.group(3)}\n'
        kept.append(ln)
    try:
        os.makedirs(_SKY_CACHE, exist_ok=True)
        tmp = f"{out}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w") as f:
            f.writelines(kept)
        os.replace(tmp, out)   # atomic promote — concurrent builders are safe
        return out
    except OSError:
        return path


def sky130_corner_lib(corner="tt"):
    """The full sky130 .lib bundles 51 corner sections; ngspice re-parses ALL of
    them (the entire binned BSIM4 corpus) on every process launch — ~19s — even
    when one corner is used. This extracts just the requested `.lib <corner>`
    block into a standalone one-corner file (relative .includes rewritten to
    absolute so it can live anywhere), cutting each sim to ~1.4s. The corner file
    it points at is pruned in turn to the device families we actually instantiate
    (`_sky130_prune_corner_file`), which is what takes a warm sim from ~420ms to
    ~185ms. Cached on disk and reused; regenerated only if the source lib is
    newer. Falls back to the full lib if the corner block isn't found."""
    full = _sky130_lib_path()
    libdir = os.path.dirname(full)
    # cache key includes a hash of the source lib path so repointing
    # SKY130_NGSPICE_LIB to a different PDK can't reuse the wrong corner block
    tag = hashlib.sha1(os.path.abspath(full).encode()).hexdigest()[:8]
    # v3: also prunes the corner file's unused device-family model banks. The
    # prune setting is part of the name — otherwise flipping SKY130_PRUNE would
    # silently reuse a lib built the other way.
    pr = "full" if os.environ.get("SKY130_PRUNE") == "0" else "lean"
    # v4: the kept device set now includes the Vt flavors (lvt/hvt), so a v3
    # cache file would be missing banks the netlist can reference
    out = os.path.join(_SKY_CACHE, f"sky130_{corner}_{tag}_v4{pr}.lib.spice")
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
                    inc = os.path.join(libdir, inc)
                # the per-corner deck is the expensive one — prune its model banks
                if os.path.basename(os.path.dirname(inc)) == "corners":
                    inc = _sky130_prune_corner_file(inc, tag)
                ln = f'{m.group(1)}"{inc}"{m.group(3)}\n'
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
    if p.get("model") == "gaa2nm":
        return f'.include "{GAA2NM_PATH}"'   # 2nm급 근사(BSIM4) — 경향 분석용
    if p.get("model") == "asap7":
        corner = p.get("corner", "TT").upper()
        return f'.include "{os.path.join(ASAP7_DIR, f"7nm_{corner}.sp")}"'
    return f'.include "{MODEL_PATH}"'


def _input_id(p, vg):
    """|Id| (A) of one input device biased at (Vgs=vg, Vds=vdd/2, Vs=0) — op point."""
    d = p["devices"]["input"]
    vdd = p["vdd"]
    osdi = f"pre_osdi {ASAP7_OSDI}\n" if p.get("model") == "asap7" else ""
    if p.get("model") == "sky130":
        dev = f"XM d g 0 0 sky130_fd_pr__nfet_01v8 w={d['w_um']} l={round(max(d['l_nm'] / 1000.0, 0.15), 3)} nf=1 mult={d['m']}"
    elif p.get("model") == "asap7":
        dev = f"NM d g 0 0 nmos_lvt l={d['l_nm']}n nfin={nfin_of(d)}"
    else:
        dev = f"M d g 0 0 nmos W={d['w_um']}u L={d['l_nm']}n M={d['m']}"
    out = _run(f".option temp={p.get('temp', 27)}\n{_model_header(p)}\n"
               f"Vd d 0 {vdd / 2.0}\nVg g 0 {vg}\n{dev}\n.control\n{osdi}op\nprint i(Vd)\n.endc\n.end\n")
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


#: Bisection resolution for one offset sample. The original 7 steps over ±60 mV
#: quantise to 0.47 mV, which turned out to bias the headline spec: measured, σ comes
#: out up to 19% high for well-matched (large-area) designs — 0.906 vs 0.764 mV on a
#: 24 µm input pair — and those are exactly what the optimizer produces. It also *was*
#: the answer for the latch/precharge pairs, whose contributions sit near it: they
#: pinned at 0.494 mV across sizings that should have differed. 11 steps converge
#: (13 gives the same numbers) at +58% offset-MC time; the search itself uses the
#: analytic prediction, so only explicit MC calls pay.
_OFFSET_BISECT_RANGE_V = 0.06
_OFFSET_BISECT_ITERS = 11


def offset_bisect_resolution_v(n_iter=None):
    """Smallest offset difference this bisection can distinguish. `None` resolves the
    module default at call time — a default argument would bind it at definition time,
    which is the trap that made an earlier resolution experiment silently measure
    nothing when the module constant was patched."""
    if n_iter is None:
        n_iter = _OFFSET_BISECT_ITERS
    return 2.0 * _OFFSET_BISECT_RANGE_V / (2 ** (n_iter + 1))


def _offset_sample(p, dvth1, dvth2, n_iter=None):
    """Input-referred offset for one Vth-mismatch draw: bisect the differential
    input to the decision-flip point. No RNG here — deterministic per draw."""
    if n_iter is None:
        n_iter = _OFFSET_BISECT_ITERS       # resolved at call time, not definition
    lo, hi = -_OFFSET_BISECT_RANGE_V, _OFFSET_BISECT_RANGE_V
    s_lo = _decide_sign(p, lo, dvth1, dvth2)
    s_hi = _decide_sign(p, hi, dvth1, dvth2)
    if s_lo == 0.0 or s_hi == 0.0:
        return None                      # sim/parse failure — skip, don't fake a rail sample
    if (s_lo > 0) == (s_hi > 0):
        return hi if s_lo > 0 else lo    # offset beyond ±60mV range; clamp
    for _ in range(n_iter):
        mid = 0.5 * (lo + hi)
        s_mid = _decide_sign(p, mid, dvth1, dvth2)
        if (s_mid > 0) == (s_lo > 0):
            lo, s_lo = mid, s_mid
        else:
            hi, s_hi = mid, s_mid
    return 0.5 * (lo + hi)


#: Matched pairs whose Vth mismatch shows up as input-referred offset. `tail` is
#: excluded on purpose — one device, no differential partner, so its mismatch is
#: common-mode. The input pair keeps its own dedicated injection path.
OFFSET_PAIRS = ("input", "ncc", "pcc", "pre", "prei")


def pelgrom_sigma_v(p, dev):
    """Per-device Vth mismatch σ (volts) from that group's own area — Pelgrom
    σ_Vth = A_VT / √(W·L·M). Uses the effective L, so a PDK-raised length is
    credited."""
    area = max(gate_area_um2(p, dev), 1e-12)
    return (p["avt_mv_um"] / math.sqrt(area)) / 1000.0


# --- analytic offset budget, for use inside a search -------------------------
# The optimizer's offset penalty saw the input pair only, so minimising power it
# shrank the latch until latch mismatch dominated the real offset while the reported
# number improved. Fixing that needs a *predictor* cheap enough to run per candidate,
# which these constants provide. Every one of them is measured, not assumed:
#
#   input  R = 1.268, stable to 0.5% across a 13x input-width sweep (1.268..1.275),
#          measured as a MEDIAN over 5 estimator seeds at n_mc=16.
#
#          CORRECTION. This was published as 1.06 with a claimed 0.5% agreement, and
#          that was wrong: the agreement came from a single Monte-Carlo draw (seed 4242)
#          that happened to land there. The same sizing medians to 1.585 mV, not the
#          1.326 that single draw gave. So the textbook sqrt(2) = 1.414 the code
#          originally used was ~11% high, not 33% high, and replacing it with 1.06 made
#          the dominant term ~16% low — a regression dressed as a fix. Referring a
#          gate-side Vth shift to the input is still not quite 1:1 (the shift also moves
#          the tail current and common mode), but the correction is small.
#
#   ncc    the one term that actually mattered and was missing. Its contribution falls
#          9.3x as its own width goes 0.5 -> 16 um (1.794 -> 0.193 mV), so shrinking it
#          is genuinely expensive. Fitted over a 20-point grid in (input W, ncc W):
#          mean |error| 12.7%, worst 29.1% — crude, but the term it replaces was zero.
#
#   pcc    a weak power law in its OWN width, contrib = 0.318 * W^0.128, fitting the
#          measured 0.286 -> 0.442 mV over 0.5 -> 16 um to within 3%. Note the sign: its
#          contribution *rises* with width, because its leverage on the regeneration
#          grows faster than its sigma_Vth falls — so a sigma-proportional term would
#          penalise shrinking it, backwards. It was a flat constant until a per-term
#          comparison on optimizer output showed the constant over-predicting 111% at
#          the sub-micron widths the search picks, which cancelled ncc's
#          under-prediction in the RSS and made the total look better than it was.
#   pre,
#   prei   ~0.025-0.03 mV regardless of width, i.e. 150x below the input pair.
#          Negligible; carried as constants so the RSS is complete.
# EXACTLY sqrt(2), and not a fitted number. Measured deterministically, the input pair's
# input-referred offset is v = -d for a differential Vth mismatch d: v/d is 1.0000 to
# within 0.06% on all four backends and out to 4 sigma (see `input_referral_is_linear`).
# A linear response has sigma_out = sigma_in exactly, and the differential sigma of two
# independent devices is sqrt(2) * sigma_1dev. So the textbook value was right.
#
# This constant was published as 1.414, "corrected" to 1.06, then "corrected" to 1.268,
# and both corrections were wrong — by -25% and -10%, on the model's DOMINANT term, in the
# optimistic direction. All three errors have the same cause: a Monte-Carlo reference with
# a 21% standard error per estimate was treated as ground truth. It converges to sqrt(2)
# as n grows (-16.7% at n_mc=12, -3.4% at 64, +2.5% at 256) — it was never in conflict
# with the textbook, it was just noisy. Hence the deterministic reference below; the
# lesson is not about this constant, it is that a fit is only as good as its reference.
_OFFSET_R_INPUT = 1.4142135623730951
# The latch magnitude coefficient is PER MODEL — it spans 6.5x across the backends
# (0.115 on ptm45 to 0.747 on asap7), so a single global value calibrated on ptm45
# under-predicted asap7 by 41%, gaa2nm by 31% and sky130 by 14%. All in the optimistic
# direction, which is the dangerous one: the search shrinks the latch believing offset is
# fine. The exponents and the vcm term do transfer — measured, the vcm ratio at 0.82 is
# 3.55-4.30 across backends against a fit of 4.07 — so only K is split.
# The whole ncc law is per model, exponents included — because the exponents were the
# problem. Fitted on a 2-D grid (input W x ncc W varied independently, so the sigma
# exponent and the geometry exponent are separable; on a 1-D ncc sweep they are
# confounded) against the deterministic reference. The non-ptm45 backends want sigma^2.2
# to sigma^2.5 and essentially NO geometry-ratio dependence, against ptm45's sigma^0.68
# and ratio^0.37 — a different dependence, not a different scale, which is what the 174%
# width drift of a per-model-K-only fit was telling us.
#
# ptm45 keeps its original exponents: refitting them there made held-out error slightly
# WORSE (1.3% -> 1.6%), so the gate rejected it. Three of four accepted, one refused.
# Fitted on the 2-D grid PLUS the sizings the optimizer converges to. Including them is
# what closed the conservatism in the region that matters: a hand-drawn grid cannot show
# that bias, because the search does not sample sizings evenly — it goes wherever the model
# rates cheapest. This makes the fit a fixed-point iteration (the sizings depend on the
# constants being fitted), and one pass moved every backend the right way:
#
#   backend   fresh-set median      optimizer-region ratio
#   ptm45      3.9% ->  3.5%          1.31x -> 1.25x
#   asap7     11.4% ->  9.6%          1.53x -> 1.40x
#   gaa2nm    21.9% -> 10.9%          1.99x -> 1.82x
#   sky130    16.6% -> 10.7%          1.36x -> 1.30x
#
# The ratio column has to be measured AFTER installing, and that is not a formality. Judged
# at the sizings the OLD model converged to, the new law scores 1.36x and 1.55x on asap7 and
# gaa2nm; installed, the search moves to different sizings and the honest numbers are 1.40x
# and 1.82x. A fixed-point iteration cannot be evaluated at the previous fixed point.
#
# The acceptance gate required BOTH: fresh-set error had to improve AND the ratio had to
# stay >= 1.0. The second condition is the important one — a refit that made the numbers
# prettier by landing optimistic where the search lives would re-create the original defect,
# where the search gamed its own offset term. Nothing accepted here went below 1.
_OFFSET_NCC_BY_MODEL = {
    "ptm45":  (0.1067, 0.9163, 0.2965),
    "asap7":  (0.1217, 2.4253, -0.1705),
    "gaa2nm": (0.1154, 2.6029, -0.1779),
    "sky130": (0.2788, 2.7531, -0.2934),
}

#: How far the implied K still drifts across a 16x ncc-width sweep. This is the diagnostic
#: that found the problem: with global exponents it read 39% on ptm45 (where they were
#: fitted) but 82 / 174 / 176% elsewhere, which said the FORM was wrong, not the scale — a
#: single coefficient cannot absorb 176%. With per-model exponents it is 39 / 31 / 41 / 49%,
#: i.e. the non-ptm45 backends are now no worse than the one the model was derived on.
#: The Monte-Carlo reference hid all of this: 176% of drift is invisible behind an estimator
#: that scattered 27% between seeds and read 11% low on top of that.
_OFFSET_NCC_K_WIDTH_DRIFT = {"ptm45": 0.39, "asap7": 0.31, "gaa2nm": 0.41, "sky130": 0.49}
# Fallback for a backend with no entry above. Deliberately NOT a derived view of the table:
# a `{m: v[0] for ...}` convenience dict existed for one commit and immediately became a
# trap — the calibration loop patched it, the model read the real table, and every
# candidate was silently ignored. There is one place the ncc law lives.
_OFFSET_NCC_K, _OFFSET_NCC_A, _OFFSET_NCC_B = _OFFSET_NCC_BY_MODEL["ptm45"]
# The latch term also depends on the input common mode, and strongly — measured, ncc's
# contribution grows 7x as vcm_frac goes 0.62 -> 0.90 while the input pair's stays flat.
# The model had no such term, which is the bulk of why it under-predicted ~41% on
# optimizer output: the corner-feasibility step raises vcm_frac to 0.82, where the
# multiplier is already 4.3x. exp fit to +/-6% over that range, referenced to 0.62.
_OFFSET_NCC_VCM_REF, _OFFSET_NCC_VCM_K = 0.62, 7.02
# pcc and the precharge flats stay GLOBAL, deliberately — retested after the ncc law became
# per model (the first test could have been masked by ncc's much larger error) and still not
# adopted: per-model pcc helps only sky130 (10.7% -> 7.3% fresh) and HURTS asap7 (9.6% ->
# 11.8%) and gaa2nm (10.9% -> 12.7%). No consistent signal, so one law and fewer constants.
# Their measured spread across
# backends is large (pcc 0.048 mV on sky130 to 1.40 mV on asap7; prei 50x between them),
# so per-model versions were fitted and tested — and they did not earn their place. On a
# held-out set of 8 sizings, splitting them changed the error by at most ~1 point and made
# sky130 worse (17.7% -> 21.1%). Only per-model `ncc` K earned its keep (asap7 49% -> 23%).
# Shipping four per-backend micro-decisions worth ~1 point each would be fitting the
# validation set, not the circuit.
# The values themselves ARE updated: refit against the deterministic reference, the pcc law
# moves 0.3176*W^0.1283 -> 0.3161*W^0.1464 and the flats 0.030 -> 0.0067/0.0054 (the old
# 0.030 was itself a correction of a 0.484 that was pure bisection floor).
_OFFSET_FLAT_MV = {"pre": 0.0067, "prei": 0.0054}
_OFFSET_PCC_K, _OFFSET_PCC_P = 0.3161, 0.1464


#: Median |error| of the analytic budget against the deterministic reference on a
#: validation set that neither the fit NOR the acceptance gate ever saw, and which
#: deliberately reaches outside the fitted ranges (ncc 0.4 and 16 um, input 2 and 50 um).
#: Worst case in that set: 24 / 38 / 57 / 42%.
#:
#: These are deliberately the pessimistic numbers. Three other figures were available and
#: all of them flatter:
#:   - at the SEED sizing, where K is fitted: -0.2% to -0.0% on every backend
#:   - on the 8-sizing set used to ACCEPT the fit: 1.3 / 3.7 / 10.0 / 9.9%
#:   - on this fresh set:                        3.9 / 11.4 / 21.9 / 16.6%   <- recorded
#: The gap between the second and third is selection: gate on a set and it stops being an
#: independent estimate of anything. Quoting the seed figure would have claimed a model
#: exact everywhere while it was ~55% wrong one sizing away.
_OFFSET_MODEL_HELDOUT_ERR = {"ptm45": 0.035, "asap7": 0.096, "gaa2nm": 0.109,
                             "sky130": 0.107}

#: predicted / measured at the sizings the OPTIMIZER converges to, median over 3 seeds.
#: A separate number from the one above because the search does not sample sizings evenly
#: — it seeks out whatever the model rates cheapest, so its converged region has its own
#: bias, larger here than the validation-set error. Reproducible: asap7 and gaa2nm return
#: the same ratio on every seed.
#:
#: All four are ABOVE 1, i.e. the model now over-predicts offset where it is used. That is
#: the safe direction — the search over-sizes rather than shipping a design that misses —
#: and it is the opposite of where this model started, when the same selection effect ran
#: optimistic and was the reason the search could game its own offset term. But 1.99x on
#: gaa2nm means roughly twice the latch area that offset actually requires, so it is a real
#: cost, not just a comfortable margin. Closing it means including optimizer-converged
#: sizings in the fit — `scripts/calibrate_offset_model.py` does that via
#: `optimizer_sizings()` — which is a fixed-point iteration, since the sizings depend on
#: the constants being fitted. One pass is done — it brought gaa2nm from 1.99x to 1.55x and
#: every backend closer — gated on the ratio never dropping below 1.0, since a refit that
#: landed optimistic here would re-create the defect where the search gamed its own offset
#: term. Further passes are available and converge slowly — gaa2nm moved 1.99x -> 1.82x on
#: this one, having looked like 1.55x before the search was allowed to move.
_OFFSET_MODEL_OPT_REGION_BIAS = {"ptm45": 1.25, "asap7": 1.40, "gaa2nm": 1.82,
                                 "sky130": 1.30}


def offset_model_accuracy(p):
    """How far the analytic budget is known to sit from measurement on this backend.

    Reports the number, not a `calibrated: true/false`: a boolean reading "true" for a
    backend that is 23% wrong out of sample is the same false reassurance a single global
    constant gave. Deliberately quotes HELD-OUT error, since the fitted point flatters."""
    m = p.get("model") or "ptm45"
    e = _OFFSET_MODEL_HELDOUT_ERR.get(m)
    if e is None:
        note = ("no held-out error measured for this backend; the constants are ptm45 "
                "fits, and on the backends where that was tested they were 39-52% out")
    elif e < 0.05:
        note = (f"the functional form was derived on this backend; error {e:.0%} on a "
                f"validation set the fit and the gate never saw")
    else:
        note = (f"error {e:.0%} on a validation set the fit and the gate never saw — the "
                f"law is fitted per backend but this is a screening number, not a sign-off "
                f"one. Judge a final design against a measured offset_budget()")
    bias = _OFFSET_MODEL_OPT_REGION_BIAS.get(m)
    if bias:
        note += (f". Separately, at the sizings the optimizer converges to it "
                 f"over-predicts {bias:.2f}x — the safe direction, but it means a "
                 f"converged design carries roughly that much offset margin over what it "
                 f"needs, so check the measured budget before accepting the area")
    return {
        "model": m,
        "has_own_latch_law": m in _OFFSET_NCC_BY_MODEL,
        "heldout_median_abs_error": e,
        "optimizer_region_bias": bias,
        "latch_k_width_drift": _OFFSET_NCC_K_WIDTH_DRIFT.get(m),
        "reference": "deterministic (Gauss-Hermite quadrature)",
        "note": note,
    }


def predicted_offset_budget_mv(p):
    """Analytic RSS offset budget over all matched pairs, no simulation.

    Replaces the input-pair-only prediction inside the cost function. Accurate to
    ~13% on the ncc term and exact in form for the input pair; see the constants
    above for what each term is and how it was measured. Use `offset_budget` when
    you want the measured answer."""
    terms = {"input": _OFFSET_R_INPUT * pelgrom_sigma_v(p, "input") * 1e3}
    sig_ncc = pelgrom_sigma_v(p, "ncc") * 1e3
    di, dn = p["devices"]["input"], p["devices"]["ncc"]
    ratio = max((di["w_um"] * di["m"]) / max(dn["w_um"] * dn["m"], 1e-9), 1e-9)
    vcm_mult = math.exp(_OFFSET_NCC_VCM_K * (p["vcm_frac"] - _OFFSET_NCC_VCM_REF))
    model = p.get("model") or "ptm45"
    k, a, b = _OFFSET_NCC_BY_MODEL.get(
        model, (_OFFSET_NCC_K, _OFFSET_NCC_A, _OFFSET_NCC_B))
    terms["ncc"] = k * (sig_ncc ** a) * (ratio ** b) * vcm_mult
    dp = p["devices"]["pcc"]
    terms["pcc"] = _OFFSET_PCC_K * max(dp["w_um"], 1e-9) ** _OFFSET_PCC_P
    terms.update(_OFFSET_FLAT_MV)
    return math.sqrt(sum(v * v for v in terms.values())), terms


# Gauss-Hermite nodes/weights for the PROBABILISTS' weight (standard normal), weights
# normalised to sum to 1 so `sum(w_i f(x_i))` is E[f(X)] for X ~ N(0,1) directly.
# Hardcoded rather than pulled from numpy: run_sim has no numpy dependency and should not
# acquire one for five constants. `test_quadrature_rule_is_exact` validates them by
# integrating x^k, which pins every digit without needing numpy to compare against.
_GAUSS_HERMITE = {
    3: ((-1.7320508075688774, 0.0, 1.7320508075688774),
        (0.16666666666666666, 0.6666666666666667, 0.16666666666666666)),
    5: ((-2.8569700138728056, -1.355626179974266, 0.0, 1.355626179974266,
         2.8569700138728056),
        (0.011257411327720686, 0.22207592200561257, 0.5333333333333334,
         0.22207592200561257, 0.011257411327720686)),
    7: ((-3.750439717725742, -2.3667594107345415, -1.1544053947399682, 0.0,
         1.1544053947399682, 2.3667594107345415, 3.750439717725742),
        (0.0005482688559722177, 0.030757123967586498, 0.2401231786050127,
         0.45714285714285724, 0.2401231786050127, 0.030757123967586498,
         0.0005482688559722177)),
    9: ((-4.512745863399783, -3.20542900285647, -2.07684797867783, -1.0232556637891326,
         0.0, 1.0232556637891326, 2.07684797867783, 3.20542900285647, 4.512745863399783),
        (2.23458440077466e-05, 0.002789141321231769, 0.049916406765217865,
         0.24409750289493945, 0.4063492063492063, 0.24409750289493945,
         0.049916406765217865, 0.002789141321231769, 2.23458440077466e-05)),
}
#: 5 nodes and 16 bisection steps: at 16 steps the answer agrees to 0.04% across 3, 5, 7
#: and 9 nodes, so 5 is comfortable margin rather than a compromise. At the old 11-step
#: default the same sweep scattered 5.1% — the limit was never the number of nodes, it was
#: that one bisection LSB (0.029 mV) is 14% of the response at the inner nodes.
_OFFSET_QUAD_NODES = 5
_OFFSET_QUAD_ITERS = 16


def _offset_response(p, group, d, n_iter=None):
    """Input-referred offset for a single differential Vth mismatch `d` on `group`.

    One entry point for both paths, because the input pair goes through
    `_offset_sample`'s own two arguments while every other group is injected as a series
    gate source. For the input pair only the DIFFERENCE matters — putting `d` on one
    device and splitting it +d/2 / -d/2 give bit-identical results, and a pure
    common-mode shift moves the offset by one LSB, i.e. not at all — so `(d, 0)` is
    exact rather than an approximation."""
    if group == "input":
        return _offset_sample(p, d, 0.0, n_iter=n_iter)
    q = {**p, "mismatch_v": {**(p.get("mismatch_v") or {}), group: d}}
    return _offset_sample(q, 0.0, 0.0, n_iter=n_iter)


def _offset_of_pair_quad(p, group, sigma_v, nodes=None, n_iter=None):
    """Input-referred offset sigma for one matched pair, by Gauss-Hermite quadrature.

    Deterministic, and cheaper than the Monte-Carlo path it replaces. The reason it can
    be: each group's mismatch enters as a SINGLE scalar d ~ N(0, sigma_v*sqrt(2)), so
    this is a one-dimensional expectation, not a sampling problem. Monte Carlo on a 1-D
    Gaussian buys nothing but variance — at n_mc=12 the estimate carried a 21% standard
    error and the same sizing returned 0.42, 0.51, 0.39 mV on three seeds.

    5 nodes at 16 bisection steps land within 0.04% of the 9-node answer using 5
    bisections where the MC path used 12, and the result repeats bit-for-bit."""
    x, w = _GAUSS_HERMITE[nodes or _OFFSET_QUAD_NODES]
    if n_iter is None:
        n_iter = _OFFSET_QUAD_ITERS
    sd = sigma_v * math.sqrt(2.0)
    vals = pmap(lambda xi: _offset_response(p, group, xi * sd, n_iter=n_iter), list(x))
    usable = [(wi, v) for wi, v in zip(w, vals) if v is not None]
    if len(usable) < len(x):
        return {"pelgrom_sigma_vth_mv": round(sigma_v * 1e3, 4),
                "offset_sigma_mv": None, "method": "quadrature",
                "error": f"{len(x) - len(usable)} of {len(x)} quadrature nodes failed to "
                         f"converge; a partial rule is not a weaker estimate, it is a "
                         f"wrong one, so no number is reported"}
    m = sum(wi * v for wi, v in usable)
    m2 = sum(wi * v * v for wi, v in usable)
    return {"pelgrom_sigma_vth_mv": round(sigma_v * 1e3, 4),
            "offset_sigma_mv": round(math.sqrt(max(m2 - m * m, 0.0)) * 1e3, 4),
            "offset_mean_mv": round(m * 1e3, 4),
            "method": "quadrature", "nodes": len(x),
            "resolution_mv": round(offset_bisect_resolution_v(n_iter) * 1e3, 6)}


def input_referral_is_linear(params, sigmas=(0.5, 1.0, 2.0, 3.0, 4.0), n_iter=16):
    """Verify the property `_OFFSET_R_INPUT = sqrt(2)` rests on, rather than fitting it.

    Returns v/d at each multiple of the differential sigma. If the response is linear
    these are all 1.0 and the referral factor is sqrt(2) exactly; if a backend ever
    breaks linearity this is what says so, instead of a refitted constant absorbing it
    into an average."""
    p = _full(params)
    sd = pelgrom_sigma_v(p, "input") * math.sqrt(2.0)
    out = {}
    for a in sigmas:
        v = _offset_response(p, "input", a * sd, n_iter=n_iter)
        out[a] = None if v is None else round(-v / (a * sd), 5)
    got = [r for r in out.values() if r is not None]
    return {"ratios": out, "max_deviation": (max(abs(r - 1.0) for r in got) if got else None),
            "linear": bool(got) and max(abs(r - 1.0) for r in got) < 0.01,
            "implied_r_input": round(math.sqrt(2.0), 6)}


def offset_budget(params, n_mc=12, seed=4242, groups=OFFSET_PAIRS, method="quadrature"):
    """Which devices the offset is actually made of.

    `measure_offset` models the input pair only — the code called latch and tail
    mismatch "a documented extension point", and for a StrongARM that omission
    matters: the cross-coupled pair fires exactly when regeneration is deciding, so
    its Vth mismatch steers the outcome, and the precharge pair leaves the outputs
    at unequal starting points. A real offset budget names the contributors.

    Each group is perturbed by its **own** Pelgrom σ (from its own W·L·M), one
    group at a time, and the resulting input-referred offset σ is measured the same
    way as the input pair's: bisect the differential input to the decision-flip
    point. Reporting them separately is the point — it says which device to grow.

    `method="quadrature"` (default) evaluates the expectation by Gauss-Hermite
    quadrature; `"mc"` keeps the Monte-Carlo path. Quadrature is the default because
    each group's mismatch is a single scalar, so this is a 1-D expectation and sampling
    it only adds variance: the MC path carried a 21% standard error at n_mc=12 and
    scattered 27% between seeds, which is larger than most of the differences this
    function is used to resolve. Three separate constants in the analytic model were
    mis-fitted against that noise. `n_mc`/`seed` apply to `"mc"` only."""
    p = _full(params)
    p = {**p, "n_mc": n_mc}
    per = {}
    for g in groups:
        sig = pelgrom_sigma_v(p, g)
        if method == "quadrature":
            per[g] = _offset_of_pair_quad(p, g, sig)
            continue
        if g == "input":
            # existing dedicated path (series sources already in the deck)
            import random
            per[g] = {"pelgrom_sigma_vth_mv": round(sig * 1e3, 4), "method": "mc",
                      **{k: v for k, v in measure_offset(p, random.Random(seed)).items()
                         if k in ("offset_sigma_mv", "offset_mean_mv", "n_mc")}}
            continue
        per[g] = _offset_of_pair(p, g, sig, n_mc, seed)
    # RSS of the per-group contributions — independent devices, so σ's add in
    # quadrature. Reported next to the input-pair-only figure it replaces.
    contrib = [v["offset_sigma_mv"] for v in per.values()
               if v.get("offset_sigma_mv") is not None]
    total = math.sqrt(sum(c * c for c in contrib)) if contrib else None
    ranked = sorted((k for k in per if per[k].get("offset_sigma_mv") is not None),
                    key=lambda k: -per[k]["offset_sigma_mv"])
    return {
        "per_device": per,
        "total_sigma_mv": round(total, 4) if total is not None else None,
        "input_only_sigma_mv": per.get("input", {}).get("offset_sigma_mv"),
        "dominant": ranked,
        "excluded": {"tail": "single device, no differential partner — its mismatch "
                             "is common-mode, not offset"},
        "method": method,
        "note": ("each group perturbed by its own Pelgrom σ from its own W·L·M, one "
                 "at a time; total is the RSS over independent contributors. Grow "
                 "the area of whatever leads `dominant` — growing anything else "
                 "buys proportionally less."),
    }


def _offset_of_pair(p, group, sigma_v, n_mc, seed, n_iter=None):
    """Input-referred offset σ from one matched pair's Vth mismatch, by the same
    bisection the input pair uses — but with a finer bisection by default, because
    these contributions are small enough that the 7-step default *is* the answer
    (0.47 mV) rather than a bound on it."""
    import random
    # `hash(group)` here was salted per process (PYTHONHASHSEED), so this function took a
    # `seed` and did not reproduce across runs — `hash("ncc") % 10000` returned 7174,
    # 8200 and 5952 on three consecutive interpreters. Every non-input reference number
    # ever recorded came from a draw set that cannot be replayed, including the
    # calibration history. zlib.crc32 is stable across processes and versions.
    import zlib
    rng = random.Random(seed + zlib.crc32(group.encode()) % 10000)
    draws = [rng.gauss(0.0, sigma_v * math.sqrt(2)) for _ in range(n_mc)]
    vals = [v for v in pmap(lambda d: _offset_response(p, group, d, n_iter=n_iter),
                            draws) if v is not None]
    if len(vals) < 2:
        return {"pelgrom_sigma_vth_mv": round(sigma_v * 1e3, 4),
                "offset_sigma_mv": None, "n_mc": len(vals),
                "error": "not enough usable samples"}
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
    return {"pelgrom_sigma_vth_mv": round(sigma_v * 1e3, 4),
            "offset_sigma_mv": round(math.sqrt(var) * 1e3, 4),
            "offset_mean_mv": round(mean * 1e3, 4), "n_mc": len(vals),
            "method": "mc",
            "resolution_mv": round(offset_bisect_resolution_v(n_iter) * 1e3, 5)}


def clock_edge_sweep(params, trf_ps=None):
    """How much clock quality this comparator needs.

    Reported as **max f_clk vs edge rate**, not decision time vs edge rate, because
    the latter is nearly flat and would say "edge rate does not matter". It looks
    flat for a measurement reason: `tdec` is timed from the clock's own VDD/2
    crossing, so a slower edge shifts the trigger along with the response. Measured,
    decision time moves 1.3% across a 100x edge-rate range.

    What the edge rate really costs is headroom. The tail switch turns on and the
    precharge PMOS turns off from the *same* edge, so a slow edge has them both
    partly conducting — wasting the start of the evaluate phase.

    **It only matters when the design is near its own limit**, so run this at the
    operating point you intend. Measured on the seed sizing: at the default
    vcm_frac 0.62 (max 0.667 GHz) the edge rate changes nothing at all — 1.0x across
    5..200 ps. At vcm_frac 0.95 (max 2.0 GHz) it costs 2.0x: 2.0 GHz up to a 50 ps
    edge, 1.25 GHz at 100 ps, 1.0 GHz at 200 ps. A comparator with headroom does not
    care about clock quality; one running at its limit sets a clock-tree spec.

    (No clk/clkb skew here: single-clock topology, so the race is between two
    devices on one edge, not between two clock phases.)"""
    p0 = _full(params)
    if trf_ps is None:
        trf_ps = [5, 12, 25, 50, 100, 200]
    trf_ps = sorted({float(t) for t in trf_ps} | {float(p0.get("clk_trf_ps", 12.0))})

    def one(trf):
        p = {**p0, "clk_trf_ps": trf}
        mf = max_fclk_sweep(p)
        nom = run_sim(p, do_offset=False)["nominal"]
        return {"clk_trf_ps": trf,
                "max_fclk_ghz": mf.get("max_fclk_ghz"),
                "energy_fj_at_max": mf.get("energy_fj_at_max"),
                "decision_time_ps": nom.get("decision_time_ps"),
                "power_uw": nom.get("power_uw")}

    pts = pmap(one, trf_ps)
    ok = [r for r in pts if r["max_fclk_ghz"]]
    best = max(ok, key=lambda r: r["max_fclk_ghz"]) if ok else None
    worst = min(ok, key=lambda r: r["max_fclk_ghz"]) if ok else None
    ts = [r["decision_time_ps"] for r in pts if r["decision_time_ps"]]
    return {
        "points": pts,
        "best": best, "worst": worst,
        "fclk_spread": (round(best["max_fclk_ghz"] / worst["max_fclk_ghz"], 3)
                        if best and worst and worst["max_fclk_ghz"] else None),
        "decision_time_spread": (round(max(ts) / min(ts), 3) if len(ts) > 1 else None),
        "at_current_trf": next((r for r in pts
                                if r["clk_trf_ps"] == float(p0.get("clk_trf_ps", 12.0))), None),
        "no_clkb_note": ("single-clock topology — the tail switch and the precharge "
                         "PMOS share `clk`, so there is no clk/clkb skew to sweep"),
        "note": ("decision time is nearly flat in edge rate because it is timed from "
                 "the clock's own VDD/2 crossing; max f_clk is where the cost shows "
                 "up, since a slow edge overlaps tail turn-on with precharge "
                 "turn-off and eats the evaluate window."),
    }


def _decide_after_prime(p, prime_v, vdiff):
    """Polarity of the SECOND decision, given the first was forced by `prime_v`."""
    out = _run(gen_netlist({**p, "prime_v": prime_v}, vdiff=vdiff))
    f2 = _parse(out, "fdiff2")
    return f2


def measure_hysteresis(params, prime_v=0.2, clk_period_ns=1.0, n_iter=8):
    """Decision-to-decision memory: does the previous result bias the next one?

    A StrongARM's internal nodes must return to the rails during precharge. If they
    do not, the state left over from the last decision adds to the next one — a
    data-dependent offset. In a SAR ADC that is worse than a static offset because
    it correlates with the code being converted, so it does not calibrate out.

    The default deck evaluates once and cannot see this. Here the input is a
    two-step PWL: a large priming differential decides cycle 1, then the input moves
    to the value under test and **cycle 2 is what is measured**. Bisecting cycle 2's
    threshold for each priming polarity gives two thresholds; the gap between them is
    the input-referred hysteresis.

    `clk_period_ns` matters: with a long period the latch has ample precharge time
    and the hysteresis should vanish. Squeeze the period and it appears. That is the
    knob this exists to explore, so it is an argument rather than a fixed value."""
    p = _full(params)
    hi = clk_period_ns / 2.0
    p = {**p, "clk_period_ns": clk_period_ns, "clk_high_ns": hi,
         # two full cycles plus settling, and measure late in each evaluate
         "tstop_ns": round(0.2 + 2 * clk_period_ns + 0.05, 4),
         "iavg_to_ns": round(0.2 + clk_period_ns, 4)}

    def threshold(prime):
        """Bisect the cycle-2 input that flips the cycle-2 decision."""
        lo, hi_ = -0.06, 0.06
        s_lo = _decide_after_prime(p, prime, lo)
        s_hi = _decide_after_prime(p, prime, hi_)
        if s_lo is None or s_hi is None:
            return None
        if (s_lo > 0) == (s_hi > 0):
            return None                     # never flips in range — not usable
        for _ in range(n_iter):
            mid = 0.5 * (lo + hi_)
            s_mid = _decide_after_prime(p, prime, mid)
            if s_mid is None:
                return None
            if (s_mid > 0) == (s_lo > 0):
                lo, s_lo = mid, s_mid
            else:
                hi_, s_hi = mid, s_mid
        return 0.5 * (lo + hi_)

    th_pos, th_neg = pmap(threshold, [abs(prime_v), -abs(prime_v)])
    if th_pos is None or th_neg is None:
        return {"error": "cycle-2 threshold did not bracket a flip — try a longer "
                         "clk_period_ns or a smaller prime_v",
                "clk_period_ns": clk_period_ns, "prime_v": prime_v}
    hyst = th_pos - th_neg
    # The mechanism, probed at the end of cycle 1's precharge. What matters is the
    # DIFFERENTIAL residue, not the absolute levels: at 0.45 ns the outputs sit at
    # 0.681 and 0.712 V, so an absolute ">0.9·VDD" check passes on both while 31 mV
    # of differential memory survives. That is exactly the blind spot in
    # max_fclk_sweep's `reset_ok`, which uses the absolute criterion.
    out = _run(gen_netlist({**p, "prime_v": abs(prime_v)}, vdiff=0.0))
    vrp, vrn = _parse(out, "vrst1p"), _parse(out, "vrst1n")
    resid = (vrp - vrn) if (vrp is not None and vrn is not None) else None
    # bisection resolution: a hysteresis at or below one step is not resolved
    step = 0.12 / (2 ** n_iter)
    return {
        "clk_period_ns": clk_period_ns, "prime_v": prime_v,
        "threshold_after_pos_mv": round(th_pos * 1e3, 4),
        "threshold_after_neg_mv": round(th_neg * 1e3, 4),
        "hysteresis_mv": round(abs(hyst) * 1e3, 4),
        "resolution_mv": round(step * 1e3, 4),
        "resolved": abs(hyst) > 1.5 * step,
        "sign": ("previous decision attracts the next (incomplete reset leaves the "
                 "latch leaning the same way)" if hyst < 0 else
                 "previous decision repels the next"),
        "reset_v": {"outp": vrp, "outn": vrn},
        "reset_residue_mv": round(resid * 1e3, 4) if resid is not None else None,
        "reset_absolute_ok": (vrp is not None and vrn is not None
                              and vrp > 0.9 * p["vdd"] and vrn > 0.9 * p["vdd"]),
        "note": ("measured on the SECOND of two decisions; the gap between the two "
                 "priming polarities is the input-referred memory. Compare against "
                 "the offset σ — hysteresis does not calibrate out, because it "
                 "tracks the data. `reset_absolute_ok` can be true while "
                 "`reset_residue_mv` is large: the absolute level check that "
                 "max_fclk uses is necessary but not sufficient, because the memory "
                 "is differential."),
    }


def cm_range_sweep(params, vcm_fracs=None, with_offset=False, n_mc=8):
    """Input common-mode range: where the comparator works, and what the operating
    point costs.

    `vcm_frac` existed as a parameter but nothing swept it, so two things stayed
    invisible: the hard lower bound below which the latch never resolves, and how
    much speed the chosen operating point is giving up.

    **Why this is not a CMRR number.** CMRR would be ΔVcm/ΔVos on the *systematic*
    offset, but this deck is perfectly symmetric — both halves are identical devices
    into identical loads — so with zero mismatch the systematic offset is zero at
    every Vcm and CMRR is infinite. Probing it returns the bisection's own
    quantisation step (60 mV / 2⁷ ≈ 0.47 mV) at every point, which is an artifact,
    not a measurement. Real CMRR comes from asymmetry this netlist does not have
    (layout, loading, systematic gradients). What *is* measurable is reported here.

    `with_offset` re-runs the **input pair's** mismatch Monte-Carlo at each point. It is
    off by default because it costs ~90 sims per point and that term is genuinely flat:
    the input pair's Vth mismatch refers to the input gate-to-gate, so it is
    Vcm-independent to first order — measured constant to 3 significant figures across
    the usable range.

    **The total offset is NOT flat, and an earlier version of this docstring said it
    was.** The latch's contribution grows ~7x over the same sweep (ncc 0.72 -> 5.05 mV
    as vcm_frac goes 0.62 -> 0.90) because the latch mismatch is referred through a
    shrinking overdrive. So raising the operating point for speed is *not* free — it is
    paid for in offset, through the latch rather than the input pair. Use
    `offset_budget` (or the analytic `predicted_offset_budget_mv`, which now carries the
    vcm term) to price it; `with_offset` here only shows the flat part."""
    p0 = _full(params)
    if vcm_fracs is None:
        vcm_fracs = [round(0.40 + 0.05 * i, 3) for i in range(12)]   # 0.40 .. 0.95
    # always include the caller's own operating point, or the report cannot say
    # what their current choice costs
    vcm_fracs = sorted({round(float(v), 4) for v in vcm_fracs} | {round(float(p0["vcm_frac"]), 4)})

    def one(vf):
        p = {**p0, "vcm_frac": vf}
        nom = run_sim(p, do_offset=False)["nominal"]
        row = {"vcm_frac": vf, "vcm_v": round(vf * p0["vdd"], 4),
               "decision_time_ps": nom.get("decision_time_ps"),
               "power_uw": nom.get("power_uw"),
               "functional": bool(nom.get("functional")) and nom.get("decision_time_ps") is not None}
        if with_offset:
            import random
            row["offset_sigma_mv"] = measure_offset({**p, "n_mc": n_mc},
                                                    random.Random(7)).get("offset_sigma_mv")
        return row

    pts = pmap(one, vcm_fracs)
    ok = [r for r in pts if r["functional"]]
    fastest = min(ok, key=lambda r: r["decision_time_ps"]) if ok else None
    slowest = max(ok, key=lambda r: r["decision_time_ps"]) if ok else None
    return {
        "points": pts,
        "usable_vcm_frac": [ok[0]["vcm_frac"], ok[-1]["vcm_frac"]] if ok else None,
        "usable_vcm_v": [ok[0]["vcm_v"], ok[-1]["vcm_v"]] if ok else None,
        "n_nonfunctional": len(pts) - len(ok),
        "fastest": fastest, "slowest": slowest,
        "speed_spread": (round(slowest["decision_time_ps"] / fastest["decision_time_ps"], 2)
                         if fastest and slowest and fastest["decision_time_ps"] else None),
        "at_current_vcm": next((r for r in pts if r["vcm_frac"] == p0["vcm_frac"]), None),
        "cmrr_note": ("no CMRR figure: the deck is symmetric, so systematic offset — "
                      "and hence CMRR — is structurally zero/infinite. Probing it "
                      "returns the bisection quantisation step, not a measurement."),
        "note": ("the INPUT PAIR's offset σ is flat in Vcm (its mismatch is "
                 "gate-referred), but the total is not: the latch's contribution grows "
                 "~7x over this sweep, so a higher operating point buys speed and pays "
                 "for it in offset. Price it with offset_budget. Below the usable range "
                 "the latch does not resolve at all — a hard bound, not a slow corner."),
    }


def measure_kickback(params, rs_ohm=2000.0, cs_ff=50.0, vdiff=0.005):
    """Input-referred kickback: how much the comparator disturbs the voltage it is
    supposed to be measuring.

    When the outputs slew during regeneration, the input pair pushes charge back
    through Cgd into whatever is driving the gates. In a SAR ADC that is the DAC's
    held sample, so the disturbance corrupts the very value being compared — and
    every later bit decision in that conversion. It is a standard comparator spec
    and one the ideal-source deck cannot show at all: with `rs_ohm = 0` the source
    holds the gate rigid and the measured kickback is exactly zero, by construction.

    `rs_ohm` is the driver's output impedance and `cs_ff` the held sampling
    capacitance; both are properties of the *system around* the comparator, so they
    are inputs, not circuit parameters. Defaults are a plausible SAR front end
    (2 kΩ, 50 fF) — set them to your DAC's real values before believing the number.

    Reports the peak single-ended excursion, the peak differential excursion (the
    part that survives a differential DAC and directly adds to offset), and where
    the differential lands by the end of the evaluate phase (residual, which is
    what the next comparison inherits)."""
    p = _full(params)
    p = {**p, "rs_ohm": float(rs_ohm), "cs_ff": float(cs_ff)}
    out = _run(gen_netlist(p, vdiff=vdiff))
    g = {k: _parse(out, k) for k in ("kbp_max", "kbp_min", "kbn_max", "kbn_min",
                                     "kbd_max", "kbd_min", "kbd_end", "tdec", "fdiff")}
    if g["kbp_max"] is None or g["kbd_max"] is None:
        return {"error": "kickback measurement failed (comparator did not resolve?)",
                "rs_ohm": rs_ohm, "cs_ff": cs_ff}
    vcm = p["vcm_frac"] * p["vdd"]
    rest_p, rest_n = vcm + vdiff / 2.0, vcm - vdiff / 2.0
    # peak deviation from the resting value, whichever direction it went
    se_p = max(abs(g["kbp_max"] - rest_p), abs(g["kbp_min"] - rest_p))
    se_n = max(abs(g["kbn_max"] - rest_n), abs(g["kbn_min"] - rest_n))
    d_rest = vdiff
    d_pk = max(abs(g["kbd_max"] - d_rest), abs(g["kbd_min"] - d_rest))
    return {
        "rs_ohm": rs_ohm, "cs_ff": cs_ff, "vdiff_v": vdiff,
        "kickback_se_mv": round(max(se_p, se_n) * 1e3, 4),
        "kickback_diff_mv": round(d_pk * 1e3, 4),
        "residual_diff_mv": round((g["kbd_end"] - d_rest) * 1e3, 4)
        if g["kbd_end"] is not None else None,
        "decision_time_ps": round(g["tdec"] * 1e12, 2) if g["tdec"] else None,
        "functional": g["fdiff"] is not None and abs(g["fdiff"]) > 0.7 * p["vdd"],
        "note": ("differential kickback is the part that adds to offset; the "
                 "single-ended figure also matters for a single-ended DAC. "
                 "rs_ohm/cs_ff describe the driver, not the comparator — set them "
                 "to the real front end before using the number."),
    }


def measure_offset(p, rng, n_iter=None):
    """Input-referred offset sigma via Monte Carlo input-pair Vth mismatch.

    For each sample we perturb the input-pair threshold voltages (Pelgrom:
    sigma_vth = AVT / sqrt(W*L*M)) and bisect the differential input to find
    the metastable point; that input value is the input-referred offset for
    the sample. Sigma over samples is the reported offset. (Input-pair
    mismatch is the dominant term; latch/tail mismatch is a documented
    extension point.)"""
    # effective L: on sky130 the netlist raises L to the device's bin floor, and
    # injecting mismatch for the requested L would model a device never built
    area_um2 = max(gate_area_um2(p, "input"), 1e-12)
    sigma_vth = (p["avt_mv_um"] / math.sqrt(area_um2)) / 1000.0  # volts, per device
    # pre-draw all mismatch pairs in-order (keeps the RNG sequence / reproducibility
    # identical to the serial version), then bisect each sample in parallel — the
    # samples are independent and each ngspice call releases the GIL.
    pairs = [(rng.gauss(0.0, sigma_vth), rng.gauss(0.0, sigma_vth)) for _ in range(p["n_mc"])]
    offsets = pmap(lambda ab: _offset_sample(p, ab[0], ab[1], n_iter=n_iter), pairs)
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
    # _full, not a local copy of the merge: this function used to duplicate it,
    # so per-model defaults added to _full (A_VT, nominal L) silently did not
    # apply to the main entry point — asap7 kept running at the 45 nm-class seed
    # length through the API while the UI got 21 nm.
    p = _full(params)
    rng = random.Random(seed)
    result = {"nominal": measure_nominal(p, with_noise=with_noise)}
    if do_offset:
        result["offset"] = measure_offset(p, rng)
    result["params"] = p
    return result



def _probit(p):
    """표준정규 역CDF Φ⁻¹(p) — 이분법(math.erfc 기반), 의존성 없음."""
    lo, hi = -8.0, 8.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if 0.5 * math.erfc(-mid / math.sqrt(2.0)) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def noise_probit(params, points=5, n_per_point=24, seed0=1000):
    """입력환산 노이즈의 SPICE 실측 — 프로빗(noise-counting) 방법.

    준안정점 주변의 DC 입력 vin 에서, 입력쌍 열잡음(S_v = 2·4kTγ/gm)을
    trnoise 소스로 게이트에 주입한 클록 판정을 시드만 바꿔 반복하고
    P(결정=+|vin) 을 센다. 가우시안 노이즈면 P = Φ(vin/σ) 이므로 probit
    선형화 Φ⁻¹(P) = vin/σ 의 기울기에서 σ 를 얻는다. 해석적
    √(2γkT/(gm·t_int)) 추정의 교차검증 (방법론은 공개 comparator 스킬
    계열의 표준 기법 — 구현은 자체, VCO 지터 실측과 같은 주입 방식)."""
    p = _full(params)
    nom = measure_nominal(p)
    dec = nom.get("decision_time_ps")
    est = _estimate_noise(p, dec)          # 해석적 σ (µVrms) — 스윕 스케일
    if not est:
        return {"error": "해석적 노이즈 추정 실패(비기능?) — 프로빗 스윕 스케일을 정할 수 없습니다."}
    vcm = p["vcm_frac"] * p["vdd"]
    i0, i1 = _input_id(p, vcm), _input_id(p, vcm + 0.005)
    gm = (i1 - i0) / 0.005
    kT = 1.380649e-23 * (p.get("temp", 27) + 273.15)
    tstep = p.get("tstep_ps", 1.0)
    # 입력쌍 2개의 게이트 환산 백색잡음 → 단일 소스로 합산 주입
    na = math.sqrt(2.0 * 4.0 * kT * (2.0 / 3.0) / gm / (tstep * 1e-12))

    s = est * 1e-6
    vins = [round(k * s, 12) for k in (-1.2, -0.6, 0.0, 0.6, 1.2)][:points]

    def one(args):
        vin, seed = args
        nl = gen_netlist(p, vdiff=vin)
        nl = nl.replace("Vos1 g1 inpx 0.0",
                        f"Vos1 g1 inpx DC 0 trnoise({na:.6g} {tstep}p 0 0)")
        nl = nl.replace("set noaskquit", f"set noaskquit\nsetseed {seed}")
        f = _parse(_run(nl), "fdiff")
        return None if f is None else (f < 0)   # 극성: vin>0 → outdiff<0

    jobs = [(v, seed0 + i) for i in range(n_per_point) for v in vins]
    outs = pmap(one, jobs)

    pts, fit = [], []
    for v in vins:
        ds = [o for (vv, _), o in zip(jobs, outs) if vv == v and o is not None]
        if not ds:
            continue
        n = len(ds)
        p1 = sum(ds) / n
        pts.append({"vin_uv": round(v * 1e6, 3), "p_plus": round(p1, 4), "n": n})
        pc = min(max(p1, 0.5 / n), 1 - 0.5 / n)   # 프로빗 정의역으로 클램프
        fit.append((v, _probit(pc)))
    # 최소자승 z = a + b·vin → σ = 1/b
    m = len(fit)
    sx = sum(v for v, _ in fit); sz = sum(z for _, z in fit)
    sxx = sum(v * v for v, _ in fit); sxz = sum(v * z for v, z in fit)
    denom = m * sxx - sx * sx
    if denom <= 0:
        return {"error": "프로빗 피팅 실패(점 부족)", "points": pts}
    b = (m * sxz - sx * sz) / denom
    if b <= 0:
        return {"error": "프로빗 기울기 비양수 — 노이즈가 스윕 범위를 지배", "points": pts}
    sigma_uv = 1e6 / b
    return {"sigma_uv_probit": round(sigma_uv, 1), "sigma_uv_analytic": est,
            "ratio": round(sigma_uv / est, 3), "points": pts,
            "n_sims": len(jobs), "inject_na_v": round(na, 9),
            "method": "probit fit of P(+|vin), input-referred trnoise (2 devices), gamma=2/3"}


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
    # Pelgrom A_VT: 호출자가 명시하지 않으면 모델별 기본 — gaa2nm 은 얇은
    # EOT·언도프드 채널로 매칭이 좋아 ~1.2mV·µm (45nm급 기본 2.0)
    if p.get("model") == "gaa2nm" and "avt_mv_um" not in params:
        p["avt_mv_um"] = 1.2
    # Channel length: DEFAULT_PARAMS carries the 45 nm-class seed (80/45 nm), which
    # is wrong for a 7 nm or 2 nm-class card. If the caller did not name an L for a
    # device, use that backend's nominal. Only fills in what was omitted — an
    # explicit l_nm is always honoured, so this cannot override a real request.
    ov = params.get("devices") or {}
    for dev, d in p["devices"].items():
        if "l_nm" not in (ov.get(dev) or {}):
            d["l_nm"] = l_nominal_nm(p, dev)
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
    points = pmap(_one, amps)          # the amplitudes are independent sims
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


def max_fclk_sweep(params, periods_ns=None, reset_residue_limit=0.01):
    """Maximum clock rate: sweep the clock period and find the shortest one where
    the comparator both (a) resolves within the evaluate phase and (b) precharges
    back to the rails within the reset phase — *balanced*, not merely high, since a
    differential residue is remembered by the next decision (`reset_residue_limit`
    is the allowed |outp−outn| as a fraction of VDD; see measure_hysteresis).
    Reports max f_clk and the energy per
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
        have_rst = vrp is not None and vrn is not None
        # Absolute level: did both outputs get back up near the rail?
        reset_abs = have_rst and vrp > 0.9 * vdd and vrn > 0.9 * vdd
        # DIFFERENTIAL residue: did they get back to the *same* place? This check was
        # missing, and it is the one that matters — measured at a 0.45 ns period the
        # outputs sit at 0.681 and 0.712 V, so the absolute test passes on both while
        # 31 mV of differential memory survives into the next decision and shows up
        # as 17 mV of input-referred hysteresis. Declaring that period usable
        # overstates max f_clk. Budget: 1% of VDD, well above the ~0.3 mV numerical
        # floor seen at relaxed periods.
        resid = (vrp - vrn) if have_rst else None
        reset_bal = have_rst and abs(resid) <= reset_residue_limit * vdd
        reset_ok = reset_abs and reset_bal
        pw = abs(iavg) * vdd * 1e6 if iavg is not None else None
        return {"period_ns": T, "fclk_ghz": round(1.0 / T, 3), "functional": bool(resolved),
                "reset_ok": bool(reset_ok), "ok": bool(resolved and reset_ok),
                "reset_absolute_ok": bool(reset_abs), "reset_balanced": bool(reset_bal),
                "reset_residue_mv": round(resid * 1e3, 4) if resid is not None else None,
                "power_uw": round(pw, 3) if pw is not None else None,
                "energy_fj": round(pw * T, 2) if pw is not None else None}

    pts = pmap(_one, periods_ns)       # each clock period is an independent sim
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
    p = _full(params)          # same merge as run_sim — not a third copy of it
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

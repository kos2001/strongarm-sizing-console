#!/usr/bin/env python3
"""
layout.py -- transistor-level layout synthesis for the StrongARM comparator.

Builds a simplified but real GDSII layout (SKY130 stream layers) from the device
sizing: each device is a multi-finger MOS (diffusion + poly fingers + met1
source/drain straps), PMOS sit in an nwell, the input pair is interdigitated
(common-centroid-ish), and the whole cell gets a substrate guard ring. Returns
per-layer polygons for the in-browser viewer, writes a .gds, and runs a light
rule DRC (met1/poly min width + spacing). Not sign-off DRC — a schematic-to-
layout PoC — but real GDS that opens in KLayout/Magic.
"""
import os

# SKY130 stream layers (layer, datatype, viewer color, z-order)
LAYERS = {
    "nwell": (64, 20, "#2f6d4f", 0),
    "diff":  (65, 20, "#4bbf73", 1),
    "poly":  (66, 20, "#e0574a", 2),
    "licon": (66, 44, "#cfd3da", 3),
    "li1":   (67, 20, "#4a90d9", 3),
    "met1":  (68, 20, "#f0a500", 4),
    "tap":   (65, 44, "#8a8f98", 1),
}

PPITCH = 0.46      # poly pitch (um)
POLY_W = 0.15      # poly finger width
MET_W = 0.17       # met1 strap width
GR = 0.35          # guard-ring width
GAP = 0.9          # gap between device blocks
SCALE_H = 0.35     # um of diffusion height per um of device width (keeps blocks compact)

# ---- 2nm급(gaa2nm) 나노시트 그리드 룰 — IRDS 수치 근사 (µm) ----
# 소자는 CPP 그리드 위의 finger(M) × 나노시트 스택 줄(rows = W/0.2µ)로만
# 존재한다: diffusion 이 연속 높이가 아니라 시트 줄 단위로 그려져
# W 양자화가 레이아웃에서 그대로 보인다. 실제 2nm BEOL/MOL 은 NDA 라
# 수치는 IRDS 로드맵급 근사이고 사인오프 룰이 아니다.
GAA = {
    "cpp": 0.048,       # contacted poly pitch
    "poly_w": 0.014,    # drawn gate length 14nm
    "met_w": 0.020,     # M1 strap width
    "sheet_p": 0.050,   # 스택 줄 수직 피치
    "sheet_w": 0.030,   # 스택(3-시트) 드로잉 폭
    "gr": 0.10, "gap": 0.15,
    "min_w_met": 0.018, "min_w_poly": 0.012, "min_s": 0.020,
    "unit": 0.2,        # W 그리드(µm) — 줄 수 = W/unit
}

# ---- ASAP7 7nm FinFET 핀 그리드 룰 (공개 PDK 수치) ----
# fin pitch 27nm, CPP 54nm, gate L 21nm, M1 pitch 36nm — 소자는 핀 줄
# (rows = W/0.07µ = NFIN) × finger 격자 위에만 존재한다.
FIN = {
    "cpp": 0.054,
    "poly_w": 0.021,
    "met_w": 0.018,
    "sheet_p": 0.027,   # 핀 피치
    "sheet_w": 0.007,   # 핀 드로잉 폭
    "gr": 0.10, "gap": 0.15,
    "min_w_met": 0.016, "min_w_poly": 0.018, "min_s": 0.018,
    "unit": 0.07,       # 핀 1개 등가 W
}


def _ruleset(params):
    m = params.get("model")
    return GAA if m == "gaa2nm" else FIN if m == "asap7" else None


def _device_block(x0, name, dev, kind, rules=None):
    """One multi-finger MOS block starting at x0; returns (layer->rects, width)."""
    nf = max(int(dev["m"]), 1)
    rects = {k: [] for k in LAYERS}
    if rules:
        # 그리드 소자: 세로 = 줄(나노시트 스택 rows = W/0.2µ | 핀 NFIN = W/0.07µ)
        rows = max(1, round(float(dev["w_um"]) / rules["unit"]))
        cpp, pw, mw = rules["cpp"], rules["poly_w"], rules["met_w"]
        sp, sw = rules["sheet_p"], rules["sheet_w"]
        hh = round((rows - 1) * sp + sw, 4)        # 스택 줄들이 차지하는 높이
        dw = round(nf * cpp + cpp, 4)
        if kind == "p":
            rects["nwell"].append([round(x0 - 0.05, 4), -0.05, round(dw + 0.10, 4), round(hh + 0.10, 4)])
        for r in range(rows):                      # 시트 스택/핀 줄 — 양자화가 보인다
            rects["diff"].append([x0, round(r * sp, 4), dw, sw])
        for i in range(nf):                        # 게이트 fingers (CPP 그리드)
            px = round(x0 + cpp * (i + 0.5) - pw / 2, 4)
            rects["poly"].append([px, -0.03, pw, round(hh + 0.06, 4)])
        for i in range(nf + 1):                    # S/D met1 straps
            rects["met1"].append([round(x0 + cpp * i, 4), 0.0, mw, hh])
        return rects, dw
    wf = max(dev["w_um"], 0.3)
    dh = round(max(wf * SCALE_H, 0.8), 3)          # diffusion height (compact)
    dw = round(nf * PPITCH + PPITCH, 3)            # diffusion width
    if kind == "p":
        rects["nwell"].append([x0 - 0.3, -0.3, dw + 0.6, dh + 0.6])
    rects["diff"].append([x0, 0, dw, dh])
    for i in range(nf):                            # poly fingers across the diffusion
        px = round(x0 + PPITCH * (i + 0.5) - POLY_W / 2, 3)
        rects["poly"].append([px, -0.25, POLY_W, dh + 0.5])
    for i in range(nf + 1):                        # source/drain met1 straps between fingers
        rects["met1"].append([round(x0 + PPITCH * i, 3), 0.05, MET_W, dh - 0.1])
    return rects, dw


def _build_layout(blocks, cell_name, gds_path, gds_default, rules=None):
    """Place an ordered list of (name, device, kind) as a row of multi-finger MOS
    blocks + PMOS nwell + substrate guard ring, write GDS, run rule DRC. Shared by
    the comparator and the ring-VCO layout generators."""
    gr, gap = (rules["gr"], rules["gap"]) if rules else (GR, GAP)
    layer_rects = {k: [] for k in LAYERS}
    x = gr + gap
    labels = []
    for name, dev, kind in blocks:
        rb, w = _device_block(x, name, dev, kind, rules=rules)
        for lyr, rs in rb.items():
            layer_rects[lyr].extend(rs)
        labels.append({"name": name, "x": round(x, 3), "w": w, "kind": kind})
        x += w + gap

    cell_w = round(x - gap + gr, 3)
    top = max((r[1] + r[3] for rs in layer_rects.values() for r in rs), default=2.0)
    bot = min((r[1] for rs in layer_rects.values() for r in rs), default=0.0)
    ring_h = round(top - bot + 2 * gr, 3)
    y0 = round(bot - gr, 3)
    for x1, y1, w1, h1 in [
        [0, y0, cell_w, gr], [0, y0 + ring_h - gr, cell_w, gr],
        [0, y0, gr, ring_h], [cell_w - gr, y0, gr, ring_h],
    ]:
        layer_rects["tap"].append([round(x1, 3), round(y1, 3), round(w1, 3), round(h1, 3)])
        layer_rects["met1"].append([round(x1, 3), round(y1, 3), round(w1, 3), round(h1, 3)])

    area = round(cell_w * ring_h, 3)
    gds = gds_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", gds_default)
    try:
        import gdstk
        os.makedirs(os.path.dirname(gds), exist_ok=True)
        lib = gdstk.Library()
        cell = lib.new_cell(cell_name)
        for lyr, (ln, dt, _c, _z) in LAYERS.items():
            for (rx, ry, rw, rh) in layer_rects[lyr]:
                cell.add(gdstk.rectangle((rx, ry), (rx + rw, ry + rh), layer=ln, datatype=dt))
        lib.write_gds(gds)
        gds_written = gds
    except Exception as e:
        gds_written = f"error: {e}"

    return {
        "layers": [{"name": k, "gds": f"{LAYERS[k][0]}/{LAYERS[k][1]}", "color": LAYERS[k][2],
                    "z": LAYERS[k][3], "rects": layer_rects[k]} for k in LAYERS],
        "labels": labels,
        "bbox": {"w": cell_w, "h": ring_h, "y0": y0},
        "area_um2": area,
        "gds_path": gds_written,
        "drc": _drc(layer_rects, rules=rules),
        "ruleset": ("gaa2nm(IRDS-approx)" if rules is GAA else "asap7-fin(approx)" if rules is FIN else "sky130-class"),
    }


def generate_layout(params, gds_path=None):
    devices = params.get("devices", {})
    order = ["tail", "input", "ncc", "pcc", "pre", "prei"]
    kind = {"tail": "n", "input": "n", "ncc": "n", "pcc": "p", "pre": "p", "prei": "p"}
    blocks = [(k, devices[k], kind[k]) for k in order if k in devices]
    return _build_layout(blocks, "STRONGARM_COMPARATOR", gds_path, "strongarm.gds", rules=_ruleset(params))


def generate_vco_layout(params, gds_path=None):
    """Ring VCO layout — 2N+4P 유닛만: N단(각 Mp/Mn·Mpb/Mnb 인버터 2쌍 +
    래치 Mx/Mxb) 멀티핑거 MOS 행 + 가드링 + DRC. 그 외 소자 없음."""
    d = params.get("devices", {})
    n = int(params.get("n_stages", 5))
    blocks = []
    for i in range(1, n + 1):
        blocks += [(f"Mp{i}", d["invp"], "p"), (f"Mn{i}", d["invn"], "n"),
                   (f"Mpb{i}", d["invp"], "p"), (f"Mnb{i}", d["invn"], "n"),
                   (f"Mx{i}", d["xcplp"], "p"), (f"Mxb{i}", d["xcplp"], "p")]
    return _build_layout(blocks, "RING_VCO", gds_path, "ring_vco.gds", rules=_ruleset(params))


def extract_vco_parasitics(params):
    """Layout-derived added capacitance per ring output node (fF): each o_i sees
    the drains of its stage's Mp/Mn plus the next stage's gates. Real drawn
    diffusion+met1 geometry × SKY130-class cap densities — PoC extraction."""
    d = params.get("devices", {})
    rules = _ruleset(params)
    cap_p = _device_cap_ff(d["invp"], "p", rules)
    cap_n = _device_cap_ff(d["invn"], "n", rules)
    cap_x = _device_cap_ff(d["xcplp"], "p", rules)
    c_node = 0.5 * (cap_p + cap_n + cap_x)   # drain share at o_i (inverter + latch)
    return {"c_node_ff": round(c_node, 3),
            "per_device_ff": {"invp": round(cap_p, 3), "invn": round(cap_n, 3)},
            "method": ("drawn grid geometry × advanced-node cap densities (approx)" if rules
                       else "drawn diffusion+met1 area/perimeter × SKY130-class cap densities")}


# areal / fringe cap densities (SKY130-class, order-of-magnitude) used to turn
# drawn geometry into node capacitance — a real layout-derived estimate, not
# sign-off extraction
CAP = {"diff_area": 0.90, "diff_perim": 0.20, "met_area": 0.03, "met_perim": 0.04}  # fF per µm² / µm
# 2nm급: GAA 는 접합이 기판에서 격리돼 면적 성분이 작고, 촘촘한 MOL/M1 의
# 프린지가 지배한다 — 면적이 ~100× 작아지므로 절대값은 크게 줄어든다(근사)
CAP_GAA = {"diff_area": 1.5, "diff_perim": 0.05, "met_area": 0.15, "met_perim": 0.05}


def _device_cap_ff(dev, kind, rules=None):
    """Junction + met1 capacitance (fF) of one device block, from its drawn
    diffusion and met1 geometry (same block builder as the layout)."""
    rb, _dw = _device_block(0.0, "x", dev, kind, rules=rules)
    cd = CAP_GAA if rules else CAP
    c = 0.0
    for (rx, ry, rw, rh) in rb["diff"]:
        c += cd["diff_area"] * rw * rh + cd["diff_perim"] * 2 * (rw + rh)
    for (rx, ry, rw, rh) in rb["met1"]:
        c += cd["met_area"] * rw * rh + cd["met_perim"] * 2 * (rw + rh)
    return c


def extract_parasitics(params):
    """Layout-derived node capacitance (fF) from the actual drawn geometry.
    outp/outn see the latch (pcc/ncc) + precharge drains; nX/nY see the input
    pair + latch-NMOS sources. Each symmetric node gets half the paired-device
    geometry. Real geometry × areal/fringe cap — a PoC extraction, not sign-off."""
    dv = {**{k: v for k, v in params.get("devices", {}).items()}}
    rules = _ruleset(params)
    kind = {"tail": "n", "input": "n", "ncc": "n", "pcc": "p", "pre": "p", "prei": "p"}
    cap = {k: _device_cap_ff(dv[k], kind[k], rules) for k in dv if k in kind}
    c_out = 0.5 * (cap.get("pcc", 0) + cap.get("ncc", 0) + cap.get("pre", 0))
    c_int = 0.5 * (cap.get("input", 0) + cap.get("ncc", 0) + cap.get("prei", 0))
    return {"c_out_ff": round(c_out, 3), "c_int_ff": round(c_int, 3),
            "per_device_ff": {k: round(v, 3) for k, v in cap.items()},
            "method": ("drawn grid geometry × advanced-node cap densities (approx)" if rules
                       else "drawn diffusion+met1 area/perimeter × SKY130-class cap densities")}


def _drc(layer_rects, rules=None):
    """Light rule DRC: met1/poly minimum width + met1 spacing (µm).
    그리드 모델(gaa2nm/asap7)은 해당 노드급 근사 룰로 검사한다."""
    if rules:
        min_w, poly_min, min_s = rules["min_w_met"], rules["min_w_poly"], rules["min_s"]
    else:
        min_w, poly_min, min_s = 0.14, 0.15, 0.14
    viol = []
    for lyr, mw in (("met1", min_w), ("poly", poly_min)):
        for r in layer_rects[lyr]:
            if min(r[2], r[3]) < mw - 1e-6:
                viol.append(f"{lyr} width {min(r[2], r[3])} < {mw}")
    # met1 spacing (axis-aligned gap between non-overlapping rects)
    m = layer_rects["met1"]
    for i in range(len(m)):
        for j in range(i + 1, len(m)):
            a, b = m[i], m[j]
            dx = max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]))
            dy = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]))
            if dx < min_s and dy < min_s and (0 < dx < min_s or 0 < dy < min_s):
                viol.append(f"met1 spacing < {min_s}")
                break
        else:
            continue
        break
    return {"clean": not viol, "violations": viol[:8], "n_violations": len(viol),
            "rules": f"met1/poly min width, met1 min spacing = {min_s}µm"}


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import run_sim
    r = generate_layout(run_sim.DEFAULT_PARAMS)
    print(json.dumps({"area_um2": r["area_um2"], "gds_path": r["gds_path"],
                      "drc": r["drc"], "layer_counts": {l["name"]: len(l["rects"]) for l in r["layers"]}}, indent=2))

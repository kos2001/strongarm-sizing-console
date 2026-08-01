---
name: strongarm-console
description: "Use when driving the StrongARM Sizing Console (comparator + ring-VCO analog sizing over ngspice) through its MCP tools — simulating, auto-sizing, running PVT/yield sign-off, editing netlists, or proposing device sizes. Covers the 46-tool surface, the four model backends (ptm/sky130/asap7/gaa2nm), W-grid quantization rules, and the tool-call discipline that keeps agent turns fast."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [semiconductor, eda, analog, strongarm, comparator, vco, ngspice, mcp, sizing]
    related_skills: [analog-ic-robustness-optimization, strongarm-fast-loop]
---

# StrongARM Console — agent driving guide

## Overview

The `strongarm` MCP server (repo `mcp_server.py`) exposes the whole console as
46 stdio tools. Everything runs real ngspice; nothing is mocked. Tools proxy to
the HTTP backend at `$STRONGARM_API` (default `http://127.0.0.1:8770`), so the
console server must be running.

## Tool map (by task)

| Task | Tools |
|---|---|
| One sizing → metrics | `strongarm_run_sim` (comparator), `vco_simulate` |
| Auto-size to spec | `strongarm_optimize`, `vco_optimize` |
| Trade-off front | `strongarm_pareto`, `vco_pareto` |
| Sign-off | `strongarm_pvt` / `vco_pvt` (45 corners: SS/SF/TT/FS/FF × temp × VDD), `strongarm_yield`, WiCkeD tools (`*_wicked_*`) |
| Deep analysis | `strongarm_metastability`, `strongarm_noise_ber`, `vco_phase_noise`, `vco_tuning`, `vco_pushing` |
| Layout | `strongarm_layout`, `vco_layout` (GDS + DRC; gaa2nm draws the nanosheet grid) |
| Netlist as text | `strongarm_netlist` / `vco_netlist` (export deck), `spice_run_netlist` (run an edited deck — `shell` is rejected) |
| Generic SPICE (AC / DC OP / value sweep) | `spicelib` MCP server (separate, if registered): `run_ac_analysis`, `run_dc_op`, `run_transient`, `run_sweep` — use for device characterization the console tools don't cover |

## Model backends — read this before proposing sizes

`params.model` selects the device model. **W rules differ per backend:**

| model | node | VDD | W rule |
|---|---|---|---|
| `ptm` (default) | 45 nm BSIM4 | 1.0 V (comparator 0.7) | continuous µm |
| `sky130` | real SkyWater PDK | 1.8 V | continuous µm (L ≥ 150 nm) |
| `asap7` | real BSIM-CMG 107 FinFET (OSDI) | 0.7 V, L 21 nm | **integer fins**: propose `w_um` as multiples of 0.07 (netlist folds `w·m` into NFIN) |
| `gaa2nm` | 2 nm-class scaled BSIM4 (trend only) | 0.65 V, L 14 nm (input 20) | **integer nanosheet stacks**: `w_um` multiples of 0.2 |

On `asap7`/`gaa2nm` the optimizer runs integer coordinate descent and returns
`final_stacks` (per-device fin/stack counts) — report sizes in those units.
Never present `gaa2nm` numbers as sign-off quality; it is a trend-study card.

### `vt` — Vth is searched too, not just W

Every device takes `"vt": "lvt" | "svt" | "hvt"` (default `svt`). `strongarm_optimize`
searches it after the widths converge and reports `final_vt` + `vt_note`; pass
`optimize_vt: false` to skip it.

Report the chosen level per device alongside W — it is part of the sizing, and on
a real PDK it is a mask choice the user has to act on. Two things to carry over
verbatim when they appear:

- `final_vt.fallbacks` — **sky130 has no `nfet_01v8_hvt`.** An NMOS asked for hvt
  silently becomes svt unless you say so.
- `final_vt.l_clamps` — **sky130's `pfet_01v8_lvt` starts at L = 0.345 µm.** Choosing
  it forces L up ~2.3x, which is why LVT PMOS measures *slower* there (189.9 ps vs
  160.6 ps svt). Do not tell a user "LVT is faster" on sky130 PMOS.

Vth genuinely moves the metrics (asap7 at L=21nm: 18.1→24.9 ps and 10.9→7.82 µW
across the flavors), and mixed assignments are not dominated by uniform ones — so
let the search decide rather than prescribing a flavor. Offset caveat: per-flavor
`A_VT` is not modelled, so flavor affects offset only through the simulated Vth.

### `l_nm` — L is searched too, and its bounds are per backend

`strongarm_optimize` also searches channel length (`optimize_l`, default on) and
reports `final_l_nm` + `l_note` + `l_range_nm`. Two things to know:

- **W and L are not interchangeable.** At equal gate area — so equal Pelgrom
  offset — input 8.0µ×80n resolves in 530 ps but 4.0µ×160n takes 800 ps. And L is
  non-monotonic in speed: on ptm45 the input pair is *faster* at 160 nm (452 ps)
  than at 80 nm (530 ps) **and** matches better (1.39 vs 1.85 mV σ). Do not size L
  by rule; the optimum is interior.
- **Each backend's L is different and the backend now enforces it.** ptm45
  45–200 nm (below 45 the card has no model and the deck errors), sky130
  150–500 nm (per-device bin floor), asap7 21–200 nm, gaa2nm 10–120 nm. If you
  omit `l_nm`, you get that node's nominal — you no longer have to send it.

## Tool-call discipline

**Which** tool to reach for, and what each one costs in SPICE seconds, is in
`strongarm-fast-loop` — read that before the first call of a sizing turn. The
rules here are about the shape of a turn; that skill is about its cost.

These flows were tuned so one agent turn ≈ one minute:

1. **Pass the design state through.** The UI panels send the current params
   JSON in the message; put it (plus your deltas) directly into the tool's
   `params` argument in ONE call. Do not re-derive or re-simulate baselines.
2. **At most 2 tool calls per request** (3 when editing netlist text:
   `*_netlist` → edit → `spice_run_netlist`). No terminal/file tools, no
   explore-verify loops.
3. **Structural circuit edits** go through the text path: export deck, edit,
   run, and include the full modified deck in a ```spice block so the UI can
   offer it for download/import.
4. **Size proposals** end with a ```json block —
   `{"devices": {…changed only…}, "vdd": …}` (comparator) or
   `{"devices": …, "n_stages": odd ≥3, "vctrl": …}` (VCO) — so the UI's
   ↧ apply button works.

## Physics cheatsheet (for sane proposals)

- Comparator decision time ∝ C_L·V / (gm_input · regeneration); widen `input`
  for speed/offset, trim `tail`/`pcc` for power. Offset σ ≈ √2·A_VT/√(W·L·M)
  of the input pair (A_VT: 2.0 ptm, 1.4 asap7, 1.2 gaa2nm mV·µm).
- VCO: f = 1/(2N·t_d); V_ctrl sets starve current. Keep the cross-coupled
  `xcplp` weak (~1/4 of `invp` drive) — oversized it latches the ring
  (`oscillates: false`). `n_stages` must be odd, ≥ 3.
- Low-VDD StrongARM dies at slow-NMOS corners (SS/SF): strengthen `tail`/`ncc`
  (~1.5×) first, or raise vdd — verify with the 45-corner PVT tool.

## External references (공개 스킬 생태계)

같은 도메인의 공개 스킬 — **라이선스 미표기라 코드 반입은 금지**, 아이디어
참조와 이론 문서 열람용으로만 링크한다:

- `github.com/Arcadia-1/analog-circuit-skills` — StrongARM comparator 스킬
  (ngspice+PTM45): 프로빗/CDF 피팅 기반 입력환산 노이즈 추출, τ 스윕,
  램프 전달곡선, Miyahara 비교. `references/01~04`(theory/speed/noise/offset)
  는 이론 질문에 좋은 답 소스.
- `github.com/Arcadia-1/analog-agents` — 아날로그 멀티에이전트 패턴
  (design/verify/review/audit/evolve 역할 분리) — 우리 오케스트레이터의
  역할 분리와 같은 계열, 확장 아이디어 참조.

MIT/Apache 로 라이선스된 인접 스킬(kicad-happy 의 KiCad 서브서킷 SPICE 검증,
anthropics/skills 의 webapp-testing·mcp-builder)은 도메인이 달라 미설치.

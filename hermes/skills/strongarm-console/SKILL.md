---
name: strongarm-console
description: "Use when driving the StrongARM Sizing Console (comparator + ring-VCO analog sizing over ngspice) through its MCP tools — simulating, auto-sizing, running PVT/yield sign-off, editing netlists, or proposing device sizes. Covers the 46-tool surface, the four model backends (ptm/sky130/asap7/gaa2nm), W-grid quantization rules, and the tool-call discipline that keeps agent turns fast."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [semiconductor, eda, analog, strongarm, comparator, vco, ngspice, mcp, sizing]
    related_skills: [analog-ic-robustness-optimization]
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

## Tool-call discipline

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
   `{"devices": {…changed only…}, "vdd": …, "topology": …}` (comparator) or
   `{"devices": …, "n_stages": odd ≥3, "vctrl": …}` (VCO) — so the UI's
   ↧ apply button works.

## Physics cheatsheet (for sane proposals)

- Comparator decision time ∝ C_L·V / (gm_input · regeneration); widen `input`
  for speed/offset, trim `tail`/`pcc` for power. Offset σ ≈ √2·A_VT/√(W·L·M)
  of the input pair (A_VT: 2.0 ptm, 1.4 asap7, 1.2 gaa2nm mV·µm).
- VCO: f = 1/(2N·t_d); V_ctrl sets starve current. Keep the cross-coupled
  `xcplp` weak (~1/4 of `invp` drive) — oversized it latches the ring
  (`oscillates: false`). `n_stages` must be odd, ≥ 3.
- Low-VDD single-tail StrongARM dies at slow-NMOS corners (SS/SF); the
  `doubletail` topology survives — suggest it when corner sign-off fails.

---
name: strongarm-design-recipes
description: "Use when sizing or debugging the StrongARM comparator / ring VCO through the strongarm MCP tools and a design decision is needed — first-cut sizing from spec, corner-failure playbook, model-backend presets, optimizer expectations. These are MEASURED recipes from this console (real ngspice numbers), not textbook estimates."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [semiconductor, strongarm, comparator, vco, sizing, recipes, ngspice]
    related_skills: [strongarm-console, analog-ic-robustness-optimization]
---

# StrongARM design recipes (measured)

All numbers below were measured on this console's real ngspice backend. Use
them to propose near-final sizes in ONE shot, then confirm with ONE tool call
(`strongarm_design_brief` first; `strongarm_run_sim`/`vco_simulate` to verify).

## Comparator first-cut by model backend

Known-good presets (meet 400 ps / 100 µW at nominal):

| model | vdd | L (input/other) | input | tail | ncc | pcc | pre | prei | measured |
|---|---|---|---|---|---|---|---|---|---|
| ptm | 0.7 | 80/45 nm | 8µ×4 | 12µ×6 | 4µ×2 | 9µ×4 | 4µ×2 | 4µ×2 | 530 ps / 106 µW |
| gaa2nm | 0.65 | 20/14 nm | same W (0.2µ grid) | | | | | | 358 ps / 65 µW |
| asap7 | 0.7 | 21 nm | 0.28µ×4 (16 fin) | 0.42µ×6 (36) | 0.28µ×2 (8) | 0.35µ×4 (20) | 0.28µ×2 (8) | 0.28µ×2 (8) | 94.8 ps / 2.3 µW |

Spec math (before any tool call):
- Offset: σ = √2·A_VT/√(W·L·M of input). Required input area ≥ 2·(A_VT/σ_target)².
  A_VT: ptm 2.0, asap7 1.4, gaa2nm 1.2 mV·µm.
- Decision-time levers in order: input W (gm), tail W, then **shrink prei
  (S1/S2)** — internal P/Q parasitic reduction bought 530→514 ps for free.
- Power levers: tail, pcc down; the integer coordinate-descent optimizer on
  gaa2nm reached 13.6 µW from a 65 µW seed — trust `strongarm_optimize` for
  the last stretch instead of hand-iterating.

## Noise: analytic vs probit-measured

`strongarm_noise_probit` MEASURES input-referred σ by noise counting (probit
fit of P(+|vin) under injected device thermal noise, ~5 s). Measured σ runs
**1.5–2× above** the analytic √(2γkT/(gm·t_int)) estimate on the default
design (aperture/γ assumptions) — quote the measured one for BER claims, and
note its ±tens-of-% spread at n=24/point (raise n_per_point for precision).
Method credit: probit noise-counting is the standard comparator technique
(cf. Arcadia-1/analog-circuit-skills references) — implementation is ours.

## Corner-failure playbook

- **Low-VDD (≤0.7 V) + slow NMOS (SS/SF) is the binding corner** — and
  **widths cannot save it** (measured: NMOS stack ×8 still dead; subthreshold
  current is linear in W but exponential in overdrive). The real levers are
  the operating point (`vcm_frac` up — 0.82 makes the corner survive with
  default W) or a vdd floor. `strongarm_optimize` handles this automatically
  (corner_aware default): FEO-style vcm feasibility lift → corner-co-evaluated
  W search → measured 45/45 corners pass vs 9 fails corner-blind, at +1.4%
  nominal power.
- Corner skew is model-aware (±50 mV; ±25 mV on gaa2nm/asap7) — cross corners
  SF/FS often bind before SS/FF on this latch (NMOS-dominated).
- After any topology/model change, re-run PVT (45 corners) before declaring pass.

## VCO recipes

- xcpl ring, N odd ≥3. Keep `xcplp` ≈ ¼ of `invp` drive — oversized couplers
  latch the ring (`oscillates: false`).
- Frequency levers: starve widths (current) > n_stages > cload. Measured
  ranges: ptm 1.0 V ≈ 2.3 GHz; gaa2nm 0.65 V: no oscillation below
  V_ctrl ≈ 0.42, then 0.74→0.95 GHz; asap7 0.7 V: 0.84→5.41 GHz across
  V_ctrl (kVCO ≈ 13 GHz/V) — very wide, say so when proposing.
- Auto-size hits 1.0 GHz within ±0.2 % on gaa2nm in ~55 sims (integer CD).

## VCO noise: analytic vs measured jitter

`vco_phase_noise` now includes the **measured** cross-check on the default
xcpl topology too (per-stage/rail trnoise injection, multi-seed): measured
period jitter runs ~2× the analytic √(2N)·√(kTC)/I estimate (default design:
121 fs vs 63 fs, L(1MHz) −97 vs −102.5 dBc/Hz) and the accumulation slope
≈0.5 confirms the thermal 1/f² region. Quote measured numbers for jitter
claims; the analytic value is a fast lower-bound sanity check.

## W-grid discipline (quantized backends)

- gaa2nm: W = k × 0.2 µm (nanosheet stacks). asap7: W = k × 0.07 µm (fins;
  netlist folds w·m into NFIN). Propose only grid values; report sizes in
  stacks/fins — the optimizer's `final_stacks` is the ground truth.

## Tool-call pattern that keeps turns ≈1 min

1. `strongarm_design_brief` / `vco_design_brief` (ONE call: metrics + margins
   + hints). 2. Draft sizes from the recipes above, then **verify the draft
   with ONE `strongarm_run_sim`/`vco_simulate` call — never present an
   unverified sizing** (intuition sizing measurably backfires: a plausible
   "halve input m, boost ncc" draft measured 530→1063 ps on this console).
   3. If two or more specs fail at once, don't hand-tune: call
   `strongarm_optimize`/`vco_optimize` and present its result. Never explore
   with terminal/file tools.

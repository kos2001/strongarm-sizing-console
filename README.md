# StrongARM Sizing Console — analog IC sizing & sign-off over ngspice

An agent-driven analog design tool that closes the loop **simulate → evaluate →
optimize → sign-off** against real ngspice, with a React web console. Two circuit
domains share the same backend and algorithms:

- **Comparator** (StrongARM latch, 13 pages) —
  sizing, transient, metastability (τ), max f_clk + energy, auto-find (DE +
  GP-surrogate, or **integer coordinate descent** on quantized-W backends),
  sensitivity, NSGA-II Pareto, Monte-Carlo offset, noise/BER, PVT (45 corners:
  SS/SF/TT/FS/FF × temp × VDD), parametric yield, GDSII layout + DRC, full flow,
  netlist export/import roundtrip, natural-language sizing agent.
- **VCO** (cross-coupled pseudo-differential ring with reset, odd-N, 10 pages) —
  oscillation + waveform, tuning (Kvco), auto-size, NSGA-II Pareto (power↔freq),
  phase noise / jitter / FoM (analytic + SPICE trnoise cross-check), PVT, supply
  pushing, WiCkeD yield/robustness, GDSII layout + DRC, full flow, NL agent.

**Four model backends** share every page and algorithm:

| Backend | What it is | W sizing |
|---|---|---|
| PTM 45 nm | BSIM4 predictive bulk (default) | continuous µm |
| SKY130 | **real SkyWater production PDK** (.lib corners) | continuous µm |
| ASAP7 7 nm | **real BSIM-CMG 107 FinFET via ngspice OSDI** (ASU predictive PDK) | integer fins (1 fin ≈ Weff 0.07 µm) |
| GAA 2nm≈ | BSIM4 scaled to IRDS 2 nm-class targets — trend study only | integer nanosheet stacks (1 stack ≈ 0.2 µm) |

On the quantized backends (`asap7`, `gaa2nm`) W exists only on the fin/stack
grid: the editor snaps, the netlist quantizes, the layout draws the grid, and
the auto-sizer switches from continuous DE to **integer coordinate descent on
stack/fin counts** (what it searches *is* the integer, and the trajectory
reports it that way).

Stack: ngspice-46 (BSIM4 + **OSDI/BSIM-CMG**, compiled with OpenVAF) ·
dependency-free stdlib HTTP bridge · React 19 + Vite + TypeScript
(Virtuoso-styled schematic / layout / waveform, KO/EN i18n) · MCP stdio server
(46 tools) · hermes-agent profile + skills (`hermes/`) · pytest suite. The
sections below document the original comparator backend ("method 1"); see the
VCO section for the ring-oscillator flow and `webapp/README.md` for the web
console.

📊 **Overview presentation:** `docs/presentation.html` (English) /
`docs/presentation.ko.html` (한국어) — a self-contained scroll-deck (open in any
browser, EN⇄한 toggle) walking through the architecture, both domains, the
optimizers, phase-noise, performance, and rigor.

## Files

| File | Purpose |
|------|---------|
| `run_sim.py` | Core `run_sim(params) → measurements` wrapper. Generates a parameterized StrongARM netlist, runs ngspice in batch, returns JSON metrics. CLI + importable. |
| `vco_sim.py` | MOSFET **current-starved ring VCO** backend, sharing the same ngspice plumbing: `measure_vco` (osc. frequency / power / does-it-oscillate), `vco_tuning` (f vs V_ctrl → range, Kvco). Same simulate→evaluate→optimize loop as the comparator. |
| `mcp_server.py` | Dependency-free MCP stdio server — **46 tools** covering both domains: simulate, optimize (single + Pareto), metastability, PVT, yield/WiCkeD, layout, netlist text, raw-deck `spice_run_netlist`, … for hermes/Claude agents. |
| `wicked.py` / `vco_wicked.py` | WiCkeD-inspired robustness flows (WCO/WCD/mismatch/high-sigma/yield sweep) for comparator / VCO. |
| `layout.py` | GDSII layout synthesis + rule DRC + parasitic extraction — sky130-class rules, or the **nanosheet grid ruleset** on `gaa2nm` (CPP 48 nm, stack-row diffusion). |
| `models/ptm_45nm_bulk.txt` | BSIM4 (level=54) PTM 45 nm bulk (`nmos`/`pmos`). |
| `models/gaa2nm_approx.txt` | BSIM4 card scaled to 2 nm-class targets (EOT 0.85 nm, \|Vth0\| 0.20 V, VDD 0.65 V, SCE suppressed as a GAA-electrostatics proxy). **Trend study only — never sign-off.** |
| `models/asap7/` | ASAP7 7 nm FinFET: ngspice-adapted TT/SS/FF cards + compiled `bsimcmg107.osdi` (arm64). Rebuild: `scripts/build_bsimcmg_osdi.sh`. |
| `third_party/bsimcmg107/` | CMC BSIM-CMG 107.0.0 Verilog-A with two local patches (instance-param attributes; EOTACC bound 1-ulp fix) — see `scripts/build_bsimcmg_osdi.sh` header. |
| `third_party/asap7_models/` | Original ASU ASAP7 HSPICE cards (BSD-3), converted by `scripts/adapt_asap7.py`. |
| `hermes/` | **Hermes-agent assets**: profile/MCP registration guide + agent skills (`strongarm-console`, `analog-ic-robustness-optimization`). |
| `webapp/` | React console + stdlib HTTP bridge (`server.py`) — optimizers, PVT, agent proxy (`/api/agent/chat`), netlist parse. |
| `README.md` | This file. |

## Measured metrics

```
nominal: { decision_time_ps, power_uw, final_diff_v, functional }
offset:  { offset_sigma_mv, offset_mean_mv, pelgrom_sigma_vth_mv, n_mc }
```

- **decision_time_ps** — clk edge → outputs split to 0.7·VDD (regeneration speed).
- **power_uw** — average supply power over the evaluation window.
- **offset_sigma_mv** — input-referred offset σ via Monte-Carlo input-pair Vth
  mismatch (Pelgrom: σ_Vth = A_VT / √(W·L·M)); bisection finds the metastable
  input for each sample. Input-pair mismatch is the dominant term; latch/tail
  mismatch is a documented extension point. NOTE: small `n_mc` gives a noisy σ
  estimate — use `n_mc >= 24` for a reliable number, and treat the deterministic
  `pelgrom_sigma_vth_mv` (offset_σ ≈ √2 · pelgrom) as the sizing anchor.
- **functional** — did the latch resolve to a rail.

## Usage

```bash
# defaults (P1_SAR_ADC seed sizing)
python3 run_sim.py --demo

# from a params file (override any subset of devices)
python3 run_sim.py cand.json

# from stdin; skip the slow offset MC during a fast search
echo '{"devices":{"input":{"w_um":6,"l_nm":80,"m":4}}}' | python3 run_sim.py - --no-offset
```

Params schema (units are in the key names):

```json
{
  "n_mc": 16,
  "vdd": 0.9,
  "cload_ff": 15.0,
  "avt_mv_um": 2.0,
  "devices": {
    "input": {"w_um": 8.0, "l_nm": 80.0, "m": 4, "vt": "svt"},
    "tail":  {"w_um": 12.0,"l_nm": 40.0, "m": 6},
    "ncc":   {"w_um": 4.0, "l_nm": 40.0, "m": 2},
    "pcc":   {"w_um": 9.0, "l_nm": 40.0, "m": 4},
    "pre":   {"w_um": 4.0, "l_nm": 30.0, "m": 2}
  }
}
```

`input` = differential pair · `tail` = tail switch · `ncc`/`pcc` = cross-coupled
NMOS/PMOS latch · `pre` = precharge PMOS.

### `vt` — threshold voltage as a searched variable

Each device also takes `"vt": "lvt" | "svt" | "hvt"` (lower Vth / standard /
higher Vth; **`svt` is the default and reproduces the pre-`vt` netlist exactly**).
Vth is a real per-device knob on a comparator, not only a corner perturbation,
and `strongarm_optimize` searches it after the widths converge — pass
`optimize_vt: false` to skip that pass.

The level maps onto whatever the backend really has:

| backend | how `vt` is realized |
|---|---|
| `asap7` | real ASAP7 flavors already in the cards: `slvt` / `lvt` / `rvt` |
| `sky130` | real PDK devices: `nfet_01v8_lvt` · `pfet_01v8_lvt` · `pfet_01v8_hvt`. **No `nfet_01v8_hvt` exists** — an NMOS asked for hvt falls back to svt, reported in `final_vt.fallbacks`. And `pfet_01v8_lvt` is only characterized from **L = 0.345 µm**, so choosing it forces L up; reported in `final_vt.l_clamps` |
| `ptm45`, `gaa2nm` | single generic BSIM4 card with no flavors, so the level becomes a `delvto` implant **proxy** that composes with the corner skew. It shifts Vth only — it does not carry the mobility/leakage differences of a real implant |

Measured effect (why it is worth searching rather than prescribing):

- **asap7** (at the node's L = 21 nm) — all devices one level up: 18.1→24.9 ps for
  10.9→7.82 µW. `tail` alone to `lvt`: 18.1→**16.8 ps for 4% more power**.
- **sky130** — NMOS `lvt` is 16% faster (160.6→135.3 ps), but PMOS `lvt` is
  *slower* (189.9 ps) because the PDK forces its L from 45 nm to 350 nm. The
  naive "LVT everywhere" is worse than the baseline.
- In `optimize` (minimize power subject to speed/offset/corner): ptm45
  26.7→24.2 µW, asap7 0.025→0.018 µW, sky130 **1.145→0.043 µW** (PMOS hvt on
  the precharge), for +25 SPICE evals.

**Limitation:** per-flavor `A_VT` is not modelled — `avt_mv_um` is one number for
the whole design, so a flavor change affects offset only through the simulated
Vth and through W·L·M, never through a different mismatch coefficient. Speed and
power effects are simulated; the offset effect is partial. An offset-critical
flavor decision needs the foundry's per-flavor Pelgrom data.

### `l_nm` — L is **fixed**, and validated

Channel length is a methodology choice here, not a per-device free variable:
drawing the latch's groups at different L breaks the symmetry the comparator's
matching depends on, complicates the layout, and the PDK's Vt binning and corner
characterization are cleanest at a chosen L. **The sizing knobs are W and M.**

`optimize` therefore leaves every L exactly where you fixed it
(`optimize_l=False`, the default). **Omit `l_nm` and you get that node's nominal
L** — the backend now knows it:

| backend | usable L | nominal (input / other) |
|---|---|---|
| `ptm45` | 45–200 nm | 80 / 45 nm |
| `sky130` | 150–500 nm | 150 / 150 nm (per-device bin floor) |
| `asap7` | 21–200 nm | 21 / 21 nm |
| `gaa2nm` | 10–120 nm | 20 / 14 nm |

Because L is fixed, a *wrongly* fixed L is the one thing that can go quiet, so
`l_report` validates it against the measured range — below 45 nm the PTM card has
no model and **the deck errors out**, which otherwise reads as "non-functional"
rather than "bad input". Judgement is made on the L actually built: a sky130
request under the bin floor is raised and reported (`raised_by_pdk`), not failed.

If you want to know what a *different fixed* L would buy — a seed-selection
question — `optimize_l: true` runs an exploratory pass. Measured on ptm45, the
input pair at 160 nm is both faster than the seed's 80 nm (452 vs 530 ps) **and**
better matched (1.39 vs 1.85 mV σ), so 80 nm is worth revisiting as a fixed
choice. Note also that W and L are not interchangeable: at identical gate area —
identical Pelgrom offset — 8.0 µm × 80 nm resolves in 530 ps while 4.0 µm × 160 nm
takes 800 ps.

Two bugs this surfaced, both fixed:

1. **The API and the UI disagreed on L.** Per-model L lived only in the web UI's
   model buttons, so an API/MCP caller asking for `{"model": "asap7"}` got the
   45 nm-class seed (80/45 nm) on a 7 nm card — 4x the node's gate length. The
   backend is now the single source of truth (`run_sim.L_RANGE_NM`).
2. **Offset was computed for a device that was never built.** On sky130 the
   netlist raises L to the PDK bin floor, but every area calculation read `l_nm`
   directly — so asking for 45 nm simulated a 150 nm device while reporting the
   offset of a 45 nm one, **1.83x worse than the real geometry**, and the
   optimizer paid an offset penalty against that phantom. All area math now goes
   through `run_sim.effective_l_nm` / `gate_area_um2`.

## Gaps against real sign-off criteria

Two things a comparator design review asks for that the tool could not report. Both
are opt-in — with the new inputs unset, every generated deck is byte-identical to
before, verified against the previous revision on all four backends.

### Kickback — was unmeasurable, not merely unmeasured

`Vinp inpx 0 …` drove the gates from **ideal** voltage sources. An ideal source holds
its node rigid, so the charge the input pair pushes back through Cgd when the outputs
slew produced exactly zero disturbance. A real SAR comparator is driven by the DAC's
finite output impedance into its own held sampling capacitance, and that held value
is what kickback corrupts — along with every later bit decision in the conversion.

`rs_ohm` / `cs_ff` insert that network (`/api/kickback`, `strongarm_kickback`). They
describe the *driver*, not the comparator, so they are inputs; the 2 kΩ / 50 fF
defaults are a plausible SAR front end, not a property of this circuit.

Measured on the seed sizing, next to the budget the tool was already optimizing:

| quantity | value |
|---|---|
| offset σ (input pair, MC) | 1.85 mV |
| input-referred noise σ | 0.053 mV |
| min usable input @ BER 1e-3 | 5.72 mV |
| **kickback, differential** | **27.6 mV** |
| **kickback, single-ended** | **67.9 mV** |

Kickback is **14.9× the offset σ** being minimised and **4.8× the smallest input the
tool claims to resolve**. Worse, it opposes the offset lever: growing the input pair
buys matching and pays kickback (6.2 → 27.6 → 37.9 mV across W = 2 → 8 → 24 µm), a
trade the optimizer cannot currently see. Sanity checks all hold — kickback rises
with input-pair Cgd, falls with the held capacitance, and falls with a stiffer driver.

### Offset budget past the input pair

`measure_offset` modelled the input pair alone; the code called latch and tail
mismatch "a documented extension point". For a StrongARM the cross-coupled pair
fires exactly when regeneration is deciding, and the precharge pair leaves the
outputs at unequal starting points. `/api/offset/budget`
(`strongarm_offset_budget`) perturbs each matched pair by **its own** Pelgrom σ from
its own W·L·M, one at a time, and reports the breakdown:

| device | Vth σ | input-referred offset σ |
|---|---|---|
| `input` | 1.25 mV | **1.448 mV** |
| `ncc` | 3.33 mV | 0.611 mV |
| `prei` | 3.33 mV | 0.490 mV |
| `pre` | 3.33 mV | 0.462 mV |
| `pcc` | 1.57 mV | 0.424 mV |
| **RSS total** | | **1.761 mV** |

So the input pair does dominate — the original comment was right about that — but the
input-pair-only figure **understates the total by 22%**. Note the latch devices carry
a *larger* Vth σ (they are smaller) yet contribute *less* input-referred offset,
because latch mismatch is divided by the input pair's gain on the way to the input.
`tail` is excluded on purpose: one device, no differential partner, so its mismatch
is common-mode rather than offset.

### Input common-mode range — and why there is no CMRR number

`vcm_frac` was a parameter nothing swept, which hid two things
(`/api/cmrange`, `strongarm_cmrange`):

| vcm_frac | Vcm | t_dec | offset σ | functional |
|---|---|---|---|---|
| 0.40 | 0.280 V | — | 1.33 mV | **no** |
| 0.45 | 0.315 V | — | 1.33 mV | **no** |
| 0.50 | 0.350 V | 1867 ps | 1.33 mV | yes |
| **0.62 (default)** | 0.434 V | **530 ps** | 1.33 mV | yes |
| 0.70 | 0.490 V | 307 ps | 1.33 mV | yes |
| 0.95 | 0.665 V | **198 ps** | 1.33 mV | yes |

- **A hard lower bound.** Below vcm_frac 0.50 the latch does not resolve at all —
  not a slow corner, a wall. Nothing reported it before.
- **The seed operating point costs 2.7× in speed** (530 vs 198 ps) across a 9.4×
  spread. The *input pair's* σ is flat to 6 significant figures in Vcm, because its Vth
  mismatch refers to the input gate-to-gate.

  > **Correction.** This section originally concluded that the operating point is
  > therefore "nearly-free speed", a speed/power knob only. That is wrong, and it was
  > wrong because only the input-pair term was measured. The **latch's** contribution
  > grows **~7×** over the same sweep (ncc 0.72 → 5.05 mV as vcm_frac goes 0.62 → 0.90),
  > so raising the operating point is paid for in offset — through the latch. The
  > analytic budget now carries that term; `cm_range_sweep`'s `with_offset` still shows
  > only the flat part, and says so.

**No CMRR figure is returned, on purpose.** CMRR is ΔVcm/ΔVos on the *systematic*
offset, but this deck is perfectly symmetric — identical devices into identical
loads — so with zero mismatch the systematic offset is zero at every Vcm and CMRR
is infinite. Probing it returns 0.4688 mV at every single Vcm, which is exactly the
offset bisection's own quantisation step (60 mV / 2⁷ / 2) — an artifact, not a
measurement. Real CMRR needs asymmetry this netlist does not have (layout gradients,
unequal loading). A test pins that reasoning so the "missing" number does not later
get filled in with the artifact.

### The optimizer can now see kickback

Kickback runs well above the offset σ the cost function minimises **and moves
against the same lever**, so the search was trading blind. An optional
`targets.kickback_diff_mv` puts it in the constraint set (one extra simulation per
candidate, evaluated only when a target is given):

| kickback target | input W | offset σ | kickback |
|---|---|---|---|
| none | 19.12 µm | 1.32 mV | — |
| ≤ 30 mV | 29.53 µm | 0.966 mV | 10.3 mV |
| ≤ 10 mV | 7.06 µm | 2.011 mV | 4.35 mV |
| ≤ 5 mV | 2.73 µm | 3.230 mV | 4.96 mV |

Tightening kickback shrinks the input pair and gives back offset — the trade is now
priced instead of ignored. A non-binding target leaves the sizing unchanged, and
when the two specs genuinely conflict (offset ≤ 1.0 mV with kickback ≤ 3 mV) the
optimizer reports `success: false` rather than quietly satisfying one of them. That
conflict is the honest signal that kickback wants a *system* fix — a bigger held
sampling capacitance or a stiffer driver, both of which live in `cs_ff`/`rs_ohm`
rather than in any device width.

### Hysteresis — and the reset check it corrected

A StrongARM's nodes must return to the rails during precharge, or the previous
decision biases the next: a data-dependent offset that in a SAR ADC correlates with
the code and therefore **does not calibrate out**. The deck evaluated once, so this
was invisible. `/api/hysteresis` (`strongarm_hysteresis`) runs two decisions in one
transient — prime the latch, then bisect the *next* cycle's threshold — and compares
the two priming polarities:

| clk period | hysteresis | differential reset residue | absolute reset check |
|---|---|---|---|
| 4.0 ns | 0.0 mV (below resolution) | 0.00 mV | passes |
| 1.0 ns | ≤0.47 mV (below resolution) | −0.24 mV | passes |
| 0.6 ns | **3.28 mV** | −8.87 mV | passes |
| 0.45 ns | **17.34 mV** | −30.81 mV | passes |

At 0.45 ns the hysteresis is ~9× the offset σ — and unlike offset it tracks the data.
The measurement reports its own bisection resolution so the values at relaxed clocks
are not read as measurements.

**That last column is a defect this uncovered.** `max_fclk_sweep`'s reset criterion
tested *absolute* output levels only. At 0.45 ns the outputs come back to 0.681 and
0.712 V, so ">0.9·VDD" passes on both while 31 mV of **differential** memory survives
into the next decision. Fixed: the criterion now also requires the residue to be
within 1% of VDD (`reset_residue_limit`), and each period reports
`reset_absolute_ok` / `reset_balanced` / `reset_residue_mv` separately.

Effect on the headline number — at a fast operating point (vcm_frac 0.95),
**max f_clk drops 2.0 → 1.25 GHz**: the 0.6 and 0.5 ns periods resolve and pass the
absolute check but leave −9.96 and −23.7 mV of residue. The previous figure was
overstated by 1.6×. At the default operating point nothing changes, because
resolution binds before reset does — the fix does not penalise designs that were
already honest.

### Clock edge rate

`clk_trf_ps` was hardcoded at 12 ps (`/api/clockedge`, `strongarm_clockedge`).
Reported as **max f_clk vs edge rate**, not decision time vs edge rate, because
decision time is nearly flat in it — 1.6% across 5–200 ps, since `tdec` is timed from
the clock's own VDD/2 crossing, so a slower edge moves the trigger along with the
response.

The cost shows up as headroom, and **only when the design is near its limit**:

| operating point | max f_clk at 12 ps | at 200 ps | spread |
|---|---|---|---|
| default (vcm_frac 0.62) | 0.667 GHz | 0.667 GHz | **1.0×** |
| fast (vcm_frac 0.95) | 2.0 GHz | 1.0 GHz | **2.0×** |

So a comparator with headroom does not care about clock quality; one running at its
limit sets a clock-tree spec. Run the sweep at the operating point you intend.

**There is no clk/clkb skew to sweep** — this topology is single-clock, with the tail
switch and the precharge PMOS both driven from `clk`, so the race is between those two
devices on one edge rather than between two clock phases. (`clkb_line` was dead code
and is gone.)

### The optimizer now prices mismatch on every pair — and a loop keeps it honest

Following the discovery that the search was gaming its input-pair-only offset term,
the cost function now uses an analytic budget over all matched pairs
(`run_sim.predicted_offset_budget_mv`). Getting there needed three corrections, each
found by measurement rather than reasoning:

**0. The reference is deterministic — and everything above it depended on that.** Each
group's mismatch enters as a **single scalar** `d ~ N(0, σ√2)`, so the offset σ is a
one-dimensional expectation, not a sampling problem. Monte Carlo on a 1-D Gaussian buys
nothing but variance. `offset_budget` now evaluates it by **Gauss-Hermite quadrature**:
5 nodes at 16 bisection steps, agreeing to **0.04%** across 3, 5, 7 and 9 nodes, and
repeating bit-for-bit. It is also *cheaper* than what it replaced — 5 bisections per group
against 12 — so the old path was paying more for a worse answer.

How much worse:

| | Monte Carlo, n_mc=12 | quadrature |
|---|---|---|
| same sizing, repeated | 0.42 / 0.51 / 0.39 mV | identical every time |
| standard error per estimate | 21% | — |
| bias vs the exact answer | **−10.7%** (7 of 8 seeds low) | 0.04% |
| bisections per group | 12 | 5 |

The bias is the part that matters. The old reference was not merely noisy, it read
**optimistic** at the sample count actually used (closing to −1.6% only at n_mc=32) — the
same direction as the model's own error, so the two compounded instead of cancelling, and
no amount of seed-averaging could remove a bias. This is the single root cause behind
every mis-fitted constant in this section, including two wrong published values of the
dominant one. The MC path is kept as `method="mc"` for comparison.

Two defects fell out of looking at it. `_offset_of_pair` seeded its RNG with
`seed + hash(group)`, and `hash` on a `str` is **salted per process** — so a function that
took a `seed` returned a different draw set on every interpreter (`hash("ncc") % 10000`
gave 7174, 8200, 5952 on three consecutive runs). Every non-input reference number ever
recorded, including the calibration history, came from an unreplayable draw set; it uses
`zlib.crc32` now. And a quadrature node that fails to converge reports **no number** rather
than a partial rule, whose weights no longer sum to 1 and whose variance therefore comes
out low — optimistic again.

**1. The offset bisection was too coarse to measure what was being fitted.** 7 steps
over ±60 mV quantise to 0.47 mV. The latch and precharge contributions land *at* that
step — measured values pinned at 0.494 mV across sizings that should have differed —
so the earlier "RSS 1.761 mV, 22% understated" figure was partly floor artifact. It
also biased the headline input-pair σ up to **19% high** for large-area designs
(0.906 → 0.764 mV on a 24 µm input pair), which are exactly what the optimizer
produces. Default is now 11 steps (0.029 mV); 13 gives the same numbers. Cost: offset
MC 0.85 s → 1.34 s. The search itself uses the analytic path, so only explicit MC pays.

**2. The input referral factor is exactly √2, and it is not a fitted number.** Measured
deterministically, the input pair's input-referred offset is `v = −d` for a differential
Vth mismatch `d`: the ratio is 1.0000 to within **0.06% on all four backends and out to
4σ**. A linear response has σ_out = σ_in exactly, and two independent devices give
σ_diff = √2·σ_1dev. So the textbook value was right, and `input_referral_is_linear()`
verifies the property instead of refitting the constant.

> **Correction (third and final on this constant).** It was published as √2, "corrected"
> to **1.06**, then "corrected" to **1.268**. Both corrections were wrong — by −25% and
> −10%, on the model's **dominant** term, in the optimistic direction. All three errors
> have one cause: a Monte-Carlo reference with a 21% standard error per estimate was
> treated as ground truth. It converges to √2 as n grows — −16.7% at n_mc=12, −3.4% at 64,
> +2.5% at 256 — so it was never in conflict with the textbook, it was just noisy. The
> lesson is not about this constant. It is that **a fit is only as good as its
> reference**, which is why the reference is now deterministic.

**3. `pcc` had to be modelled as a constant, not σ-proportional.** Its contribution
*rises* with its own width (0.286 → 0.442 mV over 0.5 → 16 µm) because its leverage on
the regeneration grows faster than its σ_Vth falls. A σ-proportional term would have
penalised shrinking it — backwards. `pre`/`prei` are ~0.026 mV regardless of width,
150x below the input pair, so they are carried as constants only for completeness.
**`ncc` is the one term that mattered and was missing**: its contribution falls 9.3x as
its width goes 0.5 → 16 µm.

**4. The whole latch law is per backend — the exponents were the problem, not the scale.**
The constants were fitted on ptm45 and applied to all four backends. The `exp(7.02·(vcm−
0.62))` term does transfer (its ratio at vcm 0.82 measures 3.55–4.30 across the backends
against a fit of 4.07). The rest does not, and the give-away was **K's drift across a 16x
ncc-width sweep: 39% on ptm45, but 82/174/176% elsewhere.** A single coefficient cannot
absorb 176% of drift — that is a wrong *shape*, and it stays wrong however the magnitude is
rescaled. Refitting per model on a 2-D grid (input W × ncc W varied independently, so the
σ exponent and the geometry exponent are separable) gives a genuinely different law:

| backend | law | width drift | fresh-set error, global exponents | per-model |
|---|---|---|---|---|
| ptm45 (BSIM4 45nm) | 0.1175·σ^0.68·r^0.37 | 39% | **3.9%** (24.5% worst) | rejected |
| asap7 (BSIM-CMG FinFET) | 0.1647·σ^2.22·r^−0.10 | 31% | 42.7% (177.8%) | **11.4%** (37.6%) |
| gaa2nm (scaled, trend-only) | 0.1536·σ^2.24·r^−0.02 | 41% | 30.6% (136.0%) | **21.9%** (57.4%) |
| sky130 (real PDK) | 0.3173·σ^2.55·r^−0.23 | 49% | 34.5% (185.7%) | **16.6%** (41.7%) |

σ^2.2–2.5 with essentially no geometry-ratio dependence, against ptm45's σ^0.68·r^0.37 —
a different dependence, not a different scale. Median error falls 2–4x and worst case 3–5x,
the width drift closes to ptm45's own level, and on ptm45 the refit was **rejected** (1.3%
→ 1.6% on the gate set), so three of four accepted and one refused.

**Which error figure gets published matters more than the fit.** Four were available:

| measured on | ptm45 | asap7 | gaa2nm | sky130 |
|---|---|---|---|---|
| the **seed** sizing, where K is fitted | −0.2% | −0.2% | −0.0% | −0.0% |
| the 8 sizings used to **accept** the fit | 1.3% | 3.7% | 10.0% | 9.9% |
| a **fresh** set neither fit nor gate saw | **3.9%** | **11.4%** | **21.9%** | **16.6%** |

There is a fourth number, and it is the largest: **at the sizings the optimizer actually
converges to, the model over-predicts 1.31x / 1.53x / 1.99x / 1.36x** (median over 3
seeds; asap7 and gaa2nm reproduce exactly). The search does not sample sizings evenly — it
seeks out whatever the model rates cheapest — so its converged region has its own bias,
and no validation set drawn by hand will show it.

Every one of those is *above* 1, i.e. conservative. That is the safe direction, and it is
the opposite of where this model started: the same selection effect once ran optimistic,
which is precisely how the search came to game its own offset term. But 1.99x on gaa2nm
means roughly twice the latch area offset actually requires, so it is a cost and not just
comfortable margin. Closing it means folding optimizer-converged sizings into the fit —
`scripts/calibrate_offset_model.py` does that via `optimizer_sizings()`, a fixed-point
iteration since the sizings depend on the constants being fitted. **Not done deliberately:
a refit that lands optimistic here would be worse than a known 2x of conservatism.**

End-to-end, all three tested backends now meet their offset target with the measured
budget (ptm45 1.50 mV / 2.0, asap7 3.16 / 6.0, sky130 1.25 / 2.5).

The third row of the table is what `offset_model_accuracy()` reports. The seed row would have claimed a
model exact everywhere while it was ~55% wrong one sizing away; the gap between rows two
and three is pure selection — gate on a set and it stops being an independent estimate of
anything. The fresh set also reaches deliberately outside the fitted ranges (ncc 0.4 and
16 µm, input 2 and 50 µm), because σ^2.2 extrapolates hard.

Per-model `pcc` and precharge constants were also fitted, tested, and **not shipped**:
they changed held-out error by ≲1 point and made sky130 worse (17.7% → 21.1%). Four
per-backend micro-decisions worth a point each is fitting the validation set. Their
*global* values are updated against the clean reference (`0.3176·W^0.1283` →
`0.3161·W^0.1464`; the flats 0.030 → 0.0067/0.0054).

`run_sim.offset_model_accuracy(p)` reports the held-out error for the backend in use, and
every server response carrying a predicted offset carries it — `optimize` as
`offset_model_accuracy`, `design_brief` as `predicted_offset_accuracy`. It reports the
*number*, not a `calibrated: true/false`: a boolean reading "true" for a backend 23% wrong
out of sample is the same false reassurance a single global constant gave.

Result on ptm45, compared at the same 2.0 mV target across four seeds:

| objective | ncc W median | measured budget | median | met target | power median |
|---|---|---|---|---|---|
| input-pair only | 1.33 µm | 2.02–4.00 mV | 3.00 | 0/4 | 20.8 µW |
| **full budget** | **2.25 µm** | **1.99–3.00 mV** | **2.35** | 1/4 | 24.3 µW |

Honest reading: the pathological case is gone and the median improves 22%, at ~17%
more power. It is **not** uniformly better — one seed came out slightly worse, which is
what a predictor with this much error guiding a stochastic search should be expected to
do. Three of four runs still miss a tight target, so the measured `offset_budget` check
on the winner remains the backstop.

#### How accurate is the predictor, honestly

It tracks the measured budget to ~8% mean / 19% worst on the fitting grid. But the
**measured reference itself scatters 27–28%** across estimator seeds at n_mc 12–24
(14% at n_mc 48), so the model cannot be shown to be better than that, and no safety
factor was tuned onto the residuals because that would be fitting noise. Tests assert
35–40% against a *median over estimator seeds*; a single-draw reference made one
assertion intermittently fail, and the flakiness was the reference moving, not the model.

#### The same flaw was in two more places

Fixing the single-objective cost function exposed that `optimize_pareto`'s constraint
and `design_brief`'s headline both used the input-pair-only figure too — the Pareto
front therefore admitted designs whose real offset was worse than reported, for exactly
the same reason. Both now use the full budget. It was free in the Pareto loop, which
already runs one simulation per candidate and needed no extra one; the front now keeps
`ncc` at 3.75–7.56 µm where it used to collapse. `design_brief` returns both figures
plus the per-device terms, so the difference is visible rather than implied.

#### The self-improvement loop

`scripts/calibrate_offset_model.py` closes the loop those constants sit in — they were
otherwise a snapshot of one afternoon, with nothing to notice if the circuit, the model
card or the measurement changed underneath them:

    measure a grid → re-fit → validate on HELD-OUT sizings → accept or reject

The held-out gate is the point: a refit that fits the training grid better but the
held-out sizings worse is rejected, so the loop cannot talk itself into overfitting.
Every run appends to `out/offset_model_history.jsonl` whether it accepted or not, so
drift is visible even when nothing changes. `--apply` rewrites the constants in place
(keeping a `.bak`); without it the loop only reports.

The loop immediately earned itself twice. It flagged that `R_input` refits to 1.363
rather than 1.06 — because it was being fitted on the *latch* grid, where ncc is driven
to 0.5 µm and a weak latch inflates the input pair's measured offset. The held-out error
even "improved", because the held-out set shared the same skew: a gate only guards
against overfitting when the held-out data is drawn differently. `R_input` now has its
own nominal-latch sweep. Then a test caught that two of the eight held-out sizings were
also in that sweep, making a quarter of the gate training data.

### Sign-off now covers the terms that dominate — and the optimizer confesses

`fullflow` ran sizing → post-layout → PVT → layout/DRC and called that sign-off. It
omitted every input-referred error term measured above to be first-order. Four stages
added: **offset budget** (all matched pairs), **kickback**, **hysteresis at the
design's own max f_clk** (not an arbitrary period), and **common-mode range**.

A stage with no target is measured but **not judged** — `ok: null` — and the flow
lists those in `reported_not_judged` next to `overall`, so `overall: true` cannot be
read as "everything passed".

#### The optimizer was gaming its own offset spec

The offset-budget stage immediately caught something worse than a missing report. The
cost function prices **only the input pair's** mismatch, so minimising power the
search grows the input pair — the one thing the penalty sees — and shrinks the latch
and precharge pairs, whose mismatch is then free:

| device | seed W | optimizer W | seed Vth σ | optimizer Vth σ | offset contribution |
|---|---|---|---|---|---|
| `input` | 8.0 µm | **19.12 µm** | 1.250 mV | 0.809 mV | 1.285 → **0.889 mV** |
| `ncc` | 4.0 µm | **1.16 µm** | 3.333 mV | 6.190 mV | 0.656 → **3.164 mV** |
| `pcc` | 9.0 µm | 0.79 µm | 1.571 mV | 5.304 mV | 0.484 → 0.484 mV |
| **RSS total** | | | | | **1.669 → 3.392 mV** |

**The reported offset improves (1.285 → 0.889 mV) while the real offset doubles
(1.669 → 3.392 mV)**, and `ncc` overtakes the input pair as the dominant contributor.
A textbook case of optimising against an incomplete model.

The *mechanism* is fully reproducible; the *magnitude* is not. Across four optimizer
seeds the latch always collapses (ncc 0.50–1.19 µm from a 4.0 µm seed) and **`ncc` is
the dominant contributor in every run**, but the real-to-reported ratio lands anywhere
from **2.3× to 7.1×** depending on where the stochastic search settles — so treat the
ratio as "large and unpredictable", not as a number. The σ estimates themselves carry
~15–35% run-to-run spread at these Monte-Carlo sample counts, which is why the warning
triggers on a coarse 1.25× threshold rather than reporting a precise factor.

`optimize` measures the winner once against the full budget and reports it
(`offset_budget`, `offset_budget_warning`). `budget_check=False` skips it; cost is
6.2 s → 9.1 s on ptm45.

**Superseded in part:** the cost function now prices every pair (see below), so the
warning is no longer evidence of a modelling gap — it is a pointer to whichever device
is binding, which is usually `ncc`. Judge a design against `total_sigma_mv` and grow
the device the warning names; growing the input pair will not help.

## Merging related sidebar pages

The console has 24 pages (14 comparator + 10 VCO), several of which are views of
one underlying measurement rather than separate analyses. The overlap is in the
code, not just the visual design:

**Built — `Resolution (merged)`, replacing three pages' worth of reading.**
Metastability, Monte-Carlo offset and BER all answer one question about one
variable: how small a differential input this comparator can be given. `ber_curve`
was already running the offset Monte-Carlo that the Monte-Carlo page displays, and
both sweeps used the same 10 µV..100 mV log axis. `/api/resolution` measures once —
the τ sweep and one noise+offset run, in parallel — and evaluates BER analytically
at the sweep's own amplitudes, so both curves land on identical x values.

What the merge buys is not speed (it is the same 158 simulations either way; the
deck cache already deduplicated the repeated offset MC across the three separate
calls). It is that two things only visible together:

- **"Resolved" does not mean "correct."** At 10 µV the latch reaches a rail — the
  metastability view reports `resolved: true` — while BER is 0.498. A coin flip
  that took 993 ps.
- **Offset, not noise, sets the floor.** Minimum usable input is 165 µV on noise
  alone but 5719 µV once chip-to-chip offset is included: a 35x difference. The
  fix is input-pair area, not tail current — and the page says so.

**Not built, but the same argument applies** (recorded here rather than acted on):

| candidate merge | why they are one story |
|---|---|
| `pvt` + `yield` + `wicked` | all statistical sign-off; the WiCkeD flows already run corner and yield sweeps internally |
| `optimizer` + `pareto` + `sensitivity` | one sizing decision; `pareto` now returns `sizing_relation`, which is exactly the bridge |
| `layout` + `flow` | `flow` already runs layout + DRC as one of its stages |
| `vcopn` + `vcopushing` | both are supply/spectral sensitivity of the same oscillator |
| `vcopvt` + `vcoyield` | the VCO half of the robustness cluster |
| comparator vs VCO `pvt`/`layout`/`pareto`/`flow` | identical views over a different circuit — candidates for one page with a domain toggle rather than parallel trees |

## Sizing corners: one worst case, or all 45?

Measured, because the answer is two-sided and easy to over-claim. Sampled 24
random sizings x 45 corners on ptm45, against the corner the optimizer sizes
against (slow-N / -40 C / 0.9 x VDD):

**Functionality — one worst corner is enough.** No sizing passed that corner and
then failed a different one (0 / 24), and the failing corner sets are *nested*, so
it really is the hardest. Dropping the guard is not free: nominal-only sizing left
**5 / 45 corners non-functional**, while the guarded sizing left 0.

**Timing — a subset is not enough.** The slowest *resolving* corner landed on
**16 different corners** across those 24 sizings and was **never** the assumed
one. The three most frequent worst corners still under-estimate worst-case
decision time by up to **73%**.

Physically: failing to resolve is limited by insufficient regeneration, which is
monotone in slow-N + cold + low overdrive, so it has a single hardest corner.
Decision *time* among the corners that do resolve is a competition between tail
current, latch strength and load whose balance shifts with sizing — so its argmax
wanders.

So the split this tool already uses is the right one, and its guarantee has a
boundary worth stating: **size with one corner, sign off with all 45.** `optimize`
returns `corner_guarantee` saying exactly that, because `final_corner` otherwise
looks like a timing result. In one measured run the guarded design's worst corner
came in at 983 ps against a 1000 ps relaxed budget — 1.7% margin, and only because
the constraint had made that corner binding, not because it was predictable.

## Reading a Pareto front as a sizing decision

`/api/pareto` returns `sizing_relation` alongside the front: how far each device
group's width travels along it, and a rank correlation against each objective, so
"move right on the curve" becomes "widen this device". On the comparator's
power↔speed front:

| device | W span | corr(power) |
|---|---|---|
| `tail` | 80x | +0.98 |
| `input` | 31x | +0.97 |
| `pcc` | 14x | +0.95 |
| `prei` | 12x | +0.32 |
| `pre` | 21x | **−0.15** |

The trade-off is bought almost entirely with `tail` and `input`. `pre` barely
participates — it only conducts during reset, so it is not on this curve. Note the
two objectives' correlations are exact negatives on a 2-objective front by
construction: that is one finding per device, not two.

## How agents close the loop

- **This session:** agents call `python3 run_sim.py <file>` via Bash. The
  Tuning Orchestrator writes a candidate params JSON, runs it, reads the
  metrics, and adjusts the dominant device for whichever spec is violated
  (offset → input-pair area; speed → tail/latch; power → total width).
- **Future sessions:** register the MCP server so agents call it as a tool.

### Register the MCP server (future sessions)

Add to `~/.claude/settings.json` (or project `.mcp.json`):

```json
{
  "mcpServers": {
    "strongarm-sim": {
      "command": "python3",
      "args": ["/Users/kos2001/gitspace/ip-dev-fde/strongarm_sim/mcp_server.py"],
      "cwd": "/Users/kos2001/gitspace/ip-dev-fde/strongarm_sim"
    }
  }
}
```

Restart Claude Code; the tool `strongarm_run_sim` becomes available.

## Expose the optimizer through hermes-agent's api_server

> Agent-facing assets (profile setup, MCP registration script, and the agent
> **skills** — `strongarm-console`, `analog-ic-robustness-optimization`) live in
> **`hermes/`**; see `hermes/README.md`. The web console's floating 🤖 agent
> panels proxy to this profile via `/api/agent/chat` (session-scoped, MCP-only
> steering).

The whole console is registered as a hermes-agent MCP server (`mcp_server.py`)
so it is callable through the OpenAI-compatible **api_server** (the dedicated
`strong-arm` profile, `:8645`, and the hermes-gateway front). It now exposes
**46 tools** covering both domains: simulate / optimize (single + NSGA-II) /
metastability / noise·BER / PVT (45 corners) / WiCkeD yield & robustness /
layout / netlist text export + raw-deck `spice_run_netlist` — all proxying to
the running backend at `$STRONGARM_API` (default `:8770`). A client can ask the
agent to "size / sign off a StrongARM comparator" and it drives the flow.

Registered via:

```sh
hermes mcp add strongarm --command python3 \
  --args /Users/kos2001/gitspace/ip-dev-fde/strongarm_sim/mcp_server.py
```

- Written to the **active profile** (`lsi`) at `~/.hermes/profiles/lsi/config.yaml`
  under `mcp_servers`, `enabled: true`. The `lsi` profile backs the primary
  `default`/`ai-fde` api_server upstream (`:8643`).
- hermes appends every enabled MCP server to each session's toolset
  (`agent/coding_context.py` → `[profile.toolset, *_enabled_mcp_servers(config)]`),
  so the tool is exposed on the api_server platform, not just the CLI.
- Verified: `hermes mcp test strongarm-sim` connects and discovers the tool; a
  direct MCP `tools/call` runs ngspice and returns real metrics.

To also expose it on the **virtuoso-bridge** api_server (`:8650`, the Cadence
Virtuoso / analog instance):

```sh
hermes profile use virtuoso-bridge
hermes mcp add strongarm-sim --command python3 \
  --args /Users/kos2001/gitspace/ip-dev-fde/strongarm_sim/mcp_server.py
hermes profile use lsi     # restore your previous active profile
```

Call it through the gateway once an api_server instance is running (needs
network to the backing model):

```sh
curl -s http://127.0.0.1:8700/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_CLIENT_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"ai-fde","messages":[{"role":"user",
       "content":"Optimize a StrongARM comparator: offset sigma <=5mV, decision <=400ps, power <=100uW. Minimize input-pair area. Use strongarm_run_sim."}]}'
```

## Device model — PTM 45 nm bulk (real BSIM4)

`run_sim.py` includes a real published **BSIM4 (level=54)** model card:
`models/ptm_45nm_bulk.txt`, the ASU **Predictive Technology Model** 45 nm bulk
process (ngspice-ready copy from `github.com/indra-ipd/bag_deep_ckt-1`). Node
defaults: **VDD = 1.0 V, minimum L = 45 nm**. PTM is a predictive academic model
(not a specific foundry PDK) but it is a genuine BSIM4 card ngspice runs
natively, so absolute numbers are 45 nm-class realistic. Runtime ≈ 20-25 s per
full call (BSIM4 parse is heavier than a toy model); drop `n_mc` for faster
search iterations.

To use a **specific foundry PDK** (e.g. SkyWater sky130) instead, point
`MODEL_PATH` at that PDK's model file and adjust the netlist:

- Raw SkyWater sky130 models are **spectre-format** and reference instance
  params (`l`/`w`/`mult`) inside `.model` cards, which ngspice rejects
  (`Expression err`). They must first be converted via **open_pdks** to the
  ngspice variant (`sky130A/libs.tech/ngspice/sky130.lib.spice`).
- sky130 devices are **subckts** (`sky130_fd_pr__nfet_01v8 d g s b`), so change
  the `M1 …` lines in `gen_netlist` to `XM1 … sky130_fd_pr__nfet_01v8 w=… l=…
  nf=… mult=…`, use `.lib "…/sky130.lib.spice" tt`, and set VDD/min-L to the
  130 nm node (1.8 V core, L ≥ 0.15 µm).

Everything else — netlist topology, measurement setup, the agent loop — stays
the same. Also update the Pelgrom `avt_mv_um` to the PDK's value.

### ASAP7 7 nm FinFET — real BSIM-CMG 107 via ngspice OSDI (`"model": "asap7"`)

Not an approximation: the ASU **ASAP7 predictive PDK** model cards run on the
CMC **BSIM-CMG 107** compact model, compiled from Verilog-A to a native
`.osdi` plugin with **OpenVAF** and loaded by ngspice-46 (`pre_osdi`).

- Sizing is **integer fins**: the netlist folds `w_um × m` into
  `nfin = round(W_total / 0.07 µm)` (Weff/fin = 2·HFIN + TFIN). Node defaults:
  VDD 0.7 V, L 21 nm, LVT flavor. Corners: TT/SS/FF cards + cross corners
  (SF/FS) via the `DELVTRAND` instance parameter (note: **+ lowers Vth** —
  opposite sign to `delvto`; `gen_netlist` flips it).
- Rebuild the plugin after changing the va sources:
  `scripts/build_bsimcmg_osdi.sh` (needs `openvaf-r`; macOS builds from source
  with `brew install rust llvm@21`). Two local va patches are documented in the
  script header (instance-param attributes; an EOTACC bound 1-ulp float fix).
- Regenerate the cards from the ASU originals: `scripts/adapt_asap7.py`
  (level=72 → `bsimcmg`, `nmos/pmos` → `devtype 1/0`, drop `version`).

Measured (TT, preset sizing): comparator **94.8 ps / 2.3 µW** (16–36 fins),
VCO xcpl **2.96 GHz / 66.8 µW**, tuning 0.84–5.41 GHz.

### GAA 2nm≈ — scaled-BSIM4 trend card (`"model": "gaa2nm"`)

`models/gaa2nm_approx.txt` scales the PTM card to IRDS 2 nm-class targets
(EOT 0.85 nm, |Vth0| 0.20 V, VDD 0.65 V) and suppresses short-channel roll-off
as a proxy for GAA electrostatics. W exists only on the **0.2 µm nanosheet-stack
grid**; corner skew is ±25 mV and Pelgrom A_VT defaults to 1.2 mV·µm. The layout
generator draws the nanosheet grid (CPP 48 nm, stack-row diffusion) with a
2 nm-class rule DRC. **Trend analysis only — real 2 nm PDKs are foundry-NDA.**
For a rigorous multi-gate model use the ASAP7/BSIM-CMG path above.

## MOSFET ring VCO (same optimization loop)

Beyond the comparator, the tool sizes a **pure-MOSFET current-starved ring VCO**
with the identical algorithm + flow depth. Its own **VCO domain** in the frontend
has 9 pages — Circuit·waveform / Sizing·tuning / Auto-size (DE + GP surrogate) /
**Pareto (NSGA-II, power↔frequency)** / **Phase noise (L(Δf) · jitter · FoM)** /
PVT corners / Supply pushing / **Layout (GDSII + DRC)** / **Full flow**
(`vco_sim.py`, `layout.generate_vco_layout`, `/api/vco/*`):

- **Topology** — N odd current-starved CMOS inverter stages in a ring; V_ctrl
  sets the tail current (NMOS ref mirrored to a diode PMOS → vbp), hence the
  per-stage delay `t_d ≈ C_L·VDD/I_D` and frequency `f = 1/(2N·t_d)`.
- **Cross-coupled topology** (`"topology": "xcpl"`) — a pseudo-differential
  variant: two odd-N starved inverter rails (N0/P0) tied at every stage by a
  weak cross-coupled PMOS pair (P1 = `Mx`/`Mxb`, Mansuri-CCO style), started
  deterministically by a reset PMOS (`Mrst`) that clamps `o1` while `rstb` is
  low — no `.ic` kick-start; the t=0 DC operating point *is* the reset state.
  Same V_ctrl tuning rails, so tuning/pushing/phase-noise/waveform all reuse
  the same pipeline. Keep P1 weak: oversized, it latches the stage
  (`oscillates: false`), which the mismatch MC below quantifies.
- **Metrics** — `measure_vco`: oscillation frequency, does-it-oscillate, power,
  swing. `vco_tuning`: sweeps V_ctrl → tuning range %, Kvco (GHz/V), center.
- **Auto-size** — `optimize_vco` (log-space Differential Evolution + `_pmap`
  parallelism) sizes the four device groups (core Mp/Mn, starve Mbp/Mbn) to hit
  a **target frequency** at minimum power, subject to must-oscillate. On the PTM
  seed it tunes ~0.57–2.24 GHz (≈119 %, Kvco ≈2.75 GHz/V) and hits a 2.0 GHz
  target within a few percent.
- **Pareto (NSGA-II)** — `optimize_vco_pareto` maps the power ↔ frequency
  trade-off (min power, max frequency, must-oscillate); the front gives the
  min-power sizing at each frequency.
- **Layout + parasitics** — `layout.generate_vco_layout` synthesizes the ring's
  GDSII (bias mirror + N stages, multi-finger MOS + guard ring) with rule DRC;
  `layout.extract_vco_parasitics` derives per-ring-node C from the drawn
  geometry, and the post-layout re-sim shows the frequency drop (~5%).
- **Phase noise / jitter** — `phase_noise` gives a first-order thermal estimate:
  each stage transition jitters by √(kT·C)/I, 2N per period accumulate →
  L(Δf) = 10log₁₀(f₀³·σ_T²/Δf²) (the −20 dB/dec 1/f² region), plus period jitter
  and the VCO FoM. Uses the frequency-consistent node cap C = I·t_d/VDD, so no
  extra guess. Thermal-only, not a PSS/pnoise sign-off.
- **Full flow** — `vco_fullflow` chains auto-size → post-layout re-sim → PVT
  sign-off → layout/DRC, mirroring the comparator's end-to-end flow.

```bash
python3 vco_sim.py            # nominal: f_osc / oscillates / power
python3 vco_sim.py --tune     # V_ctrl tuning sweep -> range, Kvco
```

> The VCO's cross-region is conceptually the flip side of the comparator: both
> lean on regenerative CMOS feedback — the comparator *decides once*, the VCO
> *oscillates forever*. (LC-VCO's cross-coupled −gm core is literally the
> StrongARM latch structure.)

## WiCkeD-inspired robustness flow

`wicked.py` applies the public WiCkeD methodology ideas to this open ngspice
backend. It is not Cadence/MunEDA WiCkeD, but it implements the same class of
workflow primitives in an inspectable way:

- **FEO** feasibility check: run nominal SPICE and report functional/spec margins.
- **DNO-like refinement**: sensitivity-guided nominal sizing moves for offset,
  decision-time, and power.
- **WCO** worst-case operation: enumerated process × temperature × VDD corners.
- **WCD/high-sigma proxy**: nearest-failure sigma estimate combining analytic
  Pelgrom mismatch distance with ngspice-backed PVT boundary sampling.
- **Full-device mismatch budget**: input-pair plus weighted latch/tail/precharge
  Vth contributors so second-order offset risk is visible.
- **Importance-sampled yield proxy**: shifted high-sigma sampling around the WCD
  limiting region with Gaussian likelihood reweighting.
- **Yield-aware robust optimizer**: compact coordinate search using WCO/WCD
  feedback for design centering.
- **Yield-aware report**: estimated yield %, limiting mechanism, samples, and
  per-stage pass/fail verdicts.

CLI smoke run:

```bash
python3 - <<'PY'
import json, wicked
r = wicked.wicked_flow(
    {},
    {"decision_time_ps": 400, "power_uw": 400, "offset_sigma_mv": 20, "yield_pct": 90},
    dno_iterations=1,
    wcd_samples=4,
)
print(json.dumps({"overall": r["overall"], "stages": r["stages"]}, indent=2))
PY
```

HTTP endpoints exposed by `webapp/server.py`:

- `POST /api/wicked/dno` — DNO-like nominal refinement
- `POST /api/wicked/wcd` — WCD/high-sigma proxy
- `POST /api/wicked/mismatch` — full-device mismatch budget
- `POST /api/wicked/importance` — importance-sampled high-sigma yield proxy
- `POST /api/wicked/optimize` — yield-aware robust design-centering search
- `POST /api/wicked/screening` — parameter sensitivity ranking
- `POST /api/wicked/yieldsweep` — yield vs global process variation (yield-plot)
- `POST /api/wicked/yop` — YOP-like yield optimization (maximize WCD beta)
- `POST /api/wicked/postlayout` — post-layout WCD re-evaluation
- `POST /api/wicked/corners` — worst-case corner extraction and ranking
- `POST /api/wicked/fullflow` — FEO → DNO → WCO-in-loop → full WCO → WCD → mismatch → importance → screening → corners → post-layout WCD

### WiCkeD for the VCO (`vco_wicked.py`)

The same methodology is ported to the ring VCO (both topologies), with the
comparator's spec triple replaced by *oscillates / frequency band
(f_ghz ± f_tol_pct) / power*:

- `nominal_verdict` — FEO-style margins against the f-band and power targets.
- `parameter_screening` — OAT width ranking for f and power, with a
  `kills_osc` flag on moves that stop the oscillation.
- `wco_operating` / `worst_case_corners` — 27 PVT corners, ranked by f-margin.
- `worst_case_distance` — WCD beta over (pskew, VDD, temp) with linear
  interpolation to the band edge; `yop_optimize` centers the design on beta.
- `mismatch_mc` — the comparator's Monte-Carlo offset analog: an independent
  Pelgrom `delvto` per MOSFET (both rails, bias, cross-couple, reset) →
  σ_f/f spread **and start-up failures** — the key xcpl risk, where mismatch
  strengthening P1 against a weakened tail latches a stage. No global-corner
  analysis reveals this.
- `yield_sweep` — mismatch+PVT MC per process-skew point (yield-plot style).
- `dno_refine` — feasibility (restore oscillation; for xcpl weaken P1) →
  center f with the starve widths → power trim via screening.
- `postlayout_wcd` — `layout.extract_vco_parasitics` → cload → WCD re-check.
- `wicked_flow` — staged FEO → DNO → WCO → WCD → mismatch MC → screening →
  corners → post-layout report (`POST /api/vco/wicked/fullflow`).

HTTP endpoints: `POST /api/vco/wicked/{verdict,screening,wcd,mismatch,
yieldsweep,dno,yop,postlayout,corners,fullflow}`.

MCP tools exposed by `mcp_server.py`:

- `strongarm_wicked`
- `strongarm_wicked_importance`
- `strongarm_wicked_optimize`
- `strongarm_wicked_screening`
- `strongarm_wicked_yieldsweep`
- `strongarm_wicked_yop`
- `strongarm_wicked_postlayout`
- `strongarm_wicked_corners`
- `vco_wicked` / `vco_wicked_mismatch` / `vco_wicked_screening` /
  `vco_wicked_wcd` / `vco_wicked_corners` — the VCO ports (both topologies)

Current limitations: WCD is a practical proxy, not a commercial high-sigma
implementation; only input-pair mismatch is directly injected into SPICE while
latch/tail/precharge are weighted analytic contributors; full Virtuoso/OA schematic
migration and sign-off DRC/LVS/PEX are outside this repo.

## Extension points (documented, not stubbed)

- **Transient noise** → add ngspice `.noise`/transient-noise and report
  input-referred µVrms.
- **Full-device mismatch offset** → inject Vth mismatch into latch/tail devices
  (per-instance model cards) so second-order offset contributions are captured.
- **PDK migration mapping** → add device/CDF/pin mapping files for Virtuoso-style
  source-PDK to target-PDK migration before re-sizing.
- **Sign-off extraction** → replace layout capacitance proxy with Magic/KLayout +
  LVS/PEX and feed extracted netlists back into the same WCO/WCD flow.

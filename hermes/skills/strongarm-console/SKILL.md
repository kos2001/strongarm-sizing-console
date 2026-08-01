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

### `l_nm` — L is **fixed**; W and M are the sizing knobs

Channel length is a methodology choice, not a searched variable — different L per
latch group breaks the symmetry the comparator's matching relies on. `optimize`
leaves L where the user fixed it (`optimize_l` defaults to false) and reports
`final_l_nm` + `l_report`.

- **Omit `l_nm` and you get the node's nominal** — ptm45 80/45 nm, sky130 150 nm,
  asap7 21 nm, gaa2nm 20/14 nm. You no longer have to send it, and you should not
  carry a 45 nm-class L onto a 7 nm or 2 nm-class backend.
- **Check `l_report.out_of_range`.** With L fixed, a bad fixed value is the quiet
  failure: below 45 nm the PTM card has no model and the deck *errors*, which
  surfaces as "non-functional" rather than "bad input". Say so instead of
  reporting a broken sizing.
- **`l_report.raised_by_pdk`** — sky130 silently builds a longer device than
  asked when the request is under the bin floor. Report the L that was built.
- Do not propose per-device L changes as a sizing move. If the user asks what a
  different *fixed* L would buy, that is `optimize_l: true` — an exploratory
  question, and worth mentioning that on ptm45 the input pair at 160 nm beats the
  seed's 80 nm on both speed (452 vs 530 ps) and matching (1.39 vs 1.85 mV σ).

## Before claiming a resolution, check kickback

`strongarm_kickback` measures how much the comparator disturbs the voltage it is
measuring — charge pushed back through Cgd when the outputs slew, into the DAC's
held sample. **It used to be unmeasurable**: the deck drove the gates from ideal
sources, which hold the node rigid.

On the seed sizing it is **27.6 mV differential — 14.9× the offset σ (1.85 mV) and
4.8× the minimum usable input (5.72 mV)**. So:

- Never quote an offset σ or a resolution as *the* input-referred error without
  saying whether kickback was checked. It is usually the biggest term.
- `rs_ohm`/`cs_ff` describe the **driver**, not the comparator (defaults 2 kΩ /
  50 fF). Say which values you assumed; ask for the real front end if it matters.
- **It fights the offset lever.** Growing the input pair improves matching and
  worsens kickback (6.2 → 37.9 mV over W = 2 → 24 µm). If a user asks to cut
  offset by widening the input pair, mention the kickback cost. Cutting kickback
  instead wants a bigger sampling cap or a stiffer driver — system changes.

## ⚠ The optimizer's reported offset is optimistic — check the warning

`strongarm_optimize` prices **only the input pair's** mismatch, so minimising power it
grows the input pair and shrinks the latch/precharge pairs, whose mismatch is then
free. Measured: input 8.0→19.12 µm and ncc 4.0→1.16 µm, so the reported σ *improves*
1.285→0.889 mV while the real budget goes 1.669→**3.392 mV**, with `ncc` becoming
dominant. Real-to-reported: **3.82× on the optimizer's own output**.

The result now carries `offset_budget` and `offset_budget_warning`. **When the warning
is present, quote `offset_budget.total_sigma_mv`, not the `offset` field**, and tell
the user which device dominates. Recommending "grow the input pair to cut offset"
after an optimize run is usually wrong — the latch is the problem by then.

`strongarm_fullflow` now includes offset budget, kickback, hysteresis (at the design's
own max f_clk) and common-mode range. Stages with no target come back `ok: null` and
are listed in `reported_not_judged` — **`overall: true` does not mean everything
passed**, so read that list before saying a design signed off.

## Hysteresis: the error that does not calibrate out

`strongarm_hysteresis` primes the latch one way, then finds the input threshold on
the **next** cycle, and compares against the other priming polarity. Measured on the
seed sizing: 0 at a 4 ns period, **3.3 mV at 0.6 ns, 17.3 mV at 0.45 ns** (~9× the
offset σ).

- Unlike offset, hysteresis **tracks the data**, so it does not trim out. If a user
  is running near max f_clk, check it before quoting an error budget.
- **`max_fclk`'s reset check alone is not sufficient.** It now reports
  `reset_absolute_ok`, `reset_balanced` and `reset_residue_mv` separately, because
  the outputs can both return near the rail while tens of mV of *differential*
  memory survives. If `reset_balanced` is false, the period is not usable however
  good the absolute levels look.
- The measurement reports `resolution_mv` and `resolved`; do not quote a hysteresis
  at or below the bisection step as a measurement.

## Clock edge rate: only matters near the limit

`strongarm_clockedge` sweeps `clk_trf_ps` and reports **max f_clk**, not decision
time — decision time is nearly flat in edge rate (timed from the clock's own VDD/2
crossing). Measured: 1.0× spread at the default operating point, **2.0× at a fast
one** (2.0 GHz at 12 ps → 1.0 GHz at 200 ps).

So: a design with headroom does not care about clock quality; one at its limit sets
a clock-tree spec. Run it at the operating point the user actually intends. And do
not offer a clk/clkb skew analysis — this topology is single-clock.

## The operating point is nearly-free speed

`strongarm_cmrange` sweeps `vcm_frac`. Two things to use it for:

- **There is a hard lower bound.** Below vcm_frac 0.50 the seed sizing does not
  resolve *at all* — a wall, not a slow corner. If a design "fails" at low common
  mode, check this before re-sizing anything.
- **The default 0.62 is 2.7× slower than 0.95** (530 vs 198 ps) across a 9.4×
  spread, at **no offset cost** — σ is flat in Vcm because input-pair mismatch is
  gate-referred. So when someone wants speed, raising the common mode is often
  cheaper than any width change. Offer it.

**Do not report a CMRR number.** The deck is symmetric, so systematic offset — and
hence CMRR — is structurally zero/infinite; the probe returns the bisection's
quantisation step at every Vcm. If asked, explain that rather than quoting it.

## Sizing against kickback

Pass `targets.kickback_diff_mv` to `strongarm_optimize` and kickback joins the
constraint set (costs one extra sim per candidate). Tightening it shrinks the input
pair and gives back offset — measured: ≤30 mV → W 29.5 µm / σ 0.97 mV, ≤5 mV →
W 2.7 µm / σ 3.23 mV.

When both specs are tight the run comes back `success: false`. That is the correct
answer, not a failure to optimize: kickback and offset pull opposite ways on the same
width, so the fix is systemic — a bigger held cap (`cs_ff`) or a stiffer driver
(`rs_ohm`). Say that instead of loosening a spec silently.

## Offset is not just the input pair

`strongarm_offset_budget` breaks offset σ down per matched pair, each perturbed by
its own Pelgrom σ. Measured: input 1.448 mV, ncc 0.611, prei 0.490, pre 0.462,
pcc 0.424 → **RSS 1.761 mV, so the plain offset number understates by 22%**.

Report the RSS total when the user asks for offset sign-off, and name
`dominant[0]` when they ask what to grow. Two things worth passing on: the latch
devices have a *larger* Vth σ but contribute *less* input-referred offset (latch
mismatch is divided by the input pair's gain), and `tail` is excluded because a
single device's mismatch is common-mode, not offset.

## Input resolution: one call, not three

`/api/resolution` (`strongarm_run_sim`'s console sibling) returns the τ sweep, the
Monte-Carlo offset σ, the noise σ and the BER curve **on one amplitude axis**.
Prefer it over asking for metastability, offset and BER separately — they are three
faces of one measurement, and two facts only show up together:

- **`resolved: true` does not mean correct.** At 10 µV the latch reaches a rail
  after 993 ps with BER 0.498. Never report "resolves down to X µV" from the
  metastability sweep alone; quote `markers_uv.min_input_total`.
- **Offset sets the floor, not noise.** Measured 165 µV noise-only vs 5719 µV with
  chip-to-chip offset — 35x. So when a user wants better resolution, the answer is
  **input-pair area (W·L·M)**, not more tail current.

## Corners: what one corner does and does not prove

`strongarm_optimize` sizes against a single corner (slow-N / −40 °C / 0.9·VDD) and
returns `corner_guarantee`. Measured over 24 random sizings × 45 corners:

- **Functionality: that corner is sufficient.** 0/24 sizings passed it and failed
  another, and the failing sets are nested. Without the guard, nominal-only sizing
  left 5/45 corners non-functional.
- **Timing: it is not.** The slowest corner landed on 16 different corners and was
  never the assumed one; the 3 most frequent worst corners still under-estimate
  worst-case delay by up to 73%.

So **never report timing closure from `final_corner`** — say "functional across
corners" and run `strongarm_pvt` (45 corners) before claiming a delay spec holds.
Quote `corner_guarantee` if the user asks how much the sizing run proved.

## Pareto ⇄ sizing: answer with the device, not the curve

`strongarm_pareto` returns `sizing_relation` — per device, how far its width
travels along the front and its rank correlation with each objective, plus
`drivers` (ordered) and `fixed_along_front`. Use it to answer trade-off questions
as sizing moves: on the comparator's power↔speed front the drivers are `tail`
(+0.98) and `input` (+0.97), while `pre` is ~uncorrelated (−0.15) because it only
conducts during reset. Telling the user "buy speed with tail width, not precharge
width" is more useful than handing over the curve.

Caveat to pass on: on a 2-objective front the two correlations are exact negatives
by construction — one finding per device, not two.

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

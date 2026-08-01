---
name: strongarm-fast-loop
description: "Use when answering StrongARM/VCO sizing questions through the strongarm MCP tools and the answer should arrive fast — choosing which tool to call, which model backend to search on, how many calls a request is worth, and when a re-check is free. Carries a measured cost table for every endpoint and backend, so tool choice is a budget decision rather than a guess. Read this before the first tool call of a sizing turn."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [semiconductor, eda, analog, strongarm, vco, ngspice, performance, latency, cost-model, mcp]
    related_skills: [strongarm-console, strongarm-design-recipes, analog-ic-robustness-optimization]
---

# StrongARM fast loop — spend SPICE seconds where they buy an answer

## Why this exists

Every tool here runs real ngspice. Two calls that answer the same question can
differ by 100x in wall time, and the agent picks which one runs. This skill is
the cost table plus the routing rules that follow from it.

The rule that matters most: **ask the cheapest tool that can actually answer the
question, then stop.** A 45-corner PVT sweep does not make a nominal-speed
answer more true — it makes it 4x slower.

## Measured cost table

Wall time per call on the default backend (`ptm45`), measured on a 10-core
arm64 mac with ngspice-46, each endpoint in a fresh server so *cold* means an
empty deck cache. **Warm** is the identical call repeated.

Treat these as orders of magnitude, not constants — they move ±50% with machine
load. What is stable, and what the routing rules below rest on, is the *ratios*:
offset MC ≈ 10x a plain sim, `optimize` ≈ 35x, `vco_optimize` ≈ 100x, sky130
≈ 4x any other backend.

| Tool / endpoint | cold | warm | notes |
|---|---|---|---|
| `strongarm_layout` | ~0.00s | ~0.00s | pure Python — no SPICE at all |
| `strongarm_run_sim` (no offset) | 0.10s | ~0.00s | one transient |
| `strongarm_maxfclk` | 0.11s | ~0.00s | 11 periods, parallel |
| `strongarm_sensitivity` | 0.18s | ~0.00s | |
| `strongarm_wicked_wcd` | 0.18s | ~0.00s | |
| `strongarm_metastability` | 0.14s | ~0.00s | 13 amplitudes → τ fit |
| `strongarm_yield` (n=24) | 0.27s | ~0.00s | |
| `strongarm_pvt` (45 corners) | 0.40s | ~0.00s | |
| `strongarm_wicked_corners` | 0.39s | ~0.00s | |
| `strongarm_run_sim` (**+offset MC**) | 0.99s | ~0.00s | **10x the no-offset call** |
| `strongarm_pareto` (NSGA-II) | 1.04s | ~0.01s | |
| `strongarm_optimize` (DE+GP, 108 sims) | 3.51s | ~0.02s | |
| `strongarm_fullflow` | 3.34s | ~0.02s | optimize + post-layout + PVT + DRC |
| `vco_simulate` | 0.24s | ~0.00s | |
| `vco_tuning` | 0.38s | ~0.00s | |
| `vco_pvt` (45 corners) | 2.02s | ~0.00s | |
| `vco_pareto` | 5.66s | ~0.01s | |
| `vco_optimize` (99 sims) | **10.28s** | ~0.01s | the most expensive tool here |

### Backend multiplier

Same endpoint, different `params.model` — this is the biggest lever you control:

| backend | `run_sim` | `pvt` 45 | `optimize` | vs ptm45 |
|---|---|---|---|---|
| `gaa2nm` | 0.07s | 0.39s | 3.24s | 0.9x |
| `ptm45` (default) | 0.10s | 0.45s | 3.56s | 1.0x |
| `asap7` | 0.53s | 0.70s | 5.43s | ~1.5x |
| `sky130` | 0.43s | 1.72s | **15.58s** | **~4.4x** |

## Routing rules

**1. Search cheap, confirm real.** Explore and iterate on `ptm45` (or `gaa2nm`
for 2 nm trend questions). Move to `sky130` only for the final confirmation or
when the user asked for the real PDK. A DE search on sky130 costs 15.6s; the
same search on ptm45 costs 3.6s and usually lands in the same place. Never
present `gaa2nm` as sign-off — it is a trend card.

**2. Pick by question, not by thoroughness.**

| The user asked | Call | Not |
|---|---|---|
| "how fast / how much power?" | `run_sim` **with offset off** | `run_sim` with MC offset (10x) |
| "what's the offset σ?" | `run_sim` with offset | — (this is the one case worth 1s) |
| "does it survive corners?" | `pvt` | `fullflow` |
| "size it to this spec" | `optimize` | `fullflow`, then a second `optimize` |
| "sign it off" | `fullflow` (once) | optimize + pvt + layout as three calls |
| "how big is the cell?" | `layout` | anything with SPICE in it |
| "power↔speed trade-off" | `pareto` | a hand-rolled sweep of `run_sim` calls |

**3. Skip the offset MC unless offset is the question.** It is 90% of a
`run_sim` call's cost and answers nothing about speed or power. For a sizing
anchor, the deterministic `pelgrom_sigma_vth_mv` comes back free with every call
(offset σ ≈ √2 · pelgrom) — quote that instead of paying for the MC.

**4. Re-checks are free; new candidates are not.** The backend memoizes each
ngspice deck by its text, so calling the same tool with the same params again
costs ~0.00s (see the warm column). Two consequences:

- Never refuse to re-verify a number because it "would be slow". It isn't.
- But changing *one* device width makes a new deck at full price. A 6-candidate
  hand sweep is 6 full-price sims; `optimize` runs 108 of them in 3.5s because
  it fans out in parallel. **Prefer one `optimize` call over a manual sweep.**
- After a `pvt` run, `wicked_corners` on the same sizing is nearly free — its
  corner decks are already cached. Order the expensive-then-related calls that
  way when you need both.

**5. One tool call per request is the target; two is the ceiling.** Three only
for the netlist text path (`*_netlist` → edit → `spice_run_netlist`). The
design state arrives in the message — put it straight into the tool's `params`.
Do not re-simulate a baseline the user just gave you.

**6. Report before you refine.** If the first call answers the question, answer
it. Offer the deeper sweep as a next step instead of running it unasked — the
user can spend the 10s if they want it.

## Cost self-check

`GET /api/health` returns `sim_cache: {hits, misses, size, max_procs}`. If you
have run several tools and `hits` is still 0, you are re-deriving instead of
reusing — check whether you are perturbing params you did not mean to.

## Provenance

The numbers above were measured after the SPICE-loop optimization landed
(sky130 corner-deck prune, deck memo cache, parallel sweeps). On an older build
sky130 was ~2.4x slower again and the sweeps were serial, so if measurements on
a given machine come back far above this table, check that the backend is
current rather than assuming the table is wrong. Re-measure with
`scripts/measure_tool_cost.sh`.

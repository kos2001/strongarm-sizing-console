---
name: analog-ic-robustness-optimization
description: "Use when building, extending, or debugging an open/ngspice-backed analog IC sizing, robustness, and yield optimization flow inspired by Cadence/MunEDA WiCkeD methodology. Covers FEO/DNO nominal sizing, WCO PVT worst-case, WCD high-sigma proxy, mismatch budgeting, importance sampling, YOP yield optimization, parameter screening, yield sweep, post-layout WCD, and worst-case corner extraction."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [semiconductor, eda, analog, custom-ic, sizing, yield, robustness, wicked, wcd, ngspice, optimization]
    related_skills: [ppa-closure-agent, software-delivery-lifecycle, research-intelligence-workflows]
---

# Analog IC Robustness Optimization

## Overview

This skill covers the class of work where you need to implement analog/custom IC
sizing, robustness analysis, and yield optimization using open tools (ngspice)
rather than commercial EDA licenses. The methodology is inspired by Cadence/MunEDA
WiCkeD — the industry-standard tool suite for circuit sizing, yield optimization,
and design centering — but implemented from public methodology descriptions, not
by replicating proprietary algorithms.

## When to Use

- Build or extend an ngspice-backed analog sizing tool with WiCkeD-like flows.
- Implement worst-case distance (WCD), yield optimization, or high-sigma analysis.
- Add FEO/DNO-style feasibility and nominal sizing refinement.
- Implement WCO (worst-case operation) PVT corner sweeps.
- Add mismatch budgeting across all device groups (not just input pair).
- Implement importance-sampled high-sigma yield estimation.
- Add parameter screening / sensitivity ranking for design variables.
- Implement yield sweep (yield vs global process variation).
- Add post-layout WCD re-evaluation with parasitic extraction.
- Expose analog optimization flows via HTTP API and MCP tools for agent access.

## WiCkeD Methodology Map

Public WiCkeD descriptions expose these tool concepts. Each maps to a practical
open implementation:

| WiCkeD Tool | Concept | Open Implementation |
|---|---|---|
| FEO | Feasibility analysis & optimization | Nominal ngspice run + spec margin check |
| DNO | Deterministic nominal optimization | Sensitivity-guided width moves (feasibility → sensitivity → constrained refine) |
| GNO | Global nominal optimization | Log-space Differential Evolution + GP surrogate (already in repo) |
| YOP | Yield optimization | Coordinate search maximizing WCD beta sigma |
| WCO | Worst-case operation | Enumerated PVT corner sweep (3 process × 3 temp × 3 VDD = 27) |
| WCD | Worst-case distance | Pelgrom offset beta + ngspice PVT boundary sampling/interpolation |
| Mismatch | Full-device mismatch budget | Weighted analytic contributors per device group |
| High-sigma | Importance sampling | Shifted Gaussian MC with likelihood reweighting |
| Screening | Parameter screening | Normalized OAT sensitivity ranking per metric |
| Yield plot | Yield vs process variation | Compact MC per process skew point |

## Architecture Pattern

The implementation lives in a single module (`wicked.py`) that wraps the existing
`run_sim.py` ngspice backend. No third-party packages required beyond what the
repo already uses.

```text
wicked.py
  ├── nominal_verdict()        # FEO: one ngspice run + spec margins
  ├── sensitivity()            # OAT width sensitivity for DNO
  ├── dno_refine()             # DNO: feasibility → sensitivity → constrained refine
  ├── robust_refine()          # WCO-in-loop: representative corners, strengthen devices
  ├── wco_operating()          # Full 27-corner PVT sweep
  ├── worst_case_distance()    # WCD: analytic offset + PVT boundary sampling
  ├── mismatch_budget()        # Full-device weighted mismatch contributors
  ├── importance_sampling_yield()  # Shifted MC with Gaussian likelihood reweighting
  ├── robust_optimize()        # Yield-aware coordinate search (WCO+WCD feedback)
  ├── parameter_screening()    # Normalized sensitivity ranking per metric
  ├── yield_sweep()            # Yield vs process skew (yield-plot style)
  ├── yop_optimize()           # YOP: maximize WCD beta via coordinate search
  ├── postlayout_wcd()         # WCD re-eval with layout-extracted parasitics
  ├── worst_case_corners()     # Ranked PVT corner diagnosis
  └── wicked_flow()            # 10-stage end-to-end pipeline
```

## Key Implementation Techniques

### WCD (Worst-Case Distance) Proxy

Combine two mechanisms:
1. **Analytic offset WCD**: `beta_offset = offset_limit / sigma_offset` where
   `sigma_offset = sqrt(2) * AVT / sqrt(W*L*M)` (Pelgrom).
2. **Simulation-backed PVT WCD**: sample standard-normal directions for process
   skew, VDD, and temperature; interpolate the boundary distance when
   decision-time crosses the target.

Reported `beta = min(all mechanisms)`. Estimated yield from normal CDF.

### Importance Sampling Proxy

1. Find WCD-limiting mechanism and direction.
2. Shift sampling distribution `N(mu, I)` toward failure region where
   `mu = beta * direction`.
3. Evaluate ngspice at each shifted sample.
4. Unbias with Gaussian likelihood ratio: `LR = exp(-mu·z + |mu|²/2)`.
5. `Pf = sum(LR * fail) / N`, `yield = 1 - Pf`.

### Full-Device Mismatch Budget

Input pair is simulated directly in SPICE. Other device groups (latch NMOS/PMOS,
tail, precharge) use weighted analytic contributors:
`contrib_k = weight_k * AVT / sqrt(W_k * L_k * M_k)`.

Weights reflect input-referred contribution strength:
input=sqrt(2), ncc=0.35, pcc=0.30, tail=0.18, pre=0.08.

### YOP Yield Optimization

Coordinate search where the objective is to maximize WCD beta:
1. For each device group, try width up (1.15×) and down (0.90×).
2. Evaluate WCD beta for each candidate.
3. Select the candidate with highest beta.
4. Repeat until "hold" wins or iteration budget exhausted.

## Integration Pattern

### HTTP API

Add endpoints under `/api/wicked/` in the existing stdlib HTTP server:
- `POST /api/wicked/dno` — DNO refinement
- `POST /api/wicked/wcd` — WCD/high-sigma proxy
- `POST /api/wicked/mismatch` — mismatch budget
- `POST /api/wicked/importance` — importance sampling
- `POST /api/wicked/optimize` — robust optimizer
- `POST /api/wicked/screening` — parameter screening
- `POST /api/wicked/yieldsweep` — yield sweep
- `POST /api/wicked/yop` — YOP yield optimization
- `POST /api/wicked/postlayout` — post-layout WCD
- `POST /api/wicked/corners` — worst-case corner extraction
- `POST /api/wicked/fullflow` — 10-stage end-to-end pipeline

### MCP Tools

Register in `mcp_server.py` with `_TOOL_ENDPOINT` proxy mapping:
- `strongarm_wicked` → `/api/wicked/fullflow`
- `strongarm_wicked_importance` → `/api/wicked/importance`
- `strongarm_wicked_optimize` → `/api/wicked/optimize`
- `strongarm_wicked_screening` → `/api/wicked/screening`
- `strongarm_wicked_yieldsweep` → `/api/wicked/yieldsweep`
- `strongarm_wicked_yop` → `/api/wicked/yop`
- `strongarm_wicked_postlayout` → `/api/wicked/postlayout`
- `strongarm_wicked_corners` → `/api/wicked/corners`

## Wicked Flow Stages (10-stage pipeline)

1. FEO feasibility check
2. DNO sensitivity-guided nominal refinement
3. WCO-in-loop robust refinement (representative corners)
4. WCO PVT worst-case operation (full 27-corner sweep)
5. WCD high-sigma/yield proxy
6. Full-device mismatch budget
7. Importance-sampled high-sigma check
8. Parameter screening
9. Worst-case corner extraction
10. Post-layout WCD re-evaluation

## Common Pitfalls

1. **Claiming commercial WiCkeD equivalence.** Always state "WiCkeD-inspired
   open flow" — the WCD is a practical proxy, not the proprietary algorithm.

2. **Only modeling input-pair mismatch in SPICE.** Latch/tail/precharge mismatch
   matters; use weighted analytic contributors even if SPICE injection is limited
   to the input pair.

3. **WCO failure on SS/cold/lowV corners.** The default StrongARM sizing may fail
   at SS/-40°C/0.9V. Don't hide this — report `overall: false` honestly.

4. **Pyright None-comparison on ngspice outputs.** `dec_ps` from `_parse()` can be
   `None`. Guard with `dec_ps is not None and dec_ps > target` — never bare `>`.

5. **Importance sampling with zero PVT shift.** When the limiting mechanism is
   offset (not PVT), `direction = [0,0,0]` and `mu = [0,0,0]`. The likelihood
   ratio becomes 1.0 (degenerate but correct — it falls back to plain MC).

6. **Post-layout WCD with no parasitic delta.** If the layout proxy's extracted
   caps are very small, `beta_delta ≈ 0`. This is correct, not a bug.

7. **Long verification runs.** The full wicked_flow with importance sampling and
   post-layout WCD can take several minutes. Use `background=true` with
   `notify_on_complete=true` for verification runs exceeding 60s.

8. **MCP `devices` parameter silently dropped.** The `strongarm_run_sim` (and
   likely other `strongarm_*`) MCP tool has `devices` typed as
   `{"properties": {}, "type": "object"}` — no nested properties declared. The
   MCP framework serializes this as an empty `{}` regardless of what you pass,
   so every sim runs with DEFAULT_PARAMS instead of your sizing. Symptom: the
   `params.devices` in the result never matches your input. Fix: call
   `run_sim.run_sim(params, do_offset=True)` directly via terminal Python from
   the repo directory (`/Users/kos2001/gitspace/ip-dev-fde/strongarm_sim`).
   Example:
   ```bash
   cd /Users/kos2001/gitspace/ip-dev-fde/strongarm_sim && python3 -c "
   import json, run_sim
   params = {'vdd':0.7,'cload_ff':15,'avt_mv_um':2,'n_mc':16,'model':'ptm',
     'devices':{'input':{'w_um':10,'l_nm':80,'m':4},'tail':{'w_um':12,'l_nm':45,'m':6},
                'ncc':{'w_um':4,'l_nm':45,'m':2},'pcc':{'w_um':9,'l_nm':45,'m':4},
                'pre':{'w_um':4,'l_nm':45,'m':2}}}
   r = run_sim.run_sim(params, do_offset=True)
   print(json.dumps(r, indent=2))"
   ```
   Always check that `result.params.devices` matches your input before trusting
   the numbers. If it doesn't, the MCP proxy dropped your params — fall back to
   direct Python.

## Server Deployment Pattern (launchd)

When the analog sizing console runs as a launchd service (e.g.
`com.strongarm.sizingconsole.plist`), restarting the Python process directly
with `kill` causes launchd to auto-respawn it within seconds — the new process
picks up the old code because launchd cached the plist. The correct restart
sequence is:

```bash
launchctl unload ~/Library/LaunchAgents/com.strongarm.sizingconsole.plist
sleep 2  # let the old process die
launchctl load ~/Library/LaunchAgents/com.strongarm.sizingconsole.plist
sleep 2  # let the new process bind
curl -s http://127.0.0.1:8770/api/health  # verify
```

After restart, smoke-test at least one new endpoint (e.g.
`POST /api/wicked/mismatch`) to confirm the server loaded the updated module.

If another process occupies the port (launchd respawn loop), find ALL pids with
`lsof -ti :8770` and `ps aux | grep server.py`, then `launchctl unload` first
before killing residual processes.

## Verification Pattern

Use the ad-hoc verification script pattern from `software-delivery-lifecycle`:
create a `hermes-verify-*.py` tempfile under the system temp dir, py_compile all
changed files, import and exercise each new function with deterministic inputs,
assert key invariants, then clean up. Report as ad-hoc verification, not suite
green.

**Timeout handling**: when the verification script calls ngspice (each sim takes
~20-25s and the full flow can run 10+ sims), the script may exceed the 600s
foreground limit. Use `background=true` with `notify_on_complete=true`, then
`process(action='wait', session_id=..., timeout=60)` to poll. The 60s wait limit
is enough because the background process finishes in 2-5 minutes for a minimal
smoke config (dno_iterations=1, wcd_samples=2, importance_samples=2).

Key assertions to check:
- `mismatch_budget` returns all device groups with positive sigma
- `worst_case_distance` returns positive beta and 0-100% yield
- `importance_sampling_yield` returns n samples and 0-100% yield
- `parameter_screening` ranks all devices and is sorted descending
- `worst_case_corners` returns 27 corners and top-5
- `yop_optimize` returns positive final beta
- `postlayout_wcd` has pre/post WCD and par_caps
- `wicked_flow` has all 10 stage names

## Research Sources

See `references/wicked-methodology-research.md` for the compiled public WiCkeD
methodology research: tool descriptions, WCD formalism, MunEDA acquisition by
Cadence, high-sigma/importance sampling approaches, and key papers.

## Relationship to Other Skills

- `ppa-closure-agent`: covers backend/physical-design PPA closure (digital). This
  skill covers analog/custom IC sizing and yield (the other half of the EDA flow).
- `software-delivery-lifecycle`: provides the ad-hoc verification pattern used
  for this class of work.
- `research-intelligence-workflows`: provides the research methodology used to
  gather public WiCkeD information before implementation.

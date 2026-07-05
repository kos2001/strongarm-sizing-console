# StrongARM Comparator — Agent-Driven Sizing Backend (Method 1)

Programmatic SPICE backend that lets an agent close the sizing loop for a
StrongARM latch comparator: **simulate → evaluate → adjust → repeat**, against
real ngspice.

## Files

| File | Purpose |
|------|---------|
| `run_sim.py` | Core `run_sim(params) → measurements` wrapper. Generates a parameterized StrongARM netlist, runs ngspice in batch, returns JSON metrics. CLI + importable. |
| `vco_sim.py` | MOSFET **current-starved ring VCO** backend, sharing the same ngspice plumbing: `measure_vco` (osc. frequency / power / does-it-oscillate), `vco_tuning` (f vs V_ctrl → range, Kvco). Same simulate→evaluate→optimize loop as the comparator. |
| `mcp_server.py` | Minimal dependency-free MCP stdio server exposing `run_sim` as a native tool (`strongarm_run_sim`) for future-session agents. |
| `models/ptm_45nm_bulk.txt` | Real BSIM4 (level=54) device model — PTM 45 nm bulk (`nmos`/`pmos`). |
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
    "input": {"w_um": 8.0, "l_nm": 80.0, "m": 4},
    "tail":  {"w_um": 12.0,"l_nm": 40.0, "m": 6},
    "ncc":   {"w_um": 4.0, "l_nm": 40.0, "m": 2},
    "pcc":   {"w_um": 9.0, "l_nm": 40.0, "m": 4},
    "pre":   {"w_um": 4.0, "l_nm": 30.0, "m": 2}
  }
}
```

`input` = differential pair · `tail` = tail switch · `ncc`/`pcc` = cross-coupled
NMOS/PMOS latch · `pre` = precharge PMOS.

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

The whole console is registered as a hermes-agent MCP server (`mcp_server.py`,
`strongarm-sim`) so it is callable through the OpenAI-compatible **api_server**
(and the hermes-gateway front, model alias `ai-fde`). It exposes **5 tools**:
`strongarm_run_sim` (direct ngspice eval of a sizing), and `strongarm_optimize`
(DE + GP-surrogate auto-size), `strongarm_pareto` (NSGA-II front), `strongarm_pvt`
(27-corner sign-off), `strongarm_fullflow` (end-to-end sign-off) — the latter four
proxy to the running backend at `$STRONGARM_API` (default `:8770`). A client can
ask the agent to "size / sign off a StrongARM comparator" and it drives the flow.

Registered via:

```sh
hermes mcp add strongarm-sim --command python3 \
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

## Extension points (documented, not stubbed)

- **Transient noise** → add ngspice `.noise`/transient-noise and report
  input-referred µVrms.
- **Full-device mismatch offset** → inject Vth mismatch into latch/tail devices
  (per-instance model cards) so second-order offset contributions are captured.
- **PVT corners** → loop the `.lib` corner and temperature; report worst case.

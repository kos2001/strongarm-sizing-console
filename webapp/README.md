# StrongARM Sizing Console — frontend

A modern web console for the `run_sim` SPICE backend: edit transistor sizing,
run ngspice, and see decision time / power / offset σ against the P1 spec.

**Stack:** React 19 · Vite 8 · TypeScript · Tailwind CSS v4. Backend bridge is a
dependency-free Python stdlib server wrapping `../run_sim.py`.

## Run it

### Recommended — single origin, no flicker

```sh
cd strongarm_sim/webapp
npm run build             # produces dist/
npm run server            # = python3 server.py  (serves dist/ + /api on :8770)
```

Open **http://127.0.0.1:8770**. The backend serves the built app and the API on
one origin — no Vite, no HMR websocket, so it cannot reload-loop/flicker.

### Run as a service (launchd — auto-start + auto-restart)

`com.strongarm.sizingconsole.plist` is a macOS LaunchAgent that starts the
backend at login and restarts it if it dies (`KeepAlive`). Install:

```sh
cp strongarm_sim/webapp/com.strongarm.sizingconsole.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.strongarm.sizingconsole.plist
```

Then open http://127.0.0.1:8770 — it stays up across crashes and logins.

| Action | Command |
|--------|---------|
| status | `launchctl list \| grep strongarm` |
| restart | `launchctl kickstart -k gui/$(id -u)/com.strongarm.sizingconsole` |
| stop / uninstall | `launchctl bootout gui/$(id -u)/com.strongarm.sizingconsole` |
| logs | `/tmp/strongarm-sizing.out.log`, `/tmp/strongarm-sizing.err.log` |

(Build `dist/` first with `npm run build` so the service serves the latest UI;
re-run build + `kickstart -k` after UI changes.)

### Development (hot reload)

```sh
npm run server            # SPICE bridge on :8770
npm run dev               # Vite on :5199, proxies /api -> :8770
```

Open http://localhost:5199 (use `localhost`, not a LAN IP — the Vite HMR
websocket must reach the dev server, or the page will reload-loop). The header
shows **backend live** when the bridge is reachable.

> Flicker note: the app applies its theme before first paint (inline script in
> `index.html`), so there's no dark→light flash. If you still see flickering in
> dev, it's the Vite HMR client failing to connect over a non-`localhost` host —
> use the single-origin build above (:8770), which has no HMR at all.

## Build

```sh
npm run build     # -> dist/  (static, then serve dist/ behind any /api proxy)
```

## Tests

`strongarm_sim/tests/` holds a pytest regression suite (SPICE integration
tests — auto-skipped if ngspice is missing): backend functional/verdict/noise,
metastability τ, layout DRC + parasitic extraction, BER monotonicity,
sensitivity coverage, and optimizer convergence.

```sh
cd strongarm_sim && python3 -m pytest tests/ -q      # ~2 min (runs real ngspice)
```

## What it does

- **Device editor** — W (µm) / L (nm) / M for the input pair, tail, latch
  N/P, and precharge devices; plus VDD, C_load, n_MC.
- **Presets** — `PTM seed`, `Under-sized` (fails offset), `Tuned pass`.
- **Run SPICE** — POSTs the sizing to `/api/simulate`; the bridge runs ngspice
  (transient + Monte-Carlo offset) and returns measured metrics.
- **Circuit & transient** — a **transistor-level StrongARM schematic** (SVG MOS
  symbols: tail → input pair → cross-coupled NMOS/PMOS latch → precharge, gate
  bubbles on PMOS) annotated with the current W×M per device, next to the **real
  ngspice transient** (`/api/waveform` → ngspice `wrdata` of V(clk)/V(outp)/
  V(outn)) showing the outputs precharge to VDD and split to the rails, with
  clk-edge and decision markers. It refreshes on every Run SPICE / Auto-find (or
  the ↻ button). After Auto-find the chart **overlays the before (faint dashed)
  and after (solid) transients** so the pre/post-optimization behaviour compares
  on one axis. During Auto-find the schematic **replays the search step by step**
  (auto-advance + click any trajectory row to scrub), highlighting the device
  whose W just changed and showing that step's ΣW / decision / power.
- **Monte-Carlo offset** — when a run measures offset, a panel plots the sample
  distribution: histogram + individual sample dots (rug) + mean + ±σ band + the
  ±spec limits, so the offset σ is shown as the spread of per-draw offsets
  (each = one random Vth-mismatch draw whose decision-flipping input is found by
  bisection). A **fitted normal curve** (measured mean/σ) overlays the histogram
  so the distribution reads clearly even at low n_MC, and after Auto-find the
  **measured before-optimization distribution** (a real MC on the starting
  design — faint outlined bars + dashed curve) is overlaid on the after, so you
  see how sizing shifted the offset spread (e.g. seed σ 1.85 mV → optimized
  σ 2.77 mV). Raise n_MC for a denser histogram.
- **Auto-find W & M** — a global **log-space Differential Evolution** search
  (`/api/optimize`) that **minimizes power** subject to offset + decision-time +
  functional constraints (penalty method) over all five device widths. Offset is
  the analytic Pelgrom prediction (free); decision/power/functionality come from
  one fast ngspice transient per candidate; the winner is confirmed with a
  Monte-Carlo offset run. A **Gaussian-process surrogate** (scikit-learn) fitted
  on evaluated points pre-screens clearly-worse candidates so SPICE is skipped
  for them (~30% fewer calls). The best-of-generation history is the trajectory
  the Optimizer page replays. On the P1 targets it finds ~48 µW (all three specs
  pass) — a better basin than the earlier greedy descent.
- **⚡ parasitics** (Circuit page, `/api/postlayout`) — an estimated
  post-extraction re-sim: routing/junction C (~0.25 fF/µm of connected width) is
  added at outp/outn/nX/nY and the transient re-run, overlaid against the
  schematic so you see the regeneration slowdown (e.g. 181 → 190 ps).
- **SKY130 (real)** — a model toggle on the Sizing page switches `run_sim`
  between the generic PTM 45 nm `.model` and the **real SkyWater SKY130** ngspice
  `.lib` (open_pdks, `~/pdk/...`; env `SKY130_NGSPICE_LIB`) with subckt devices
  at 1.8 V / L≥0.15 µm. Real-silicon numbers instead of the PTM stand-in.
- **Pareto** (Pareto page, `/api/pareto`) — **NSGA-II** multi-objective search
  mapping the power ↔ decision-time trade-off; plots the non-dominated front vs
  all evaluated designs with the spec box, and each front point is loadable.
- **Layout** (Layout page, `/api/layout`) — transistor-level GDSII synthesis
  from the sizing (`layout.py`, gdstk): multi-finger MOS (diffusion + poly
  fingers + met1 straps), PMOS nwell, substrate guard ring on SKY130 stream
  layers, with an SVG viewer, cell area, a rule DRC (met1/poly min width + met1
  spacing), and a real `.gds` (opens in KLayout/Magic). PoC layout, not sign-off
  DRC. Needs `pip install gdstk`; KLayout (`brew install --cask klayout`) opens
  the GDS.
- **Full flow** (Full flow page, `/api/fullflow`) — chains the native stages
  end-to-end: DE+GP sizing → MC offset confirm → post-layout parasitic re-sim →
  PVT sign-off → **GDSII layout + rule DRC**, with a per-stage verdict, overall
  SIGNED-OFF / NOT-CLEAN, and the final layout rendered inline.
- **PVT corners** (PVT page, `/api/pvt`) — worst-case sign-off across 27 corners:
  process SS/TT/FF (±50 mV Vth skew via BSIM4 `delvto`) × temperature
  −40/27/125 °C (`.option temp`) × voltage 0.9/1.0/1.1×VDD. Shows a colored
  corner grid + worst-case decision/power vs the P1 targets — nominal-passing
  sizings often miss at the slow-cold-low-V corner. All 27 corners run in
  parallel (`ThreadPoolExecutor`; ngspice is a subprocess so it releases the
  GIL) — ~0.9 s instead of serial. DE/NSGA-II/full-flow are parallelized too.
- **Metastability** (Metastability page, `/api/metastability`) — decision time
  vs input differential amplitude on a log axis. As V<sub>in</sub> → 0 the
  regeneration time diverges as τ·ln(1/V<sub>in</sub>); fitting the slope recovers
  the regeneration time constant τ = C/g<sub>m,latch</sub> (seed ≈ 26 ps). The
  defining StrongARM characterization curve.
- **Max f_clk** (Max f_clk page, `/api/maxfclk`) — sweeps the clock period and
  finds the shortest one where the comparator both resolves in the evaluate
  phase and precharges back within reset; reports the maximum usable clock rate
  and the energy per conversion (avg supply power × period) at that rate — the
  comparator FoM (seed ≈ 2 GHz / ~0.8 pJ).
- **Sensitivity** (Sensitivity page, `/api/sensitivity`) — one-at-a-time ±10 % W
  perturbation of each device, showing Δ{decision, power, offset} as a tornado
  (widest bar = strongest lever). Decision/power from ngspice, offset from the
  analytic Pelgrom prediction. Guides manual tuning — the input pair dominates
  both speed and offset.
- **Noise / BER** (Noise / BER page, `/api/ber`) — input-referred noise and the
  decision error rate vs input amplitude. σ<sub>vn</sub> is a first-order
  estimate from the input-pair transconductance (finite-difference g<sub>m</sub>,
  σ = √(2·γ·kT/(g<sub>m</sub>·t<sub>int</sub>))); the BER curve is
  0.5·erfc(V<sub>in</sub>/√2σ) on that noise plus the Monte-Carlo offset
  (σ<sub>tot</sub> = √(σ<sub>vn</sub>²+σ<sub>os</sub>²)). Analytic on measured σ —
  ngspice `trnoise` works but the NA→physical-density mapping is model-dependent,
  so the measured σ is used instead. Offset dominates the minimum detectable
  input (~5 mV) over noise (~0.2 mV).
- **Yield** (Yield page, `/api/yield`) — parametric yield: a Monte-Carlo over
  input-pair Vth mismatch **and** a random PVT operating point (process skew /
  temp / VDD). A chip passes if it resolves correctly, meets the decision target
  at its corner, and its offset is within spec. Reports yield %, the dominant
  failure mode, and a sample scatter with the spec box — the production metric
  that couples mismatch and process variation into one number.
- **Spec gauges + profiles** — decision time, power, offset σ, and input noise,
  each with a target marker and PASS/FAIL verdict. Pick a **spec profile**
  (P1 SAR-ADC / P2 high-speed / P3 low-power) or edit any target limit inline;
  the gauges, PVT/Pareto/Monte-Carlo/yield thresholds, and the optimizer targets
  all follow the current selection.
- **Report export** — the sidebar **⤓ report** button downloads a Markdown
  report (device table, spec verdicts, and whichever of metastability / BER /
  PVT / sensitivity / f_clk / yield / Pareto have been run, plus the raw JSON)
  for design records.
- **Bilingual + beginner help** — a 🌐 KO/EN language toggle (sidebar) switches
  the nav, page titles, device roles, and chrome between Korean and English.
  Every page opens with a collapsible 💡 "What is this?" card explaining, in
  plain language, what the page does and how to read its result — aimed at
  newcomers to analog/comparator design (strings in `src/i18n.ts`).
- **Run history** — every run is logged; click a row to reload its sizing.
- **Offset toggle** — off ≈ fast (speed/power only); on ≈ 20 s (adds the
  Monte-Carlo offset sweep).

Notes: the model is BSIM4 PTM 45 nm bulk, so at VDD 1.0 V the seed sizing draws
~260 µW — over the 28 nm-derived 100 µW target, which is exactly the kind of
miss the console is for. Files: `server.py` (bridge), `src/` (app),
`vite.config.ts` (dev proxy).

# WiCkeD Methodology Research

Compiled from public sources during the session that built `wicked.py`.
This is a knowledge bank, not a full mirror of upstream docs.

## What is WiCkeD?

WiCkeD is the flagship tool suite of MunEDA GmbH (Munich, Germany), acquired by
Cadence Design Systems on 2024-05-16 (add-on acquisition). It is the industry
standard for analog/custom IC sizing, yield optimization, and design centering.

Name origin: **Wi**rst **C**ase **D**istance — the core algorithm finds the
shortest statistical distance from the nominal design point to the performance
specification boundary in the space of statistical (mismatch/process) and
operating (PVT) parameters.

## Tool Suite Components

### Circuit Sizing & Optimization

| Tool | Full Name | Description |
|---|---|---|
| FEO | Feasibility Analysis & Optimization | Defines/analyzes circuit functionality based on electrical, layout, area constraints. Auto-parametrizes and fulfills them. |
| DNO | Deterministic Nominal Optimization | Sensitivity-based circuit optimization for nominal (typical) case and worst-case operating corners. |
| GNO | Global Nominal Optimization | Statistical/stochastic optimization based on sampling and design-space exploration. |
| YOP | Yield Optimization | Automated circuit yield and robustness optimization for high sigma and performance margins. Based on worst-case distance and sigma measures. |
| REL | Reliability Option | Considers reliability models and constraints for aging, degradation, area, stress. |

### Circuit Analysis & Verification

| Feature | Description |
|---|---|
| Sensitivity Analysis | Per-performance sensitivity to design parameters |
| PVT & Operating Corner Analysis | Fast corner-case influence evaluation |
| Parameter Screening | Identify which parameters matter most |
| Monte Carlo Analysis (3-5 sigma) | Fast enhanced MC |
| High Sigma Worst Case Analysis (6-9 sigma) | Simulation-true worst-case analysis |
| Importance Sampling & Robustness Verification | For ultra-high sigma (6-12+ sigma) |
| Global/local variation and yield analysis | Separates process and mismatch variation |
| Reliability & aging analysis | Degradation effects |
| Yield plot sweeps for global variation | Yield vs process parameter |

### Circuit Porting & Migration

| Tool | Description |
|---|---|
| SPT | Schematic Porting Tool — migrate schematics between PDKs/nodes |

## Worst-Case Distance (WCD) Formalism

From the foundational paper (Antreich et al., IEEE TCAD, 2002, cited 254+):

- Statistical parameters `x_S` (mismatch, process) are normally distributed.
- Operating parameters `x_O` (temp, VDD, load) vary over a defined range.
- Design parameters `x_D` (W, L, R, C) are what the designer tunes.
- For each performance `f_i`, the worst-case value `f_i^w(x_S)` is found over
  operating parameters.
- The acceptance region is defined by `f_i(x_S) >= f_i^spec`.
- WCD `β_i` is the minimum distance from the nominal point to the spec boundary
  in the normalized statistical parameter space.
- Yield ≈ Φ(β) where Φ is the standard normal CDF.
- The limiting mechanism is the one with the smallest β.

Key insight: WCD extends beyond simple sigma counting by handling non-normal
distributions, multiple interdependent specs, and operating parameter ranges.

## MunEDA Acquisition by Cadence

- Date: 2024-05-16
- Deal type: Add-on acquisition (Cadence's 11th semiconductor sector deal)
- Target: MunEDA GmbH, Unterhaching (near Munich), Germany
- Integration: MunEDA team/tech merged into Cadence Custom IC Design business unit
- Post-acquisition: WiCkeD integrated into Virtuoso Studio; license tier in
  Virtuoso ADE Artist (IC25.1) enables WiCkeD usage

Source: Mergr (mergr.com/transaction/cadence-acquires-muneda)

## High-Sigma Analysis Approaches

From DATE 2019 paper (Weller et al., KIT):

- Brute-force MC is infeasible for rare events (6+ sigma requires 10^6+ samples).
- Importance Sampling (IS): shift sampling distribution toward failure region,
  evaluate, then unbias with likelihood ratio.
- Bayesian Optimization-based IS (BOIS): use BO surrogate to find optimal shift.
- Convergence rate ρ = sqrt(Var(P̂_f)) / P̂_f measures MC efficiency.
- Key concern: shifting distribution may overlook other failure regions.

Solido (now Siemens): HSMC (High-Sigma Monte Carlo) — uses sequential testing
and worst-case distance methods. Claims 10,000,000× speedup for ultra-high sigma.

## MunEDA Customer Cases (from public MUGM presentations)

### STMicroelectronics (28nm DDRx I/O)
- Task: Reduce jitter and duty cycle
- Manual tuning: 2 weeks → MunEDA: 3 hours
- Corner spread reduced by 50%

### Faraday (standard cells)
- Batch-mode optimization of clock buffers
- Balance slopes across cell/process variants
- Complete automation, equal/better than manual

### Top microprocessor company (65nm RF receiver)
- 2000 MOS, 8000 parasitics, 40min/simulation
- 80 specs, 50 design parameters
- Power significantly reduced, automated

### Evatronix (IP porting)
- WiCkeD IP Porting and Verification Flow
- Fast analog IP migration to new process technologies
- Documented robustness verification

## PVT Corner vs Process MC Trade-offs

From MunEDA MOS-AK 2013 presentation:

| Aspect | Corners | Process MC |
|---|---|---|
| Simulation effort (pure CMOS) | Low | Medium |
| Simulation effort (many device types) | High | Medium |
| Timing for full-custom digital | Yes | No |
| Correct device correlation | No | Yes |
| Analog performance variability | No | Yes |
| Estimate yield | No | Yes |
| Process parameter sensitivities | No | Yes |

Key insight: For analog features (Cgs, Gain), corner spread can differ from
global MC by >30-80%. WiCkeD WCO handles continuous operating parameters
together with corners; MCA can vary process parameters even when corners
are defined.

## Open Implementation Notes

When implementing WiCkeD-inspired flows with ngspice:
- Only input-pair Vth mismatch can be directly injected via `dvth1`/`dvth2`
  in the netlist. Other device groups need weighted analytic contributors.
- Process variation is modeled as `pskew` (Vth shift) for PTM models, or as
  PDK corner names (ss/tt/ff) for SKY130.
- The layout parasitic proxy uses drawn geometry × areal/fringe cap densities,
  not sign-off extraction.
- Importance sampling is a practical proxy with small N (2-24), not a
  production high-sigma sign-off.

## Key References

1. Antreich, K.J., et al. "Circuit Analysis and Optimization Driven by Worst-Case
   Distances." IEEE TCAD, 2002. (Foundational WCD paper)
2. Graeb, H. "Analog Design Centering and Sizing." Springer, 2007. (Book)
3. Weller, D., et al. "Bayesian Optimized Importance Sampling for High Sigma
   Failure Rate Estimation." DATE 2019.
4. Cadence Community Blog: "A Deep Dive into AI-Driven Optimization with WiCkeD"
   (2025-06-30)
5. SemiWiki: "Analog Circuit Migration and Optimization" (MUGM 2023 report)
6. MunEDA MOS-AK Munich 2013: "Circuit Sizing w/ Corner Models"
7. FTD Solutions: MunEDA WiCkeD tool suite overview
8. IC Infra (icinfra.cn): Cadence Wicked schematic porting guide
9. Wikipedia: "Worst-case distance"
10. TUM EDA course: "Simulation and Optimization of Analog Circuits"

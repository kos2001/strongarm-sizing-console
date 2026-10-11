import { SPEC_PROFILES, TARGET_KEYS, TARGET_META, comparatorMeasurements, type TargetKey, type Targets } from './comparator.ts'
import { DEVICE_META } from './types.ts'
import type { DeviceKey, Params, SimResult, MetastabilityResult, BerResult, MaxFclkResult, YieldResult, PvtResult, SensitivityResult, ParetoResult } from './types'

export interface ComparatorReport {
  params: Params
  targets: Targets
  profile: string
  result: SimResult | null
  metaRes?: MetastabilityResult | null
  berRes?: BerResult | null
  fclkRes?: MaxFclkResult | null
  yieldRes?: YieldResult | null
  pvtRes?: PvtResult | null
  sensRes?: SensitivityResult | null
  paretoRes?: ParetoResult | null
}

export function createComparatorReport({ params, targets, profile, result, metaRes, berRes, fclkRes, yieldRes, pvtRes, sensRes, paretoRes }: ComparatorReport, ts = new Date().toISOString()) {
  const measured = comparatorMeasurements(result)
  const pf = profile === 'custom' ? 'custom' : SPEC_PROFILES.find((p) => p.id === profile)?.label
  const fmt = (v: number | null | undefined, u: string) => (v == null ? '—' : `${v} ${u}`)
  const verdict = (k: TargetKey) => (measured[k] == null ? '—' : measured[k]! <= targets[k] ? 'PASS' : 'FAIL')
  const dev = params.devices
  const lines: string[] = [
    `# StrongARM comparator sizing report`,
    ``,
    `- Generated: ${ts}`,
    `- Model: ${params.model === 'sky130' ? 'SkyWater SKY130 (real)' : 'PTM 45nm bulk'}`,
    `- VDD: ${params.vdd} V · C_load: ${params.cload_ff} fF · n_MC: ${params.n_mc}`,
    `- Spec profile: ${pf}`,
    ``,
    `## Device sizing`,
    ``,
    `| Device | W (µm) | L (nm) | M |`,
    `|--------|-------:|-------:|--:|`,
    ...(Object.keys(dev) as DeviceKey[]).map((k) => `| ${DEVICE_META[k].name} (${k}) | ${dev[k].w_um} | ${dev[k].l_nm} | ${dev[k].m} |`),
    ``,
    `## Spec compliance`,
    ``,
    `| Metric | Measured | Target | Verdict |`,
    `|--------|---------:|-------:|:-------:|`,
    ...TARGET_KEYS.map((k) => `| ${TARGET_META[k].label} | ${fmt(measured[k], TARGET_META[k].unit)} | ≤ ${targets[k]} ${TARGET_META[k].unit} | ${verdict(k)} |`),
  ]
  if (metaRes) lines.push(``, `## Metastability`, ``, `- Regeneration τ: ${fmt(metaRes.tau_ps, 'ps')}`, `- Min resolved input: ${metaRes.min_resolved_v != null ? (metaRes.min_resolved_v * 1e6).toFixed(1) + ' µV' : '—'}`)
  if (berRes) lines.push(``, `## Noise / BER`, ``, `- Input-referred noise σ: ${berRes.noise_uv_rms} µV`, `- Offset σ: ${fmt(berRes.offset_sigma_mv, 'mV')}`, `- Min detectable input @ BER ${berRes.ber_target}: ${berRes.min_input_total_uv} µV (with offset), ${berRes.min_input_noise_uv} µV (noise only)`)
  if (fclkRes) lines.push(``, `## Max clock rate`, ``, `- Max f_clk: ${fclkRes.max_fclk_ghz != null ? fclkRes.max_fclk_ghz + ' GHz' : 'none'} (min period ${fmt(fclkRes.min_period_ns, 'ns')})`, `- Energy / conversion: ${fmt(fclkRes.energy_fj_at_max, 'fJ')}`)
  if (yieldRes) lines.push(``, `## Parametric yield`, ``, `- Yield: ${yieldRes.yield_pct}% (${yieldRes.pass}/${yieldRes.n}, mismatch × PVT)`, `- Fails — offset ${yieldRes.fail_breakdown.offset}, speed ${yieldRes.fail_breakdown.speed}, wrong ${yieldRes.fail_breakdown.decision_wrong}`)
  if (pvtRes) lines.push(``, `## PVT sign-off (45 corners)`, ``, `- Worst decision: ${fmt(pvtRes.worst.decision_time_ps, 'ps')}`, `- Worst power: ${fmt(pvtRes.worst.power_uw, 'µW')}`, `- All corners resolve: ${pvtRes.worst.any_nonfunctional ? 'NO' : 'yes'}`)
  if (sensRes) lines.push(``, `## Sensitivity (±${sensRes.delta_pct}% W)`, ``, ...sensRes.devices.map((d) => `- ${DEVICE_META[d.key].name}: decision ${d.low.decision_time_ps}→${d.high.decision_time_ps} ps, offset ${d.low.offset_sigma_mv}→${d.high.offset_sigma_mv} mV`))
  if (paretoRes) lines.push(``, `## Pareto front`, ``, `- ${paretoRes.front.length} non-dominated designs (power ↔ decision-time)`)
  lines.push(``, `---`, ``, `<details><summary>Raw JSON</summary>`, ``, '```json', JSON.stringify({ params, targets, result, metaRes, berRes, sensRes, fclkRes, yieldRes, pvtRes: pvtRes?.worst, generated: ts }, null, 2), '```', ``, `</details>`, ``)
  return lines.join('\n')
}

export function downloadComparatorReport(input: ComparatorReport) {
  const ts = new Date().toISOString()
  const blob = new Blob([createComparatorReport(input, ts)], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `strongarm-report-${ts.slice(0, 19).replace(/[:T]/g, '')}.md`
  a.click()
  URL.revokeObjectURL(url)
}

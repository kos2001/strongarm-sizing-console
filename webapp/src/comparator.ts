import type { Params, SimResult } from './types'

// metric metadata is fixed; the *limits* are editable (see spec profiles below)
export type TargetKey = 'decision_time_ps' | 'power_uw' | 'offset_sigma_mv' | 'noise_uv_rms'
export const TARGET_KEYS: TargetKey[] = ['decision_time_ps', 'power_uw', 'offset_sigma_mv', 'noise_uv_rms']
export const TARGET_META: Record<TargetKey, { unit: string; label: string; step: number }> = {
  decision_time_ps: { unit: 'ps', label: 'Decision time', step: 10 },
  power_uw: { unit: 'µW', label: 'Power', step: 5 },
  offset_sigma_mv: { unit: 'mV', label: 'Offset σ', step: 0.5 },
  noise_uv_rms: { unit: 'µV', label: 'Input noise', step: 10 },
}
export type Targets = Record<TargetKey, number>
// application-driven spec profiles; pick one, then fine-tune any limit inline
export const SPEC_PROFILES: { id: string; label: string; note: string; targets: Targets }[] = [
  { id: 'P1', label: 'P1 · SAR-ADC', note: '10-bit SAR comparator (balanced)', targets: { decision_time_ps: 400, power_uw: 100, offset_sigma_mv: 5, noise_uv_rms: 250 } },
  { id: 'P2', label: 'P2 · High-speed', note: 'fast link RX, offset-relaxed', targets: { decision_time_ps: 150, power_uw: 300, offset_sigma_mv: 10, noise_uv_rms: 400 } },
  { id: 'P3', label: 'P3 · Low-power', note: 'sensor front-end, precise + quiet', targets: { decision_time_ps: 800, power_uw: 40, offset_sigma_mv: 3, noise_uv_rms: 150 } },
]

export const DEFAULTS: Params = {
  vdd: 0.7,
  cload_ff: 15.0,
  avt_mv_um: 2.0,
  n_mc: 16,
  devices: {
    input: { w_um: 8.0, l_nm: 80.0, m: 4 },
    tail: { w_um: 12.0, l_nm: 45.0, m: 6 },
    ncc: { w_um: 4.0, l_nm: 45.0, m: 2 },
    pcc: { w_um: 9.0, l_nm: 45.0, m: 4 },
    pre: { w_um: 4.0, l_nm: 45.0, m: 2 },    // S3/S4 — 출력 X·Y 프리차지
    prei: { w_um: 4.0, l_nm: 45.0, m: 2 },   // S1/S2 — 내부 P·Q 프리차지
  },
}

export const PRESETS: { name: string; note: string; patch: (p: Params) => Params }[] = [
  { name: 'PTM seed', note: 'baseline P1 sizing', patch: () => structuredClone(DEFAULTS) },
  {
    name: 'Under-sized',
    note: 'fails offset spec',
    patch: (p) => ({ ...structuredClone(p), devices: { ...structuredClone(p.devices), input: { w_um: 2.0, l_nm: 45, m: 2 }, tail: { w_um: 3.0, l_nm: 45, m: 2 } } }),
  },
  {
    name: 'Tuned pass',
    note: 'input widened 3×',
    patch: (p) => ({ ...structuredClone(p), devices: { ...structuredClone(p.devices), input: { w_um: 6.0, l_nm: 45, m: 2 } } }),
  },
]

export function comparatorMeasurements(result: SimResult | null): Record<TargetKey, number | null> {
  return {
    decision_time_ps: result?.nominal?.decision_time_ps ?? null,
    power_uw: result?.nominal?.power_uw ?? null,
    offset_sigma_mv: result?.offset?.offset_sigma_mv ?? null,
    noise_uv_rms: result?.nominal?.noise_uv_rms ?? null,
  }
}

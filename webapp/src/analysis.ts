import type { SimResult } from './types'

/** Stable identity for the inputs that produced a result. */
export function analysisKey(...inputs: unknown[]): string {
  return JSON.stringify(inputs, (_key, value) => value && typeof value === 'object' && !Array.isArray(value)
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, value[key]])) : value)
}

export function comparatorVerdicts(result: SimResult, targets: Record<string, number>): Record<string, boolean | null> {
  const values: Record<string, number | null | undefined> = {
    decision_time_ps: result.nominal?.decision_time_ps,
    power_uw: result.nominal?.power_uw,
    offset_sigma_mv: result.offset?.offset_sigma_mv,
    noise_uv_rms: result.nominal?.noise_uv_rms,
  }
  return Object.fromEntries(Object.entries(targets).map(([key, limit]) => {
    const value = values[key]
    return [key, value == null || !Number.isFinite(value) ? null : !!result.nominal?.functional && value <= limit]
  }))
}

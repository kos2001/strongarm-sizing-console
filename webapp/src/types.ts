export type DeviceKey = 'input' | 'tail' | 'ncc' | 'pcc' | 'pre'

export interface Device {
  w_um: number
  l_nm: number
  m: number
}

export interface Params {
  vdd: number
  cload_ff: number
  avt_mv_um: number
  n_mc: number
  model?: 'ptm' | 'sky130'
  devices: Record<DeviceKey, Device>
}

export interface Nominal {
  decision_time_ps: number | null
  power_uw: number | null
  final_diff_v: number | null
  functional: boolean
  noise_uv_rms?: number | null
}

export interface Offset {
  offset_sigma_mv: number
  offset_mean_mv: number
  pelgrom_sigma_vth_mv: number
  n_mc: number
  samples_mv?: number[]
}

export interface SimResult {
  nominal: Nominal
  offset?: Offset
  verdicts: Record<string, boolean | null>
  params?: Params
  error?: string
}

export interface Target {
  limit: number
  cmp: string
  unit: string
  label: string
}

export interface Waveform {
  vdd: number
  t_ns: number[]
  clk: number[]
  outp: number[]
  outn: number[]
  decision_ns: number | null
  clk_edge_ns: number
  n: number
  error?: string
}

export interface PvtCorner {
  process: string
  temp: number
  v_frac: number
  vdd: number
  decision_time_ps: number | null
  power_uw: number | null
  functional: boolean
}

export interface PvtResult {
  corners: PvtCorner[]
  base_vdd: number
  worst: { decision_time_ps: number | null; power_uw: number | null; any_nonfunctional: boolean }
  error?: string
}

export interface ParetoPoint {
  power_uw: number | null
  decision_time_ps: number | null
  offp: number
  devices: Record<DeviceKey, Device>
}
export interface ParetoResult {
  front: ParetoPoint[]
  all: { power_uw: number | null; decision_time_ps: number | null; feasible: boolean }[]
  targets: Record<string, number>
  error?: string
}

export interface FlowStage { name: string; ok: boolean; detail: string }
export interface FlowResult {
  stages: FlowStage[]
  final_params: Params
  verdicts: Record<string, boolean | null>
  overall: boolean
  final_power_uw: number | null
  layout?: LayoutResult
  error?: string
}

export interface LayoutLayer { name: string; gds: string; color: string; z: number; rects: number[][] }
export interface LayoutResult {
  layers: LayoutLayer[]
  labels: { name: string; x: number; w: number; kind: string }[]
  bbox: { w: number; h: number; y0: number }
  area_um2: number
  gds_path: string
  drc: { clean: boolean; violations: string[]; n_violations: number; rules: string }
  error?: string
}

export interface PostLayout {
  schematic: { nominal: Nominal; waveform: Waveform }
  postlayout: { nominal: Nominal; waveform: Waveform }
  par_caps?: { c_out_ff: number; c_int_ff: number; per_device_ff: Record<string, number>; method: string }
  error?: string
}

export interface MetaPoint { vin_v: number; decision_time_ps: number | null; resolved: boolean }
export interface MetastabilityResult {
  points: MetaPoint[]
  tau_ps: number | null
  intercept_ps: number | null
  min_resolved_v: number | null
  error?: string
}

export interface BerPoint { vin_v: number; ber_noise: number; ber_total: number }
export interface BerResult {
  points: BerPoint[]
  noise_uv_rms: number
  offset_sigma_mv: number | null
  sigma_total_uv: number
  ber_target: number
  min_input_noise_uv: number
  min_input_total_uv: number
  error?: string
}

export interface FclkPoint { period_ns: number; fclk_ghz: number; functional: boolean; reset_ok: boolean; ok: boolean; power_uw: number | null; energy_fj: number | null }
export interface MaxFclkResult {
  points: FclkPoint[]
  max_fclk_ghz: number | null
  min_period_ns: number | null
  energy_fj_at_max: number | null
  power_uw_at_max: number | null
  error?: string
}

export interface YieldSample { offset_mv: number; decision_ps: number | null; temp: number; vdd: number; functional: boolean; correct: boolean; speed_ok: boolean; offset_ok: boolean; pass: boolean }
export interface YieldResult {
  n: number
  yield_pct: number
  pass: number
  fail_breakdown: { offset: number; speed: number; decision_wrong: number }
  samples: YieldSample[]
  targets: { decision_time_ps: number; offset_mv: number }
  error?: string
}

export interface SensMetrics { decision_time_ps: number | null; power_uw: number | null; offset_sigma_mv: number | null }
export interface SensDevice { key: DeviceKey; base_w_um: number; low: SensMetrics; high: SensMetrics }
export interface SensitivityResult {
  base: SensMetrics
  delta_pct: number
  devices: SensDevice[]
  error?: string
}

export interface OptStep {
  action: string
  predicted_offset_mv?: number
  total_w_um?: number
  measured?: { decision_time_ps: number | null; power_uw: number | null; offset_sigma_mv: number | null }
  verdicts?: Record<string, boolean | null>
  params: Record<DeviceKey, Device>
}

export interface OptimizeResult {
  trajectory: OptStep[]
  final_params: Params
  final_result: SimResult
  verdicts: Record<string, boolean | null>
  success: boolean
  targets: Record<string, number>
  final_power_uw?: number | null
  final_total_w_um?: number
  error?: string
}

export const DEVICE_META: Record<DeviceKey, { name: string; role: string; world: 'si' | 'ag' }> = {
  input: { name: 'Mn1 / Mn2', role: 'input pair — offset & noise', world: 'si' },
  tail: { name: 'Mtail', role: 'tail switch — speed', world: 'si' },
  ncc: { name: 'Mn3 / Mn4', role: 'latch NMOS — regeneration', world: 'si' },
  pcc: { name: 'Mp3 / Mp4', role: 'latch PMOS — regeneration', world: 'si' },
  pre: { name: 'Mp1 / Mp2', role: 'precharge — reset', world: 'si' },
}

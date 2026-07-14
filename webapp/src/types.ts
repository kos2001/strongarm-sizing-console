export type DeviceKey = 'input' | 'tail' | 'ncc' | 'pcc' | 'pre' | 'prei'

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
  model?: 'ptm' | 'sky130' | 'gaa2nm' | 'asap7'
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
  // gaa2nm: 자동 사이징이 실제로 찾은 정수 스택 수(W = 스택 × 0.2µ)
  final_stacks?: Record<DeviceKey, number> | null
  corner_aware?: boolean
  corner_note?: string | null
  final_corner?: { functional?: boolean; decision_time_ps?: number | null } | null
  error?: string
}

// ---- MOSFET ring VCO ----
export type VcoDeviceKey = 'invp' | 'invn' | 'starvep' | 'starven' | 'xcplp'
export type VcoTopology = 'starved' | 'xcpl'
export interface VcoParams {
  vdd: number
  vctrl: number
  n_stages: number
  cload_ff: number
  topology?: VcoTopology
  trst_ns?: number
  model?: 'ptm' | 'gaa2nm' | 'asap7'   // VCO 는 sky130 미지원(subckt 경로 없음)
  devices: Record<VcoDeviceKey, Device>
}
export interface VcoNominal {
  f_osc_ghz: number | null
  oscillates: boolean
  power_uw: number | null
  vpp_v: number | null
  n_stages: number
  vctrl_v: number
}
export interface VcoTuningPoint { vctrl_v: number; f_osc_ghz: number | null; power_uw: number | null; oscillates: boolean }
export interface VcoTuning {
  points: VcoTuningPoint[]
  f_min_ghz: number | null
  f_max_ghz: number | null
  tuning_pct: number | null
  kvco_ghz_per_v: number | null
  center_ghz: number | null
}
export interface VcoResult { nominal: VcoNominal; tuning?: VcoTuning; params?: VcoParams; error?: string }
export interface VcoOptStep { action: string; f_osc_ghz: number | null; power_uw: number | null; oscillates: boolean; params: Partial<Record<VcoDeviceKey, Device>> }
export interface VcoOptimizeResult {
  trajectory: VcoOptStep[]
  final_params: VcoParams
  nominal: VcoNominal
  tuning: VcoTuning
  success: boolean
  target_f_ghz: number
  n_sims: number
  n_surrogate_skips?: number
  // gaa2nm: 자동 사이징이 실제로 찾은 정수 스택 수(W = 스택 × 0.2µ)
  final_stacks?: Record<VcoDeviceKey, number> | null
  // 단수 N 탐색 스캔(홀수 3~9): 후보별 공칭 f 와 선택된 N
  stage_scan?: { points: { n: number; f_ghz: number | null; oscillates: boolean }[]; chosen_n: number; target_f_ghz: number } | null
  error?: string
}
export interface VcoWaveform { vdd: number; t_ns: number[]; o1: number[]; o2: number[]; period_ns: number | null; f_osc_ghz: number | null; error?: string }
export interface VcoPvtCorner { process: string; temp: number; v_frac: number; vdd: number; f_osc_ghz: number | null; oscillates: boolean; power_uw: number | null }
export interface VcoPvtResult { corners: VcoPvtCorner[]; base_vdd: number; f_min_ghz: number | null; f_max_ghz: number | null; any_nonosc: boolean; error?: string }
export interface VcoPushingPoint { vdd: number; f_osc_ghz: number | null; oscillates: boolean }
export interface VcoPushing { points: VcoPushingPoint[]; nominal_vdd: number; pushing_ghz_per_v: number | null; error?: string }
export interface VcoPhaseNoiseMeasured { f0_ghz: number; period_jitter_fs: number; jitter_spread_fs: number; n_seeds: number; cycles: number; points: { offset_hz: number; L_dbc: number }[]; L_1mhz_dbc: number; accum: { tau_ns: number; sigma_fs: number }[]; accum_slope: number | null; noise_type: string; method: string }
export interface VcoPhaseNoise {
  f0_ghz: number; power_uw: number; n_stages: number
  period_jitter_fs: number; c_eff_ff: number
  points: { offset_hz: number; L_dbc: number }[]
  L_1mhz_dbc: number; fom_db: number; flicker_corner_hz: number
  measured?: VcoPhaseNoiseMeasured
  error?: string
}
export interface VcoParetoPoint { power_uw: number | null; f_osc_ghz: number | null; devices: Partial<Record<VcoDeviceKey, Device>> }
export interface VcoParetoResult { front: VcoParetoPoint[]; all: { power_uw: number | null; f_osc_ghz: number | null; feasible: boolean }[]; error?: string }
// ── VCO WiCkeD (수율·강건성) ──────────────────────────────────────────────
export interface VcoWickedVerdict {
  nominal: VcoNominal & { vctrl_v?: number }
  margins: Record<string, number | null>
  pass: boolean
  targets?: Record<string, number>
  error?: string
}
export interface VcoWickedWcd {
  beta_sigma: number | null
  estimated_yield_pct: number | null
  nearest_failure?: { vdd?: number; temp?: number; pskew?: number; f_osc_ghz?: number | null; power_uw?: number | null; oscillates?: boolean } | null
  n_samples?: number
  error?: string
}
export interface VcoWickedMismatch {
  n: number
  mean_f_ghz: number | null
  sigma_f_mhz: number | null
  sigma_f_pct: number | null
  osc_failures: number
  startup_yield_pct: number | null
  error?: string
}
export interface VcoWickedYieldSweep {
  points: { pskew: number; yield_pct: number; n: number }[]
  error?: string
}

export interface VcoPostLayout { schematic: VcoWaveform; postlayout: VcoWaveform; par_caps: { c_node_ff: number; per_device_ff: Record<string, number>; method: string }; error?: string }
export interface VcoFlowStage { name: string; ok: boolean; detail: string }
export interface VcoFullflow {
  stages: VcoFlowStage[]
  final_params: VcoParams
  nominal: VcoNominal
  tuning: VcoTuning
  overall: boolean
  layout?: LayoutResult
  par_caps?: { c_node_ff: number }
  error?: string
}

export const VCO_DEVICE_META: Record<VcoDeviceKey, { name: string; role: { ko: string; en: string } }> = {
  invp: { name: 'Mp', role: { ko: '코어 PMOS — 상승', en: 'core PMOS — pull-up' } },
  invn: { name: 'Mn', role: { ko: '코어 NMOS — 하강', en: 'core NMOS — pull-down' } },
  starvep: { name: 'Mbp', role: { ko: 'PMOS 전류 스타빙', en: 'PMOS current-starve' } },
  starven: { name: 'Mbn', role: { ko: 'NMOS 전류 스타빙 (V_ctrl)', en: 'NMOS current-starve (V_ctrl)' } },
  xcplp: { name: 'Mx', role: { ko: 'P1 — 교차 결합 PMOS (약하게)', en: 'P1 — cross-coupled PMOS (keep weak)' } },
}

export const DEVICE_META: Record<DeviceKey, { name: string; role: string; world: 'si' | 'ag' }> = {
  input: { name: 'M1 / M2', role: 'input pair — offset & noise', world: 'si' },
  tail: { name: 'M7', role: 'tail switch — speed', world: 'si' },
  ncc: { name: 'M3 / M4', role: 'latch NMOS — regeneration', world: 'si' },
  pcc: { name: 'M5 / M6', role: 'latch PMOS — regeneration', world: 'si' },
  pre: { name: 'S3 / S4', role: 'precharge X·Y (outputs)', world: 'si' },
  prei: { name: 'S1 / S2', role: 'precharge P·Q (internal)', world: 'si' },
}

export interface ProbitResult {
  sigma_uv_probit?: number
  sigma_uv_analytic?: number
  ratio?: number
  points?: { vin_uv: number; p_plus: number; n: number }[]
  n_sims?: number
  error?: string
}

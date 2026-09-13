import { requestJson } from './execution'
import type { ResolutionResult, BerResult, VcoWickedMismatch, VcoWickedVerdict, VcoWickedWcd, VcoWickedYieldSweep, FlowResult, LayoutResult, MaxFclkResult, MetastabilityResult, OptimizeResult, Params, ParetoResult, PostLayout, PvtResult, SensitivityResult, SimResult, Target, VcoFullflow, VcoOptimizeResult, VcoParams, VcoParetoResult, VcoPhaseNoise, VcoPostLayout, VcoPushing, VcoPvtResult, VcoResult, VcoTuning, VcoWaveform, Waveform, WcdResult, WickedCornersResult, WickedFlowResult, WickedImportanceResult, YieldResult } from './types'

async function post<T>(path: string, params: Params): Promise<T> {
  return requestJson(path, { params })
}
export const metastability = (params: Params) => post<MetastabilityResult>('/api/metastability', params)
export const ber = (params: Params) => post<BerResult>('/api/ber', params)
export const sensitivity = (params: Params) => post<SensitivityResult>('/api/sensitivity', params)
export const maxfclk = (params: Params) => post<MaxFclkResult>('/api/maxfclk', params)
// metastability + offset MC + BER on one amplitude axis, in one call
export const resolution = (params: Params) => post<ResolutionResult>('/api/resolution', params)

export async function vcoSimulate(params: VcoParams, doTuning = false): Promise<VcoResult> {
  return requestJson('/api/vco/simulate', { params, do_tuning: doTuning })
}
export async function vcoTuning(params: VcoParams): Promise<VcoTuning> {
  return requestJson('/api/vco/tuning', { params })
}
export async function vcoOptimize(params: VcoParams, targetFGhz: number): Promise<VcoOptimizeResult> {
  return requestJson('/api/vco/optimize', { params, targets: { f_ghz: targetFGhz } })
}
// VCO WiCkeD — targets/샘플 수를 함께 보내는 호출
const wpost = <T,>(path: string, params: VcoParams, extra: Record<string, unknown> = {}): Promise<T> =>
  requestJson<T>(path, { params, ...extra })
export const vcoWickedVerdict = (p: VcoParams, targets?: Record<string, number>) => wpost<VcoWickedVerdict>('/api/vco/wicked/verdict', p, { targets })
export const vcoWickedWcd = (p: VcoParams, targets?: Record<string, number>) => wpost<VcoWickedWcd>('/api/vco/wicked/wcd', p, { targets, n_samples: 12 })
export const vcoWickedMismatch = (p: VcoParams) => wpost<VcoWickedMismatch>('/api/vco/wicked/mismatch', p, { n: 10 })
export const vcoWickedYieldsweep = (p: VcoParams, targets?: Record<string, number>) => wpost<VcoWickedYieldSweep>('/api/vco/wicked/yieldsweep', p, { targets, n_points: 5, n_mc: 4 })

const vpost = <T,>(path: string, params: VcoParams): Promise<T> =>
  requestJson<T>(path, { params })
export const vcoWaveform = (p: VcoParams) => vpost<VcoWaveform>('/api/vco/waveform', p)
export const vcoPvt = (p: VcoParams) => vpost<VcoPvtResult>('/api/vco/pvt', p)
export const vcoPushing = (p: VcoParams) => vpost<VcoPushing>('/api/vco/pushing', p)
export const vcoPhaseNoise = (p: VcoParams) => vpost<VcoPhaseNoise>('/api/vco/phasenoise', p)
export const vcoLayout = (p: VcoParams) => vpost<LayoutResult>('/api/vco/layout', p)
export const vcoPostlayout = (p: VcoParams) => vpost<VcoPostLayout>('/api/vco/postlayout', p)
export const vcoPareto = (p: VcoParams) => vpost<VcoParetoResult>('/api/vco/pareto', p)
export const vcoFullflow = (p: VcoParams, targetFGhz = 1.5) => wpost<VcoFullflow>('/api/vco/fullflow', p, { targets: { f_ghz: targetFGhz } })
// Comparator WiCkeD robustness bridge — body carries params + spec targets
// (+ knobs). Distinct from the VCO's `wpost` above, which takes VcoParams and
// merges `extra`; this one posts a body the caller has already assembled.
const cwpost = <T,>(path: string, body: Record<string, unknown>): Promise<T> =>
  requestJson<T>(path, body)
export const wickedWcd = (params: Params, targets: Record<string, number>, nSamples = 24) =>
  cwpost<WcdResult>('/api/wicked/wcd', { params, targets, n_samples: nSamples })
export const wickedImportance = (params: Params, targets: Record<string, number>, n = 24) =>
  cwpost<WickedImportanceResult>('/api/wicked/importance', { params, targets, n })
export const wickedCorners = (params: Params, targets: Record<string, number>) =>
  cwpost<WickedCornersResult>('/api/wicked/corners', { params, targets })
export const wickedFullflow = (params: Params, targets: Record<string, number>) =>
  cwpost<WickedFlowResult>('/api/wicked/fullflow', { params, targets, importance_samples: 8 })

export async function yieldRun(params: Params, targets: Record<string, number>, n = 48): Promise<YieldResult> {
  return requestJson('/api/yield', { params, targets, n })
}

export async function health(): Promise<{ ok: boolean; ngspice: string }> {
  return requestJson('/api/health')
}

export async function getDefaults(): Promise<{ defaults: Params; targets: Record<string, Target> }> {
  return requestJson('/api/defaults')
}

export async function simulate(params: Params, doOffset: boolean): Promise<SimResult> {
  return requestJson('/api/simulate', { params, do_offset: doOffset })
}

export async function optimize(params: Params, targets: Record<string, number>): Promise<OptimizeResult> {
  return requestJson('/api/optimize', { params, targets })
}

export async function waveform(params: Params): Promise<Waveform> {
  return requestJson('/api/waveform', { params })
}

export async function postlayout(params: Params): Promise<PostLayout> {
  return requestJson('/api/postlayout', { params })
}

export async function pvt(params: Params): Promise<PvtResult> {
  return requestJson('/api/pvt', { params })
}

export async function pareto(params: Params, targets: Record<string, number>): Promise<ParetoResult> {
  return requestJson('/api/pareto', { params, targets })
}

export async function fullflow(params: Params, targets: Record<string, number>): Promise<FlowResult> {
  return requestJson('/api/fullflow', { params, targets })
}

export async function layout(params: Params): Promise<LayoutResult> {
  return requestJson('/api/layout', { params })
}

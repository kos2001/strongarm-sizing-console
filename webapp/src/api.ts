import type { BerResult, FlowResult, LayoutResult, MaxFclkResult, MetastabilityResult, OptimizeResult, Params, ParetoResult, PostLayout, PvtResult, SensitivityResult, SimResult, Target, VcoFullflow, VcoOptimizeResult, VcoParams, VcoParetoResult, VcoPhaseNoise, VcoPostLayout, VcoPushing, VcoPvtResult, VcoResult, VcoTuning, VcoWaveform, Waveform, WcdResult, WickedCornersResult, WickedFlowResult, WickedImportanceResult, YieldResult } from './types'

async function post<T>(path: string, params: Params): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ params }) })
  return r.json()
}
export const metastability = (params: Params) => post<MetastabilityResult>('/api/metastability', params)
export const ber = (params: Params) => post<BerResult>('/api/ber', params)
export const sensitivity = (params: Params) => post<SensitivityResult>('/api/sensitivity', params)
export const maxfclk = (params: Params) => post<MaxFclkResult>('/api/maxfclk', params)

export async function vcoSimulate(params: VcoParams, doTuning = false): Promise<VcoResult> {
  const r = await fetch('/api/vco/simulate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ params, do_tuning: doTuning }) })
  return r.json()
}
export async function vcoTuning(params: VcoParams): Promise<VcoTuning> {
  const r = await fetch('/api/vco/tuning', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ params }) })
  return r.json()
}
export async function vcoOptimize(params: VcoParams, targetFGhz: number): Promise<VcoOptimizeResult> {
  const r = await fetch('/api/vco/optimize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ params, targets: { f_ghz: targetFGhz } }) })
  return r.json()
}
const vpost = <T,>(path: string, params: VcoParams): Promise<T> =>
  fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ params }) }).then((r) => r.json())
export const vcoWaveform = (p: VcoParams) => vpost<VcoWaveform>('/api/vco/waveform', p)
export const vcoPvt = (p: VcoParams) => vpost<VcoPvtResult>('/api/vco/pvt', p)
export const vcoPushing = (p: VcoParams) => vpost<VcoPushing>('/api/vco/pushing', p)
export const vcoPhaseNoise = (p: VcoParams) => vpost<VcoPhaseNoise>('/api/vco/phasenoise', p)
export const vcoLayout = (p: VcoParams) => vpost<LayoutResult>('/api/vco/layout', p)
export const vcoPostlayout = (p: VcoParams) => vpost<VcoPostLayout>('/api/vco/postlayout', p)
export const vcoPareto = (p: VcoParams) => vpost<VcoParetoResult>('/api/vco/pareto', p)
export const vcoFullflow = (p: VcoParams) => vpost<VcoFullflow>('/api/vco/fullflow', p)
// WiCkeD robustness bridge — body carries params + spec targets (+ knobs)
const wpost = <T,>(path: string, body: Record<string, unknown>): Promise<T> =>
  fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.json())
export const wickedWcd = (params: Params, targets: Record<string, number>, nSamples = 24) =>
  wpost<WcdResult>('/api/wicked/wcd', { params, targets, n_samples: nSamples })
export const wickedImportance = (params: Params, targets: Record<string, number>, n = 24) =>
  wpost<WickedImportanceResult>('/api/wicked/importance', { params, targets, n })
export const wickedCorners = (params: Params, targets: Record<string, number>) =>
  wpost<WickedCornersResult>('/api/wicked/corners', { params, targets })
export const wickedFullflow = (params: Params, targets: Record<string, number>) =>
  wpost<WickedFlowResult>('/api/wicked/fullflow', { params, targets, importance_samples: 8 })

export async function yieldRun(params: Params, targets: Record<string, number>, n = 48): Promise<YieldResult> {
  const r = await fetch('/api/yield', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ params, targets, n }) })
  return r.json()
}

export async function health(): Promise<{ ok: boolean; ngspice: string }> {
  const r = await fetch('/api/health')
  return r.json()
}

export async function getDefaults(): Promise<{ defaults: Params; targets: Record<string, Target> }> {
  const r = await fetch('/api/defaults')
  return r.json()
}

export async function simulate(params: Params, doOffset: boolean): Promise<SimResult> {
  const r = await fetch('/api/simulate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params, do_offset: doOffset }),
  })
  return r.json()
}

export async function optimize(params: Params, targets: Record<string, number>): Promise<OptimizeResult> {
  const r = await fetch('/api/optimize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params, targets }),
  })
  return r.json()
}

export async function waveform(params: Params): Promise<Waveform> {
  const r = await fetch('/api/waveform', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
  })
  return r.json()
}

export async function postlayout(params: Params): Promise<PostLayout> {
  const r = await fetch('/api/postlayout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
  })
  return r.json()
}

export async function pvt(params: Params): Promise<PvtResult> {
  const r = await fetch('/api/pvt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
  })
  return r.json()
}

export async function pareto(params: Params, targets: Record<string, number>): Promise<ParetoResult> {
  const r = await fetch('/api/pareto', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params, targets }),
  })
  return r.json()
}

export async function fullflow(params: Params, targets: Record<string, number>): Promise<FlowResult> {
  const r = await fetch('/api/fullflow', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params, targets }),
  })
  return r.json()
}

export async function layout(params: Params): Promise<LayoutResult> {
  const r = await fetch('/api/layout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
  })
  return r.json()
}

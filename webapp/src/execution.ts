import { analysisKey } from './analysis.ts'
import { readJson } from './http.ts'

export interface Execution {
  id: number
  path: string
  domain: 'comparator' | 'vco'
  page: string
  label: { ko: string; en: string }
  state: 'running' | 'succeeded' | 'failed'
  startedAt: number
  finishedAt?: number
  error?: string
}
const descriptions: Record<string, [string, string, string]> = {
  simulate: ['sizing', 'SPICE 측정', 'SPICE measurements'],
  optimize: ['optimizer', '자동 최적화', 'Auto optimization'],
  waveform: ['circuit', '파형 캡처', 'Waveform capture'],
  postlayout: ['circuit', '기생 성분 분석', 'Parasitic analysis'],
  pvt: ['pvt', 'PVT 코너', 'PVT corners'],
  pareto: ['pareto', '파레토 탐색', 'Pareto search'],
  fullflow: ['flow', '전체 설계 흐름', 'Full design flow'],
  layout: ['layout', '레이아웃 생성', 'Layout generation'],
  resolution: ['resolution', '입력 해상도', 'Input resolution'],
  metastability: ['metastability', '메타안정성', 'Metastability'],
  ber: ['ber', '노이즈 / BER', 'Noise / BER'],
  'noise/probit': ['ber', '노이즈 샘플링', 'Noise sampling'],
  sensitivity: ['sensitivity', '민감도', 'Sensitivity'],
  maxfclk: ['maxfclk', '최대 클럭', 'Maximum clock'],
  yield: ['yield', '수율 분석', 'Yield analysis'],
  tuning: ['vco', 'VCO 튜닝', 'VCO tuning'],
  pushing: ['vcopushing', '전원 푸싱', 'Supply pushing'],
  phasenoise: ['vcopn', '위상잡음', 'Phase noise'],
}
const vcoPages: Record<string, string> = { simulate: 'vco', optimize: 'vcoopt', waveform: 'vcocircuit', postlayout: 'vcolayout', pvt: 'vcopvt', pareto: 'vcopareto', fullflow: 'vcoflow', layout: 'vcolayout' }
const robustness: Record<string, [string, string]> = { verdict: ['공칭 판정', 'Nominal verdict'], wcd: ['최악거리', 'Worst-case distance'], mismatch: ['미스매치', 'Mismatch'], yieldsweep: ['수율 스윕', 'Yield sweep'], importance: ['고시그마 수율', 'High-sigma yield'], corners: ['최악 코너', 'Worst corners'], fullflow: ['강건성 전체 흐름', 'Robustness flow'] }
const pending = new Map<string, Promise<unknown>>()
const listeners = new Set<() => void>()
let sequence = 0
let snapshot: readonly Execution[] = []
export const getExecutions = () => snapshot
export const subscribeExecutions = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
function publish(records: readonly Execution[]) {
  snapshot = [...records.filter(record => record.state === 'running'), ...records.filter(record => record.state !== 'running').slice(0, 20)]
  listeners.forEach(listener => listener())
}
function describe(path: string) {
  const vco = path.startsWith('/api/vco/')
  const name = path.replace(vco ? '/api/vco/' : '/api/', '')
  const wicked = name.startsWith('wicked/')
  const details = wicked ? robustness[name.slice(7)] ?? ['강건성 분석', 'Robustness analysis'] : null
  const [page, ko, en] = descriptions[name] ?? ['sizing', '분석', 'Analysis']
  return { domain: vco ? 'vco' as const : 'comparator' as const,
    page: wicked ? (vco ? 'vcoyield' : 'wicked') : (vcoPages[name] && vco ? vcoPages[name] : page),
    label: { ko: details?.[0] ?? ko, en: details?.[1] ?? en } }
}

/** Track the complete JSON response, share only identical in-flight requests,
 * and keep each caller's result independent. Failed requests can be retried. */
export function requestJson<T>(path: string, body?: unknown): Promise<T> {
  if (body === undefined) return fetch(path).then(response => readJson<T>(response))
  const key = analysisKey(path, body)
  let request = pending.get(key)
  if (!request) {
    const task: Execution = { id: ++sequence, path, ...describe(path), state: 'running', startedAt: Date.now() }
    request = Promise.resolve().then(() => fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })).then(response => readJson(response)).then(value => {
      publish(snapshot.map(record => record.id === task.id ? { ...record, state: 'succeeded', finishedAt: Date.now() } : record))
      return value
    }, error => {
      publish(snapshot.map(record => record.id === task.id ? { ...record, state: 'failed', finishedAt: Date.now(), error: error instanceof Error ? error.message : String(error) } : record))
      throw error
    }).finally(() => pending.delete(key))
    pending.set(key, request)
    publish([task, ...snapshot])
  }
  return request.then(value => structuredClone(value) as T)
}

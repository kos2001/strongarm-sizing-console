import type { Params, VcoParams } from './types'

export type DesignDomain = 'comparator' | 'vco'
export interface DesignProject {
  format: 'strongarm-design'
  version: 1
  domain: DesignDomain
  name: string
  savedAt: string
  params: Params | VcoParams
  targets: Record<string, number>
}
export const MAX_PROJECT_BYTES = 1024 * 1024
const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v)
const number = (v: unknown, zero = false): v is number => typeof v === 'number' && Number.isFinite(v) && (zero ? v >= 0 : v > 0)
const integer = (v: unknown): v is number => number(v) && Number.isInteger(v)
const safeTree = (value: unknown, depth = 0): boolean => {
  if (depth > 30) return false
  if (typeof value === 'number') return Number.isFinite(value)
  if (value && typeof value === 'object') return Object.entries(value).every(([key, v]) =>
    !['__proto__', 'constructor', 'prototype'].includes(key) && safeTree(v, depth + 1))
  return true
}

export function parseProject(raw: string, expectedDomain: DesignDomain): DesignProject {
  if (new TextEncoder().encode(raw).length > MAX_PROJECT_BYTES) throw new Error('Project file exceeds 1 MiB.')
  let file: unknown
  try { file = JSON.parse(raw) } catch { throw new Error('Invalid JSON project file.') }
  if (!record(file) || !safeTree(file) || file.format !== 'strongarm-design' || file.version !== 1) {
    throw new Error('Unsupported project format or version.')
  }
  if (file.domain !== 'comparator' && file.domain !== 'vco') throw new Error('Unsupported circuit domain.')
  if (file.domain !== expectedDomain) throw new Error(`Open this file in the ${file.domain === 'vco' ? 'VCO' : 'comparator'} workspace.`)
  if (typeof file.name !== 'string' || !file.name.trim() || file.name.length > 120 || typeof file.savedAt !== 'string' || !Number.isFinite(Date.parse(file.savedAt))) {
    throw new Error('Project name or save date is invalid.')
  }
  const p = file.params
  if (!record(p) || !number(p.vdd) || !number(p.cload_ff, true) || !record(p.devices)) throw new Error('Invalid circuit inputs.')
  const keys = expectedDomain === 'comparator' ? ['input', 'tail', 'ncc', 'pcc', 'pre', 'prei'] : ['invp', 'invn', 'starvep', 'starven', 'xcplp']
  for (const key of keys) {
    const d = p.devices[key]
    if (!record(d) || !number(d.w_um) || !number(d.l_nm) || !integer(d.m) || (d.vt !== undefined && !['lvt', 'svt', 'hvt'].includes(String(d.vt)))) {
      throw new Error(`Invalid device dimensions: ${key}.`)
    }
  }
  const models = expectedDomain === 'comparator' ? ['ptm', 'ptm45', 'sky130', 'gaa2nm', 'asap7'] : ['ptm', 'gaa2nm', 'asap7']
  if (p.model !== undefined && !models.includes(String(p.model))) throw new Error('Unsupported device model.')
  if (expectedDomain === 'comparator') {
    if (!number(p.avt_mv_um, true) || !integer(p.n_mc)) throw new Error('Invalid mismatch inputs.')
  } else {
    if (!integer(p.n_stages) || p.n_stages < 3 || p.n_stages > 9 || p.n_stages % 2 !== 1 || !number(p.vctrl, true)) throw new Error('VCO stages must be 3, 5, 7, or 9, with a nonnegative control voltage.')
    if (p.topology !== undefined && !['starved', 'xcpl', 'xcplsv'].includes(String(p.topology))) throw new Error('Unsupported VCO topology.')
  }
  const targets = expectedDomain === 'comparator' ? ['decision_time_ps', 'power_uw', 'offset_sigma_mv', 'noise_uv_rms'] : ['f_ghz']
  if (!record(file.targets) || !targets.every(key => number((file.targets as Record<string, unknown>)[key])) || !Object.entries(file.targets).every(([key, value]) => targets.includes(key) && number(value))) throw new Error('Invalid specification targets.')
  // Preserve additional backend settings rather than silently dropping them.
  return file as unknown as DesignProject
}

export function projectFilename(name: string): string {
  return `${name.trim().replace(/[^\p{L}\p{N}._-]+/gu, '-').slice(0, 100) || 'design'}.strongarm.json`
}

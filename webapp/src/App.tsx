import { useEffect, useRef, useState } from 'react'
import type { BerResult, DeviceKey, FlowResult, LayoutResult, MaxFclkResult, MetastabilityResult, Offset, OptimizeResult, OptStep, Params, ParetoResult, PostLayout, PvtResult, SensitivityResult, SimResult, Waveform, YieldResult } from './types'
import { DEVICE_META } from './types'
import { ber, fullflow, getDefaults, health, layout, maxfclk, metastability, optimize, pareto, postlayout, pvt, sensitivity, simulate, waveform, yieldRun } from './api'
import BerChart from './components/BerChart'
import DeviceEditor from './components/DeviceEditor'
import FclkChart from './components/FclkChart'
import Gauge from './components/Gauge'
import LayoutView from './components/LayoutView'
import MetastabilityChart from './components/MetastabilityChart'
import MonteCarloChart from './components/MonteCarloChart'
import ParetoChart from './components/ParetoChart'
import PageHelp from './components/PageHelp'
import Schematic from './components/Schematic'
import { downloadNetlist } from './netlist'
import SensitivityChart from './components/SensitivityChart'
import VcoPage from './components/VcoPage'
import WaveformChart from './components/WaveformChart'
import YieldView from './components/YieldView'
import { NAV_LABELS, NAV_SUBS, t, UI, type Lang } from './i18n'

// metric metadata is fixed; the *limits* are editable (see spec profiles below)
type TargetKey = 'decision_time_ps' | 'power_uw' | 'offset_sigma_mv' | 'noise_uv_rms'
const TARGET_KEYS: TargetKey[] = ['decision_time_ps', 'power_uw', 'offset_sigma_mv', 'noise_uv_rms']
const TARGET_META: Record<TargetKey, { unit: string; label: string; step: number }> = {
  decision_time_ps: { unit: 'ps', label: 'Decision time', step: 10 },
  power_uw: { unit: 'µW', label: 'Power', step: 5 },
  offset_sigma_mv: { unit: 'mV', label: 'Offset σ', step: 0.5 },
  noise_uv_rms: { unit: 'µV', label: 'Input noise', step: 10 },
}
type Targets = Record<TargetKey, number>
// application-driven spec profiles; pick one, then fine-tune any limit inline
const SPEC_PROFILES: { id: string; label: string; note: string; targets: Targets }[] = [
  { id: 'P1', label: 'P1 · SAR-ADC', note: '10-bit SAR comparator (balanced)', targets: { decision_time_ps: 400, power_uw: 100, offset_sigma_mv: 5, noise_uv_rms: 250 } },
  { id: 'P2', label: 'P2 · High-speed', note: 'fast link RX, offset-relaxed', targets: { decision_time_ps: 150, power_uw: 300, offset_sigma_mv: 10, noise_uv_rms: 400 } },
  { id: 'P3', label: 'P3 · Low-power', note: 'sensor front-end, precise + quiet', targets: { decision_time_ps: 800, power_uw: 40, offset_sigma_mv: 3, noise_uv_rms: 150 } },
]

const DEFAULTS: Params = {
  vdd: 0.7,
  cload_ff: 15.0,
  avt_mv_um: 2.0,
  n_mc: 16,
  devices: {
    input: { w_um: 8.0, l_nm: 80.0, m: 4 },
    tail: { w_um: 12.0, l_nm: 45.0, m: 6 },
    ncc: { w_um: 4.0, l_nm: 45.0, m: 2 },
    pcc: { w_um: 9.0, l_nm: 45.0, m: 4 },
    pre: { w_um: 4.0, l_nm: 45.0, m: 2 },
  },
}

const PRESETS: { name: string; note: string; patch: (p: Params) => Params }[] = [
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

type Page = 'sizing' | 'circuit' | 'metastability' | 'maxfclk' | 'optimizer' | 'sensitivity' | 'pareto' | 'montecarlo' | 'ber' | 'pvt' | 'yield' | 'layout' | 'flow'
  | 'vcocircuit' | 'vco' | 'vcoopt' | 'vcopareto' | 'vcopn' | 'vcopvt' | 'vcoyield' | 'vcopushing' | 'vcolayout' | 'vcoflow'
type Domain = 'comparator' | 'vco'
const NAV_COMPARATOR: { id: Page; glyph: string }[] = [
  { id: 'sizing', glyph: '▦' },
  { id: 'circuit', glyph: '⎓' },
  { id: 'metastability', glyph: '⧗' },
  { id: 'maxfclk', glyph: '⎍' },
  { id: 'optimizer', glyph: '◴' },
  { id: 'sensitivity', glyph: '⇕' },
  { id: 'pareto', glyph: '⤢' },
  { id: 'montecarlo', glyph: '∿' },
  { id: 'ber', glyph: '⊹' },
  { id: 'pvt', glyph: '◫' },
  { id: 'yield', glyph: '⊞' },
  { id: 'layout', glyph: '▧' },
  { id: 'flow', glyph: '⇉' },
]
const NAV_VCO: { id: Page; glyph: string }[] = [
  { id: 'vcocircuit', glyph: '⎓' },
  { id: 'vco', glyph: '∿' },
  { id: 'vcoopt', glyph: '◴' },
  { id: 'vcopareto', glyph: '⤢' },
  { id: 'vcopn', glyph: '⌇' },
  { id: 'vcopvt', glyph: '◫' },
  { id: 'vcoyield', glyph: '⊞' },
  { id: 'vcopushing', glyph: '⇅' },
  { id: 'vcolayout', glyph: '▧' },
  { id: 'vcoflow', glyph: '⇉' },
]
const DOMAIN_HOME: Record<Domain, Page> = { comparator: 'sizing', vco: 'vcocircuit' }
const DOMAIN_OF: Record<string, Domain> = { vcocircuit: 'vco', vco: 'vco', vcoopt: 'vco', vcopareto: 'vco', vcopn: 'vco', vcopvt: 'vco', vcoyield: 'vco', vcopushing: 'vco', vcolayout: 'vco', vcoflow: 'vco' }
const VCO_VIEW: Record<string, 'circuit' | 'main' | 'opt' | 'pvt' | 'pushing' | 'pareto' | 'layout' | 'flow' | 'pn' | 'yield'> = { vcocircuit: 'circuit', vco: 'main', vcoopt: 'opt', vcopareto: 'pareto', vcopn: 'pn', vcopvt: 'pvt', vcoyield: 'yield', vcopushing: 'pushing', vcolayout: 'layout', vcoflow: 'flow' }
const domainOf = (p: Page): Domain => DOMAIN_OF[p] ?? 'comparator'

interface HistoryItem {
  id: number
  params: Params
  result: SimResult
  doOffset: boolean
}

export default function App() {
  const [params, setParams] = useState<Params>(DEFAULTS)
  const [profile, setProfile] = useState<string>('P1')
  const [targets, setTargets] = useState<Targets>(SPEC_PROFILES[0].targets)
  const [doOffset, setDoOffset] = useState(true)
  const [running, setRunning] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [result, setResult] = useState<SimResult | null>(null)
  const [opt, setOpt] = useState<OptimizeResult | null>(null)
  const [play, setPlay] = useState<{ steps: OptStep[]; idx: number; auto: boolean } | null>(null)
  const [page, setPage] = useState<Page>('sizing')
  const [wf, setWf] = useState<Waveform | null>(null)
  const [wfBefore, setWfBefore] = useState<Waveform | null>(null)
  const [mcBefore, setMcBefore] = useState<Offset | null>(null)
  const [wfLoading, setWfLoading] = useState(false)
  const [postLayout, setPostLayout] = useState<PostLayout | null>(null)
  const [plLoading, setPlLoading] = useState(false)
  const [pvtRes, setPvtRes] = useState<PvtResult | null>(null)
  const [pvtLoading, setPvtLoading] = useState(false)
  const [paretoRes, setParetoRes] = useState<ParetoResult | null>(null)
  const [paretoSel, setParetoSel] = useState<number | null>(null) // 파레토 front 선택점(상세 패널)
  const [paretoLoading, setParetoLoading] = useState(false)
  const [flowRes, setFlowRes] = useState<FlowResult | null>(null)
  const [flowLoading, setFlowLoading] = useState(false)
  const [layoutRes, setLayoutRes] = useState<LayoutResult | null>(null)
  const [layoutLoading, setLayoutLoading] = useState(false)
  const [metaRes, setMetaRes] = useState<MetastabilityResult | null>(null)
  const [metaLoading, setMetaLoading] = useState(false)
  const [berRes, setBerRes] = useState<BerResult | null>(null)
  const [berLoading, setBerLoading] = useState(false)
  const [sensRes, setSensRes] = useState<SensitivityResult | null>(null)
  const [sensLoading, setSensLoading] = useState(false)
  const [fclkRes, setFclkRes] = useState<MaxFclkResult | null>(null)
  const [fclkLoading, setFclkLoading] = useState(false)
  const [yieldRes, setYieldRes] = useState<YieldResult | null>(null)
  const [yieldLoading, setYieldLoading] = useState(false)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [apiUp, setApiUp] = useState<boolean | null>(null)
  const [ngspice, setNgspice] = useState('')
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const [lang, setLang] = useState<Lang>('ko')
  const idRef = useRef(1)
  const timerRef = useRef<number | null>(null)

  const loadWaveform = async (p: Params) => {
    setWfLoading(true)
    setWfBefore(null) // single-trace mode (overlay only set by the optimizer)
    try {
      const w = await waveform(p)
      if (!w.error) setWf(w)
    } catch {
      /* leave previous waveform */
    } finally {
      setWfLoading(false)
    }
  }

  const runPostLayout = async () => {
    setPlLoading(true)
    try {
      const r = await postlayout(params)
      if (!r.error) setPostLayout(r)
    } catch {
      /* ignore */
    } finally {
      setPlLoading(false)
    }
  }

  const runPvt = async () => {
    setPvtLoading(true)
    try {
      const r = await pvt(params)
      if (!r.error) setPvtRes(r)
    } catch {
      /* ignore */
    } finally {
      setPvtLoading(false)
    }
  }

  const runPareto = async () => {
    setParetoLoading(true)
    try {
      const r = await pareto(params, targets)
      if (!r.error) setParetoRes(r)
    } catch {
      /* ignore */
    } finally {
      setParetoLoading(false)
    }
  }

  const runFlow = async () => {
    setFlowLoading(true)
    try {
      const r = await fullflow(params, targets)
      if (!r.error) {
        setFlowRes(r)
        updateParams(r.final_params) // land the flow's sized design in the editor
      }
    } catch {
      /* ignore */
    } finally {
      setFlowLoading(false)
    }
  }

  const runLayout = async () => {
    setLayoutLoading(true)
    try {
      const r = await layout(params)
      if (!r.error) setLayoutRes(r)
    } catch {
      /* ignore */
    } finally {
      setLayoutLoading(false)
    }
  }

  const runMeta = async () => {
    setMetaLoading(true)
    try {
      const r = await metastability(params)
      if (!r.error) setMetaRes(r)
    } catch {
      /* ignore */
    } finally {
      setMetaLoading(false)
    }
  }

  const runBer = async () => {
    setBerLoading(true)
    try {
      const r = await ber(params)
      if (!r.error) setBerRes(r)
    } catch {
      /* ignore */
    } finally {
      setBerLoading(false)
    }
  }

  const runSens = async () => {
    setSensLoading(true)
    try {
      const r = await sensitivity(params)
      if (!r.error) setSensRes(r)
    } catch {
      /* ignore */
    } finally {
      setSensLoading(false)
    }
  }

  const runFclk = async () => {
    setFclkLoading(true)
    try {
      const r = await maxfclk(params)
      if (!r.error) setFclkRes(r)
    } catch {
      /* ignore */
    } finally {
      setFclkLoading(false)
    }
  }

  const runYield = async () => {
    setYieldLoading(true)
    try {
      const r = await yieldRun(params, targets, 48)
      if (!r.error) setYieldRes(r)
    } catch {
      /* ignore */
    } finally {
      setYieldLoading(false)
    }
  }

  const downloadReport = () => {
    const ts = new Date().toISOString()
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
    if (pvtRes) lines.push(``, `## PVT sign-off (27 corners)`, ``, `- Worst decision: ${fmt(pvtRes.worst.decision_time_ps, 'ps')}`, `- Worst power: ${fmt(pvtRes.worst.power_uw, 'µW')}`, `- All corners resolve: ${pvtRes.worst.any_nonfunctional ? 'NO' : 'yes'}`)
    if (sensRes) lines.push(``, `## Sensitivity (±${sensRes.delta_pct}% W)`, ``, ...sensRes.devices.map((d) => `- ${DEVICE_META[d.key].name}: decision ${d.low.decision_time_ps}→${d.high.decision_time_ps} ps, offset ${d.low.offset_sigma_mv}→${d.high.offset_sigma_mv} mV`))
    if (paretoRes) lines.push(``, `## Pareto front`, ``, `- ${paretoRes.front.length} non-dominated designs (power ↔ decision-time)`)
    lines.push(``, `---`, ``, `<details><summary>Raw JSON</summary>`, ``, '```json', JSON.stringify({ params, targets, result, metaRes, berRes, sensRes, fclkRes, yieldRes, pvtRes: pvtRes?.worst, generated: ts }, null, 2), '```', ``, `</details>`, ``)
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `strongarm-report-${ts.slice(0, 19).replace(/[:T]/g, '')}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    void loadWaveform(DEFAULTS) // show the seed transient on first load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // step the schematic through the optimizer trajectory (one device change per tick)
  useEffect(() => {
    if (!play?.auto || play.idx >= play.steps.length - 1) return
    const id = window.setTimeout(
      () => setPlay((p) => (p && p.auto ? { ...p, idx: Math.min(p.idx + 1, p.steps.length - 1) } : p)),
      950,
    )
    return () => clearTimeout(id)
  }, [play])

  const updateParams = (p: Params) => {
    setPlay(null) // manual edits leave playback mode
    setParams(p)
  }

  useEffect(() => {
    health()
      .then((h) => {
        setApiUp(h.ok)
        setNgspice(h.ngspice)
      })
      .catch(() => setApiUp(false))
    getDefaults()
      .then((d) => d?.defaults && setParams(d.defaults))
      .catch(() => {})
  }, [])

  const run = async (forceOffset = false) => {
    setRunning(true)
    setMcBefore(null) // single distribution (before/after only from optimizer)
    setElapsed(0)
    const t0 = performance.now()
    timerRef.current = window.setInterval(() => setElapsed((performance.now() - t0) / 1000), 100)
    try {
      const res = await simulate(params, forceOffset || doOffset)
      setResult(res)
      if (!res.error) {
        setHistory((h) => [{ id: idRef.current++, params: structuredClone(params), result: res, doOffset }, ...h].slice(0, 8))
        void loadWaveform(params)
      }
    } catch (e) {
      setResult({ nominal: { decision_time_ps: null, power_uw: null, final_diff_v: null, functional: false }, verdicts: {}, error: String(e) })
    } finally {
      if (timerRef.current) clearInterval(timerRef.current)
      setRunning(false)
    }
  }

  const runOptimize = async () => {
    setOptimizing(true)
    setOpt(null)
    setElapsed(0)
    const t0 = performance.now()
    timerRef.current = window.setInterval(() => setElapsed((performance.now() - t0) / 1000), 100)
    try {
      // capture the "before" transient + a real Monte-Carlo offset on the starting design
      const beforeWf = await waveform(params).catch(() => null)
      const beforeSim = await simulate(params, true).catch(() => null)
      const res = await optimize(params, targets)
      setOpt(res)
      if (!res.error) {
        setPlay({ steps: res.trajectory, idx: 0, auto: true }) // replay the search on the schematic
        setPage('optimizer') // surface the search result
        setMcBefore(beforeSim && !beforeSim.error ? beforeSim.offset ?? null : null)
        setParams(res.final_params)
        const fr: SimResult = { ...res.final_result, verdicts: res.verdicts }
        setResult(fr)
        setHistory((h) => [{ id: idRef.current++, params: structuredClone(res.final_params), result: fr, doOffset: true }, ...h].slice(0, 8))
        // "after" transient (optimized) on top, "before" faint underneath
        const afterWf = await waveform(res.final_params).catch(() => null)
        if (afterWf && !afterWf.error) {
          setWf(afterWf)
          setWfBefore(beforeWf && !beforeWf.error ? beforeWf : null)
        }
      }
    } catch (e) {
      setOpt({ trajectory: [], final_params: params, final_result: {} as SimResult, verdicts: {}, success: false, targets: {}, error: String(e) })
    } finally {
      if (timerRef.current) clearInterval(timerRef.current)
      setOptimizing(false)
    }
  }

  const busy = running || optimizing
  const dispDevices = play ? play.steps[play.idx].params : params.devices
  const stepChanged: DeviceKey | null = (() => {
    if (!play || play.idx === 0) return null
    const cur = play.steps[play.idx].params
    const prev = play.steps[play.idx - 1].params
    for (const k of Object.keys(cur) as DeviceKey[]) {
      if (cur[k].w_um !== prev[k].w_um || cur[k].m !== prev[k].m) return k
    }
    return null
  })()
  const stepNow = play ? play.steps[play.idx] : null
  const nom = result?.nominal
  const off = result?.offset
  const measured: Record<TargetKey, number | null> = {
    decision_time_ps: nom?.decision_time_ps ?? null,
    power_uw: nom?.power_uw ?? null,
    offset_sigma_mv: off?.offset_sigma_mv ?? null,
    noise_uv_rms: nom?.noise_uv_rms ?? null,
  }
  const applyProfile = (id: string) => {
    const prof = SPEC_PROFILES.find((p) => p.id === id)
    if (prof) {
      setProfile(id)
      setTargets({ ...prof.targets })
    }
  }
  const editTarget = (k: TargetKey, v: number) => {
    setProfile('custom')
    setTargets((t) => ({ ...t, [k]: v }))
  }
  const allPass = result && !result.error && Object.values(result.verdicts).every((v) => v === true)

  const pageTitle = t(lang, NAV_LABELS[page])
  const domain = domainOf(page)
  const navList = domain === 'vco' ? NAV_VCO : NAV_COMPARATOR
  const accent = domain === 'vco' ? 'var(--ag)' : 'var(--si)'      // VCO world reads in indigo, comparator in teal
  return (
    <div className="min-h-screen flex">
      {/* SIDEBAR */}
      <aside className="shrink-0 sticky top-0 self-start h-screen flex flex-col" style={{ width: 210, borderRight: '1px solid var(--line-soft)', background: 'var(--surface-2)' }}>
        <div className="px-4 py-4 flex items-center gap-2.5" style={{ borderBottom: '1px solid var(--line-soft)' }}>
          <div className="relative w-8 h-8 rounded-lg overflow-hidden shrink-0" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }} aria-hidden>
            <div className="absolute top-1/2 left-0 w-1/3 h-[2px]" style={{ background: 'var(--si)', boxShadow: '0 0 8px var(--si)', animation: 'sweep 2.2s linear infinite' }} />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold leading-tight" style={{ color: 'var(--text)' }}>StrongARM</div>
            <div className="mono text-[10px]" style={{ color: 'var(--faint)' }}>{t(lang, UI.appSub)}</div>
          </div>
        </div>
        {/* domain switch — Comparator vs VCO are two separate worlds */}
        <div className="grid grid-cols-2 gap-1.5 p-2" style={{ borderBottom: '1px solid var(--line-soft)' }}>
          {([['comparator', '⚖', 'var(--si)', UI.domainComparator], ['vco', '∿', 'var(--ag)', UI.domainVco]] as const).map(([d, glyph, col, label]) => {
            const on = domain === d
            return (
              <button key={d} onClick={() => setPage(DOMAIN_HOME[d])}
                className="flex flex-col items-center gap-0.5 py-2 rounded-lg transition-colors"
                style={{ background: on ? `color-mix(in srgb, ${col} 16%, transparent)` : 'var(--surface)', border: `1px solid ${on ? col : 'var(--line)'}` }}>
                <span className="text-base" style={{ color: on ? col : 'var(--faint)' }}>{glyph}</span>
                <span className="mono text-[10px] tracking-wide" style={{ color: on ? 'var(--text)' : 'var(--muted)' }}>{t(lang, label)}</span>
              </button>
            )
          })}
        </div>
        <nav className="flex flex-col gap-1 p-2 overflow-y-auto">
          {navList.map((n) => {
            const on = page === n.id
            return (
              <button
                key={n.id}
                onClick={() => setPage(n.id)}
                className="flex items-start gap-2.5 px-3 py-2 rounded-lg text-left"
                style={{ background: on ? `color-mix(in srgb, ${accent} 13%, transparent)` : 'transparent', border: `1px solid ${on ? `color-mix(in srgb, ${accent} 35%, var(--line))` : 'transparent'}` }}
              >
                <span className="mono text-sm mt-0.5" style={{ color: on ? accent : 'var(--faint)' }}>{n.glyph}</span>
                <span className="min-w-0">
                  <span className="block text-sm" style={{ color: on ? 'var(--text)' : 'var(--muted)' }}>{t(lang, NAV_LABELS[n.id])}</span>
                  <span className="block mono text-[10px]" style={{ color: 'var(--faint)' }}>{t(lang, NAV_SUBS[n.id])}</span>
                </span>
              </button>
            )
          })}
        </nav>
        <div className="mt-auto p-3 flex flex-col gap-2" style={{ borderTop: '1px solid var(--line-soft)' }}>
          <div className="mono text-[11px] flex items-center gap-2" style={{ color: 'var(--muted)' }}>
            <span className="inline-block w-2 h-2 rounded-full" style={{ background: apiUp === null ? 'var(--faint)' : apiUp ? 'var(--good)' : 'var(--bad)' }} />
            {apiUp === null ? t(lang, UI.connecting) : apiUp ? t(lang, UI.backendLive) : t(lang, UI.backendOff)}
          </div>
          <div className="flex gap-2 flex-wrap">
            <button onClick={() => setLang(lang === 'ko' ? 'en' : 'ko')} className="mono text-xs px-3 py-1.5 rounded-full" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }} title="한국어 / English">🌐 {lang === 'ko' ? 'EN' : '한'}</button>
            <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} className="mono text-xs px-3 py-1.5 rounded-full" style={{ color: 'var(--muted)', border: '1px solid var(--line)' }}>◐ {t(lang, UI.theme)}</button>
            <button onClick={downloadReport} disabled={!result} className="mono text-xs px-3 py-1.5 rounded-full disabled:opacity-40" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }} title="Download a Markdown report of the current design + results">⤓ {t(lang, UI.report)}</button>
          </div>
        </div>
      </aside>

      {/* MAIN */}
      <main className="flex-1 min-w-0">
        <div className="max-w-[1000px] mx-auto px-6 py-7 flex flex-col gap-5">
          <div className="flex items-baseline justify-between gap-4">
            <h1 className="text-lg font-semibold" style={{ color: 'var(--text)' }}>{pageTitle}</h1>
            <div className="mono text-[11px]" style={{ color: 'var(--faint)' }}>StrongARM latch · BSIM4 PTM 45nm</div>
          </div>

          {/* beginner-friendly explanation for the current page (KO/EN) */}
          <PageHelp page={page} lang={lang} />

          {page === 'sizing' && (
            <div className="grid gap-6" style={{ gridTemplateColumns: 'minmax(0, 420px) 1fr' }}>
              {/* controls */}
              <section className="flex flex-col gap-5">
          <div className="flex gap-2 flex-wrap">
            {PRESETS.map((p) => (
              <button
                key={p.name}
                disabled={busy}
                onClick={() => updateParams(p.patch(params))}
                className="text-left rounded-lg px-3 py-2 disabled:opacity-50"
                style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}
              >
                <div className="text-sm" style={{ color: 'var(--text)' }}>{p.name}</div>
                <div className="mono text-[10px]" style={{ color: 'var(--faint)' }}>{p.note}</div>
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="mono text-[11px] uppercase tracking-wider" style={{ color: 'var(--faint)' }}>Model</span>
            {([['ptm', 'PTM 45nm', 1.0], ['sky130', 'SKY130 (real)', 1.8]] as const).map(([m, label, v]) => {
              const on = (params.model ?? 'ptm') === m
              return (
                <button
                  key={m}
                  disabled={busy}
                  onClick={() => updateParams({ ...params, model: m, vdd: v })}
                  className="mono text-[11px] px-2.5 py-1 rounded-lg disabled:opacity-50"
                  style={{ color: on ? 'var(--si)' : 'var(--muted)', background: on ? 'color-mix(in srgb, var(--si) 12%, transparent)' : 'transparent', border: `1px solid ${on ? 'color-mix(in srgb, var(--si) 35%, var(--line))' : 'var(--line)'}` }}
                >
                  {label}
                </button>
              )
            })}
          </div>

          <DeviceEditor params={params} onChange={updateParams} disabled={busy} lang={lang} />

          <div className="grid grid-cols-3 gap-3">
            {([
              ['vdd', 'VDD (V)', 0.05],
              ['cload_ff', 'C_load (fF)', 1],
              ['n_mc', 'n_MC', 1],
            ] as const).map(([k, label, step]) => (
              <label key={k} className="flex flex-col gap-1">
                <span className="mono text-[11px] uppercase tracking-wider" style={{ color: 'var(--faint)' }}>{label}</span>
                <input
                  type="number"
                  step={step}
                  min={0}
                  disabled={busy}
                  value={params[k]}
                  onChange={(e) => setParams({ ...params, [k]: parseFloat(e.target.value) || 0 })}
                />
              </label>
            ))}
          </div>

          <label className="flex items-center gap-2.5 select-none cursor-pointer">
            <input type="checkbox" checked={doOffset} disabled={busy} onChange={(e) => setDoOffset(e.target.checked)} style={{ accentColor: 'var(--si)' }} />
            <span className="text-sm" style={{ color: 'var(--text)' }}>Measure offset (Monte-Carlo)</span>
            <span className="mono text-[11px]" style={{ color: 'var(--faint)' }}>{doOffset ? '~20s' : 'fast'}</span>
          </label>

          <div className="grid gap-2.5" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <button
              onClick={() => run()}
              disabled={busy || apiUp === false}
              className="rounded-xl py-3 font-semibold text-[15px] transition-opacity disabled:opacity-60"
              style={{ background: 'var(--si)', color: '#04120f' }}
            >
              {running ? `Simulating…  ${elapsed.toFixed(1)}s` : apiUp === false ? 'Backend offline' : '▶  Run SPICE'}
            </button>
            <button
              onClick={runOptimize}
              disabled={busy || apiUp === false}
              className="rounded-xl py-3 font-semibold text-[15px] transition-opacity disabled:opacity-60"
              style={{ background: 'var(--ag)', color: '#0b0820' }}
              title="Autonomous search: adjusts W and M until the spec is met"
            >
              {optimizing ? `Searching…  ${elapsed.toFixed(1)}s` : '◴  Auto-find W & M'}
            </button>
          </div>
          {apiUp === false && (
            <p className="mono text-xs" style={{ color: 'var(--muted)' }}>
              Start the bridge: <span style={{ color: 'var(--si)' }}>python3 server.py</span> in webapp/
            </p>
          )}
        </section>

              {/* spec + measured details */}
              <section className="flex flex-col gap-5">
                <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: `1px solid ${allPass ? 'color-mix(in srgb, var(--good) 45%, var(--line))' : 'var(--line)'}` }}>
                  <div className="flex items-center justify-between mb-4">
                    <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>
                      Spec compliance · {profile === 'custom' ? 'custom targets' : SPEC_PROFILES.find((p) => p.id === profile)?.label}
                    </div>
                    {result && !result.error && (
                      <div className="mono text-xs px-2.5 py-1 rounded-full" style={{ color: allPass ? 'var(--good)' : 'var(--warn)', background: `color-mix(in srgb, ${allPass ? 'var(--good)' : 'var(--warn)'} 14%, transparent)` }}>
                        {allPass ? 'ALL PASS' : 'SPEC MISS'}
                      </div>
                    )}
                  </div>
                  {/* spec profile selector + editable target limits */}
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    {SPEC_PROFILES.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => applyProfile(p.id)}
                        title={p.note}
                        className="mono text-[11px] px-2.5 py-1 rounded-full transition-colors"
                        style={{
                          color: profile === p.id ? 'var(--bg)' : 'var(--muted)',
                          background: profile === p.id ? 'var(--si)' : 'transparent',
                          border: `1px solid ${profile === p.id ? 'var(--si)' : 'var(--line)'}`,
                        }}
                      >
                        {p.label}
                      </button>
                    ))}
                    {profile === 'custom' && <span className="mono text-[11px] px-2.5 py-1 rounded-full" style={{ color: 'var(--warn)', border: '1px solid color-mix(in srgb, var(--warn) 40%, var(--line))' }}>custom</span>}
                  </div>
                  <div className="grid grid-cols-2 gap-2 mb-4">
                    {TARGET_KEYS.map((k) => (
                      <label key={k} className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5" style={{ background: 'var(--surface-2)', border: '1px solid var(--line)' }}>
                        <span className="mono text-[10px]" style={{ color: 'var(--faint)' }}>{TARGET_META[k].label} ≤</span>
                        <span className="flex items-center gap-1">
                          <input
                            type="number"
                            value={targets[k]}
                            step={TARGET_META[k].step}
                            min={0}
                            onChange={(e) => editTarget(k, Number(e.target.value))}
                            className="mono text-xs w-14 text-right bg-transparent outline-none"
                            style={{ color: 'var(--text)' }}
                          />
                          <span className="mono text-[10px]" style={{ color: 'var(--faint)' }}>{TARGET_META[k].unit}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                  {result?.error ? (
                    <p className="mono text-sm" style={{ color: 'var(--bad)' }}>error: {result.error}</p>
                  ) : (
                    <div className="flex flex-col gap-4">
                      {TARGET_KEYS.map((k) => (
                        <Gauge key={k} label={TARGET_META[k].label} value={measured[k]} limit={targets[k]} unit={TARGET_META[k].unit} pass={measured[k] == null ? null : measured[k]! <= targets[k]} />
                      ))}
                      {!result && <p className="text-sm" style={{ color: 'var(--muted)' }}>Set the device sizing and run a SPICE simulation to see the measured metrics against the selected spec targets.</p>}
                    </div>
                  )}
                </div>
                {result && !result.error && (
                  <div className="grid grid-cols-2 gap-3">
                    <Detail label="Resolved" value={nom?.functional ? 'latched to rail' : 'did not resolve'} ok={nom?.functional} />
                    <Detail label="Final Δout" value={nom?.final_diff_v != null ? `${nom.final_diff_v} V` : '—'} />
                    {off && <Detail label="Pelgrom σ_Vth" value={`${off.pelgrom_sigma_vth_mv} mV`} />}
                    {off && <Detail label="offset mean" value={`${off.offset_mean_mv} mV (n=${off.n_mc})`} />}
                  </div>
                )}
              </section>
            </div>
          )}

          {page === 'circuit' && (
            <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
              <div className="flex items-center justify-between mb-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Circuit &amp; transient · V(out) vs t</div>
                <div className="flex gap-2">
                  <button onClick={() => void loadWaveform(params)} disabled={busy || wfLoading} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--muted)', border: '1px solid var(--line)' }}>
                    {wfLoading ? 'simulating…' : '↻ waveform'}
                  </button>
                  <button onClick={runPostLayout} disabled={busy || plLoading} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                    {plLoading ? 'extracting…' : '⚡ parasitics'}
                  </button>
                  <button onClick={() => downloadNetlist('/api/netlist', params, 'strongarm.sp').catch(() => {})} className="mono text-[11px] px-2.5 py-1 rounded-full" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }}
                    title="현재 파라미터의 SPICE 덱(.sp) 다운로드 — ngspice 로 직접 실행 가능">
                    ⤓ netlist
                  </button>
                </div>
              </div>
              {play && stepNow && (
                <div className="mb-3 rounded-lg px-3 py-2 flex items-center justify-between flex-wrap gap-2" style={{ background: 'color-mix(in srgb, var(--ag) 10%, transparent)', border: '1px solid color-mix(in srgb, var(--ag) 30%, var(--line))' }}>
                  <div className="mono text-[11px]" style={{ color: 'var(--ag)' }}>◴ step {play.idx + 1}/{play.steps.length} · {stepNow.action}</div>
                  <div className="mono text-[11px] tnum" style={{ color: 'var(--muted)' }}>
                    {stepNow.total_w_um != null && <>ΣW {stepNow.total_w_um}µm</>}
                    {stepNow.measured && <> · {stepNow.measured.decision_time_ps ?? '—'}ps · <span style={{ color: 'var(--ag)' }}>{stepNow.measured.power_uw ?? '—'}µW</span>{stepNow.measured.offset_sigma_mv != null ? ` · ${stepNow.measured.offset_sigma_mv}mV` : ''}</>}
                  </div>
                </div>
              )}
              <div className="grid gap-4 items-center" style={{ gridTemplateColumns: '1fr 1fr' }}>
                <Schematic devices={dispDevices} changed={stepChanged} />
                <div className="min-w-0">
                  {wf ? (
                    <WaveformChart wf={wf} before={wfBefore} theme={theme} />
                  ) : (
                    <div className="text-sm flex items-center justify-center" style={{ height: 190, color: 'var(--muted)' }}>
                      {wfLoading ? 'capturing transient…' : 'Run a simulation to capture the transient.'}
                    </div>
                  )}
                  {wfBefore ? (
                    <p className="mono text-[11px] mt-1 leading-relaxed" style={{ color: 'var(--faint)' }}>
                      <span style={{ color: 'var(--faint)' }}>┄ before</span> {wfBefore.decision_ns} ns ·{' '}
                      <span style={{ color: 'var(--si)' }}>— optimized</span> {wf?.decision_ns} ns — overlaid pre/post Auto-find.
                    </p>
                  ) : (
                    <p className="mono text-[11px] mt-1 leading-relaxed" style={{ color: 'var(--faint)' }}>
                      Nodes precharge to V<sub>DD</sub>, split at the clock edge, and latch to the rails
                      {wf?.decision_ns != null && <> · decides ~{wf.decision_ns} ns</>}.
                    </p>
                  )}
                </div>
              </div>
              {postLayout && (
                <div className="mt-4 pt-4" style={{ borderTop: '1px solid var(--line-soft)' }}>
                  <div className="mono text-[11px] uppercase tracking-[0.16em] mb-2" style={{ color: 'var(--ag)' }}>Post-layout parasitics · schematic vs extracted</div>
                  <div className="grid gap-4 items-center" style={{ gridTemplateColumns: '1fr 1fr' }}>
                    <WaveformChart wf={postLayout.postlayout.waveform} before={postLayout.schematic.waveform} theme={theme} />
                    <div className="mono text-[12px] tnum flex flex-col gap-1.5" style={{ color: 'var(--muted)' }}>
                      {(() => {
                        const s = postLayout.schematic.nominal
                        const pl = postLayout.postlayout.nominal
                        const dd = (pl.decision_time_ps ?? 0) - (s.decision_time_ps ?? 0)
                        const dp = (pl.power_uw ?? 0) - (s.power_uw ?? 0)
                        return (
                          <>
                            <div><span style={{ color: 'var(--faint)' }}>┄ schematic</span> {s.decision_time_ps}ps · {s.power_uw}µW</div>
                            <div><span style={{ color: 'var(--si)' }}>— post-layout</span> {pl.decision_time_ps}ps · {pl.power_uw}µW</div>
                            <div style={{ color: 'var(--ag)' }}>Δ decision +{dd.toFixed(1)}ps · Δ power +{dp.toFixed(1)}µW</div>
                            <div style={{ color: 'var(--faint)' }}>routing + junction C at outp/outn/nX/nY (≈0.25 fF/µm of connected width)</div>
                          </>
                        )
                      })()}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {page === 'optimizer' && (
            <div className="flex flex-col gap-5">
              {opt && !opt.error ? (
                <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--ag)' }}>◴ Agent search · min power</div>
                    <div className="mono text-xs px-2.5 py-1 rounded-full" style={{ color: opt.success ? 'var(--good)' : 'var(--warn)', background: `color-mix(in srgb, ${opt.success ? 'var(--good)' : 'var(--warn)'} 14%, transparent)` }}>
                      {Object.values(opt.verdicts).every((v) => v === true) ? 'ALL SPECS MET' : opt.success ? 'OFFSET + SPEED MET' : 'PARTIAL'}
                    </div>
                  </div>
                  <div className="grid gap-4" style={{ gridTemplateColumns: 'minmax(0, 230px) 1fr' }}>
                    <div>
                      {stepNow && <div className="mono text-[11px] mb-1" style={{ color: 'var(--ag)' }}>replay · step {play!.idx + 1}/{play!.steps.length}</div>}
                      <Schematic devices={dispDevices} changed={stepChanged} />
                    </div>
                    <ol className="flex flex-col gap-1.5">
                      {opt.trajectory.map((s, i) => {
                        const m = s.measured
                        const active = play?.idx === i
                        return (
                          <li key={i} onClick={() => setPlay({ steps: opt.trajectory, idx: i, auto: false })} className="grid gap-2.5 items-start rounded-lg px-3 py-2 cursor-pointer" style={{ gridTemplateColumns: 'auto 1fr', background: 'var(--surface-2)', border: `1px solid ${active ? 'color-mix(in srgb, var(--ag) 55%, var(--line))' : 'var(--line-soft)'}` }} title="Show this step on the schematic">
                            <span className="mono text-[11px] mt-0.5" style={{ color: 'var(--faint)' }}>{i}</span>
                            <div className="min-w-0">
                              <div className="text-[13px]" style={{ color: 'var(--text)' }}>{s.action}</div>
                              <div className="mono text-[11px] tnum" style={{ color: 'var(--muted)' }}>
                                {s.total_w_um != null && <>ΣW {s.total_w_um}µm</>}
                                {s.predicted_offset_mv != null && <> · pred σ {s.predicted_offset_mv}mV</>}
                                {m && (<> · {m.decision_time_ps ?? '—'}ps · <span style={{ color: 'var(--ag)' }}>{m.power_uw ?? '—'}µW</span>{m.offset_sigma_mv != null ? ` · ${m.offset_sigma_mv}mV σ` : ''}</>)}
                              </div>
                            </div>
                          </li>
                        )
                      })}
                    </ol>
                  </div>
                  <p className="mono text-[11px] mt-3 leading-relaxed flex items-center justify-between gap-2" style={{ color: 'var(--faint)' }}>
                    <span>Power minimized to <span style={{ color: 'var(--ag)' }}>{opt.final_power_uw}µW</span> (ΣW {opt.final_total_w_um}µm) by trimming tail &amp; latch, offset held by the input pair — click a step to replay it on the schematic.</span>
                    <button onClick={() => downloadNetlist('/api/netlist', opt.final_params, 'strongarm_opt.sp').catch(() => {})} className="mono text-[11px] px-2.5 py-1 rounded-full shrink-0" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }}
                      title="최적화된 소자 크기가 반영된 SPICE 덱(.sp) 다운로드">
                      ⤓ netlist
                    </button>
                  </p>
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>{opt?.error ? `error: ${opt.error}` : 'Run “Auto-find W & M” on the Sizing page — the search trajectory replays here step by step.'}</p>
              )}
              <div>
                <div className="mono text-[11px] uppercase tracking-[0.16em] mb-2.5" style={{ color: 'var(--faint)' }}>Run history</div>
                {history.length === 0 ? (
                  <p className="text-sm" style={{ color: 'var(--muted)' }}>No runs yet.</p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {history.map((h) => {
                      const hp = Object.values(h.result.verdicts).every((v) => v === true)
                      const inp = h.params.devices.input
                      return (
                        <button key={h.id} onClick={() => updateParams(structuredClone(h.params))} className="grid gap-2 items-center rounded-lg px-3 py-2 text-left" style={{ gridTemplateColumns: '1fr auto', background: 'var(--surface)', border: '1px solid var(--line)' }} title="Load these params">
                          <div className="mono text-xs tnum truncate" style={{ color: 'var(--muted)' }}>
                            in {inp.w_um}µm/{inp.l_nm}n/×{inp.m} ·{' '}
                            <span style={{ color: 'var(--text)' }}>{h.result.nominal.decision_time_ps ?? '—'}ps</span> ·{' '}
                            <span style={{ color: 'var(--text)' }}>{h.result.nominal.power_uw ?? '—'}µW</span> ·{' '}
                            <span style={{ color: 'var(--text)' }}>{h.result.offset?.offset_sigma_mv ?? '—'}mV</span>
                          </div>
                          <span className="mono text-[10px] px-2 py-0.5 rounded-full shrink-0" style={{ color: hp ? 'var(--good)' : 'var(--bad)', background: `color-mix(in srgb, ${hp ? 'var(--good)' : 'var(--bad)'} 14%, transparent)` }}>
                            {hp ? 'PASS' : 'MISS'}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {page === 'montecarlo' && (
            <div className="flex flex-col gap-4">
            {/* MC 는 결과 뷰어였음 — 이 페이지에서 바로 돌릴 수 있게 실행 버튼 제공(오프셋 강제 on) */}
            <div className="flex items-center justify-between gap-3">
              <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Monte-Carlo · V_th mismatch → offset σ</div>
              <button onClick={() => run(true)} disabled={busy || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}
                title="현재 소자 크기로 n_MC회 미스매치 샘플링(ngspice)을 돌려 오프셋 분포를 측정">
                {running ? `sampling… ${elapsed.toFixed(0)}s` : `∿ run Monte-Carlo (n=${params.n_mc})`}
              </button>
            </div>
            {off?.samples_mv?.length ? (
              <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                <div className="flex items-center justify-between mb-3">
                  <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Monte-Carlo offset · {off.n_mc} samples</div>
                  <div className="mono text-xs px-2.5 py-1 rounded-full" style={{ color: result?.verdicts.offset_sigma_mv ? 'var(--good)' : 'var(--bad)', background: `color-mix(in srgb, ${result?.verdicts.offset_sigma_mv ? 'var(--good)' : 'var(--bad)'} 14%, transparent)` }}>
                    σ {off.offset_sigma_mv} mV
                  </div>
                </div>
                <MonteCarloChart offset={off} before={mcBefore} targetMv={targets.offset_sigma_mv} theme={theme} />
                <p className="mono text-[11px] mt-1 leading-relaxed" style={{ color: 'var(--faint)' }}>
                  Each dot is one random V<sub>th</sub>-mismatch draw; the input that flips the decision is its offset. Bars = histogram, shaded = ±σ ({off.offset_sigma_mv} mV), mean {off.offset_mean_mv} mV.{' '}
                  <span style={{ color: 'var(--si)' }}>Solid</span> = optimized fit.{' '}
                  {mcBefore ? (
                    <><span style={{ color: 'var(--faint)' }}>┄ dashed / outlined</span> = measured before optimization (σ {mcBefore.offset_sigma_mv} mV, {mcBefore.n_mc} samples) → after {off.offset_sigma_mv} mV. </>
                  ) : null}
                  Red dots fall outside ±{targets.offset_sigma_mv} mV. Raise n<sub>MC</sub> for a denser distribution.
                </p>
              </div>
            ) : (
              <p className="text-sm" style={{ color: 'var(--muted)' }}>
                아직 몬테카를로 결과가 없습니다 — 위의 <span className="mono" style={{ color: 'var(--ag)' }}>∿ run Monte-Carlo</span> 버튼을 누르면 현재 소자 크기로
                V<sub>th</sub> 미스매치를 {params.n_mc}회 무작위 추출해(ngspice) <b>입력 오프셋 분포·σ</b>를 측정합니다.
                (소자 크기 페이지에서 “오프셋 측정” 체크 후 실행해도 같은 결과가 여기 표시됩니다.)
              </p>
            )}
            </div>
          )}

          {page === 'pvt' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>PVT · worst-case across process / voltage / temperature</div>
                <button onClick={runPvt} disabled={busy || pvtLoading || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  {pvtLoading ? 'sweeping 27 corners…' : '◫ run PVT sweep'}
                </button>
              </div>
              {pvtRes ? (
                <>
                  <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                    <div className="flex flex-col gap-4">
                      {(['decision_time_ps', 'power_uw'] as const).map((k) => {
                        const val = pvtRes.worst[k]
                        const lim = targets[k]
                        return <Gauge key={k} label={`${TARGET_META[k].label} (worst corner)`} value={val} limit={lim} unit={TARGET_META[k].unit} pass={val == null ? null : val <= lim} />
                      })}
                      <div className="mono text-[11px]" style={{ color: pvtRes.worst.any_nonfunctional ? 'var(--bad)' : 'var(--good)' }}>
                        {pvtRes.worst.any_nonfunctional ? '✗ some corner failed to resolve' : '✓ resolves to a rail in all 27 corners'}
                      </div>
                    </div>
                  </div>
                  <div className="rounded-2xl p-4 overflow-x-auto" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                    {(['SS', 'TT', 'FF'] as const).map((proc) => (
                      <div key={proc} className="flex items-center gap-1.5 mb-1.5">
                        <span className="mono text-[11px] w-7 shrink-0" style={{ color: 'var(--muted)' }}>{proc}</span>
                        {pvtRes.corners.filter((c) => c.process === proc).map((c, i) => {
                          const pass = c.functional && c.decision_time_ps != null && c.decision_time_ps <= targets.decision_time_ps
                          return (
                            <div key={i} className="mono text-[9.5px] tnum rounded px-1 py-1 text-center shrink-0" style={{ minWidth: 50, color: pass ? 'var(--si)' : 'var(--bad)', background: `color-mix(in srgb, ${pass ? 'var(--si)' : 'var(--bad)'} 12%, transparent)`, border: `1px solid color-mix(in srgb, ${pass ? 'var(--si)' : 'var(--bad)'} 30%, var(--line))` }} title={`${c.process} · ${c.temp}°C · ${(c.v_frac * 100).toFixed(0)}% VDD (${c.vdd}V) → ${c.decision_time_ps}ps, ${c.power_uw}µW`}>
                              {c.decision_time_ps ?? '—'}
                            </div>
                          )
                        })}
                      </div>
                    ))}
                    <div className="mono text-[10px] mt-1.5 leading-relaxed" style={{ color: 'var(--faint)' }}>
                      each cell = decision (ps) at one corner; 9 cols = T(−40/27/125°C) × V(0.9/1.0/1.1×VDD); process = ±50 mV Vth skew (delvto). teal ≤ {targets.decision_time_ps} ps, red = miss. Nominal passing ≠ PVT passing.
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>Run the PVT sweep to check the current sizing across 27 process/voltage/temperature corners (worst-case sign-off).</p>
              )}
            </div>
          )}

          {page === 'pareto' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Pareto front · power ↔ decision-time (NSGA-II)</div>
                <button onClick={runPareto} disabled={busy || paretoLoading || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  {paretoLoading ? 'searching front…' : '⤢ run NSGA-II'}
                </button>
              </div>
              {paretoRes ? (
                <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                  <ParetoChart res={paretoRes} pTarget={targets.power_uw} dTarget={targets.decision_time_ps} theme={theme}
                    selected={paretoSel} onSelect={setParetoSel} />
                  <p className="mono text-[11px] mt-2 leading-relaxed" style={{ color: 'var(--faint)' }}>
                    <span style={{ color: 'var(--si)' }}>— front</span> = {paretoRes.front.length} non-dominated designs; faint dots = all evaluated (red = infeasible). Dashed = spec limits (≤{targets.power_uw}µW, ≤{targets.decision_time_ps}ps). Lower-left is better — click a front point for details.
                  </p>
                  {/* 선택점 상세: 측정값 + 소자 크기 + 적용/넷리스트 */}
                  {paretoSel != null && paretoRes.front[paretoSel] && (() => {
                    const pt = paretoRes.front[paretoSel]
                    return (
                      <div className="rounded-xl p-3 mt-3" style={{ background: 'color-mix(in srgb, var(--warn) 7%, var(--surface-2))', border: '1px solid color-mix(in srgb, var(--warn) 35%, var(--line))' }}>
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <div className="mono text-[11px] tnum" style={{ color: 'var(--text)' }}>
                            ◎ front #{paretoSel + 1} — <span style={{ color: 'var(--ag)' }}>{pt.power_uw}µW</span> · {pt.decision_time_ps}ps · σ(pred) {pt.offp}mV
                          </div>
                          <div className="flex gap-2">
                            <button onClick={() => updateParams({ ...params, devices: pt.devices })} className="mono text-[11px] px-2.5 py-1 rounded-full" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }} title="이 크기를 에디터에 로드">↧ 적용</button>
                            <button onClick={() => downloadNetlist('/api/netlist', { ...params, devices: pt.devices }, `strongarm_front${paretoSel + 1}.sp`).catch(() => {})} className="mono text-[11px] px-2.5 py-1 rounded-full" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }} title="이 크기의 SPICE 덱 다운로드">⤓ netlist</button>
                          </div>
                        </div>
                        <div className="grid gap-1.5 mt-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
                          {(Object.keys(pt.devices) as (keyof typeof pt.devices)[]).map((k) => (
                            <div key={String(k)} className="mono text-[10.5px] tnum rounded-lg px-2 py-1.5" style={{ background: 'var(--surface)', border: '1px solid var(--line-soft)' }}>
                              <span style={{ color: 'var(--si)' }}>{DEVICE_META[k]?.name ?? String(k)}</span>
                              <span style={{ color: 'var(--muted)' }}> {pt.devices[k].w_um}µ × {pt.devices[k].m}</span>
                              <div style={{ color: 'var(--faint)' }}>{DEVICE_META[k]?.role}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })()}
                  <div className="flex flex-col gap-1.5 mt-3">
                    {paretoRes.front.slice(0, 8).map((pt, i) => (
                      <button key={i} onClick={() => setParetoSel(i)} className="mono text-[11px] tnum text-left rounded-lg px-3 py-1.5" style={{ background: paretoSel === i ? 'color-mix(in srgb, var(--warn) 10%, var(--surface-2))' : 'var(--surface-2)', border: `1px solid ${paretoSel === i ? 'color-mix(in srgb, var(--warn) 40%, var(--line))' : 'var(--line-soft)'}`, color: 'var(--muted)' }} title="이 점의 상세 보기">
                        {pt.power_uw}µW · {pt.decision_time_ps}ps · σ {pt.offp}mV
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>Run NSGA-II to map the power ↔ speed Pareto front for the current L/M; click a front point to load that sizing.</p>
              )}
            </div>
          )}

          {page === 'metastability' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Metastability · decision time vs input amplitude</div>
                <button onClick={runMeta} disabled={busy || metaLoading || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  {metaLoading ? 'sweeping…' : '⧗ run sweep'}
                </button>
              </div>
              {metaRes ? (
                <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                  <MetastabilityChart res={metaRes} theme={theme} />
                  <div className="grid grid-cols-2 gap-3 mt-3">
                    <Detail label="Regeneration τ" value={metaRes.tau_ps != null ? `${metaRes.tau_ps} ps` : '—'} />
                    <Detail label="Min resolved input" value={metaRes.min_resolved_v != null ? `${(metaRes.min_resolved_v * 1e6).toFixed(1)} µV` : '—'} />
                  </div>
                  <p className="mono text-[11px] mt-3 leading-relaxed" style={{ color: 'var(--faint)' }}>
                    <span style={{ color: 'var(--si)' }}>— measured</span> decision time; <span style={{ color: 'var(--ag)' }}>-- fit</span> t = τ·ln(1/V<sub>in</sub>)+c. The slope is the regeneration time constant τ = C/g<sub>m,latch</sub>; as V<sub>in</sub> → 0 the resolve time diverges logarithmically (metastability).
                  </p>
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>Sweep the input differential amplitude to see the decision time diverge as V<sub>in</sub> shrinks, and extract the regeneration time constant τ.</p>
              )}
            </div>
          )}

          {page === 'sensitivity' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Sensitivity · which device moves each spec</div>
                <button onClick={runSens} disabled={busy || sensLoading || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  {sensLoading ? 'perturbing…' : '⇕ run sensitivity'}
                </button>
              </div>
              {sensRes ? (
                <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                  <SensitivityChart res={sensRes} />
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>Perturb each device width by ±10% to rank which device is the strongest lever for speed, power, and offset — a guide for manual tuning.</p>
              )}
            </div>
          )}

          {page === 'ber' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Noise / BER · decision error rate vs input</div>
                <button onClick={runBer} disabled={busy || berLoading || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  {berLoading ? 'computing…' : '⊹ compute BER'}
                </button>
              </div>
              {berRes ? (
                <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                  <BerChart res={berRes} theme={theme} />
                  <div className="grid grid-cols-2 gap-3 mt-3">
                    <Detail label="Input noise σ (gm)" value={`${berRes.noise_uv_rms} µV`} />
                    <Detail label="Offset σ (MC)" value={berRes.offset_sigma_mv != null ? `${berRes.offset_sigma_mv} mV` : '—'} />
                    <Detail label={`Min input @ BER ${berRes.ber_target} (noise)`} value={`${berRes.min_input_noise_uv} µV`} />
                    <Detail label={`Min input @ BER ${berRes.ber_target} (+offset)`} value={`${berRes.min_input_total_uv} µV`} />
                  </div>
                  <p className="mono text-[11px] mt-3 leading-relaxed" style={{ color: 'var(--faint)' }}>
                    <span style={{ color: 'var(--si)' }}>— noise floor</span> 0.5·erfc(V<sub>in</sub>/√2σ<sub>vn</sub>) from the SPICE-measured input-referred noise; <span style={{ color: 'var(--bad)' }}>— total</span> adds chip-to-chip offset (σ<sub>tot</sub>=√(σ<sub>vn</sub>²+σ<sub>os</sub>²)). Dashed = BER target. Analytic curve on measured σ — not a transient-noise Monte-Carlo.
                  </p>
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>Compute the decision error rate vs input amplitude from the measured input-referred noise and offset — the minimum detectable input for a target BER.</p>
              )}
            </div>
          )}

          {page === 'maxfclk' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Max clock rate · energy per conversion</div>
                <button onClick={runFclk} disabled={busy || fclkLoading || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  {fclkLoading ? 'sweeping…' : '⎍ sweep clock'}
                </button>
              </div>
              {fclkRes ? (
                <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                  <FclkChart res={fclkRes} theme={theme} />
                  <div className="grid grid-cols-3 gap-3 mt-3">
                    <Detail label="Max f_clk" value={fclkRes.max_fclk_ghz != null ? `${fclkRes.max_fclk_ghz} GHz` : 'none'} ok={fclkRes.max_fclk_ghz != null} />
                    <Detail label="Min period" value={fclkRes.min_period_ns != null ? `${fclkRes.min_period_ns} ns` : '—'} />
                    <Detail label="Energy / conv" value={fclkRes.energy_fj_at_max != null ? `${fclkRes.energy_fj_at_max} fJ` : '—'} />
                  </div>
                  <p className="mono text-[11px] mt-3 leading-relaxed" style={{ color: 'var(--faint)' }}>
                    <span style={{ color: 'var(--si)' }}>● ok</span> = resolves in the evaluate phase and precharges back within reset; <span style={{ color: 'var(--bad)' }}>● fail</span> = one of those runs out of time. Max f_clk is the fastest passing rate; energy/conversion = avg supply power × period at that rate.
                  </p>
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>Sweep the clock period to find the maximum usable f<sub>clk</sub> (limited by evaluate + reset timing) and the energy per conversion — the comparator FoM.</p>
              )}
            </div>
          )}

          {page === 'yield' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Parametric yield · mismatch × PVT Monte-Carlo</div>
                <button onClick={runYield} disabled={busy || yieldLoading || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  {yieldLoading ? 'sampling…' : '⊞ run yield (48)'}
                </button>
              </div>
              {yieldRes ? (
                <div className="rounded-2xl p-5" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                  <YieldView res={yieldRes} />
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>Draw chips from Vth mismatch × random process/temp/VDD and count the fraction meeting offset ≤ {targets.offset_sigma_mv} mV and decision ≤ {targets.decision_time_ps} ps — the production yield that couples mismatch and corner variation.</p>
              )}
            </div>
          )}

          {domain === 'vco' && <VcoPage view={VCO_VIEW[page]} lang={lang} theme={theme} />}

          {page === 'flow' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Full flow · size → post-layout → PVT → layout/GDS</div>
                <button onClick={runFlow} disabled={busy || flowLoading || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  {flowLoading ? 'running flow… (~60s)' : '⇉ run full flow'}
                </button>
              </div>
              {flowRes ? (
                <div className="rounded-2xl p-5 flex flex-col gap-3" style={{ background: 'var(--surface)', border: `1px solid ${flowRes.overall ? 'color-mix(in srgb, var(--good) 45%, var(--line))' : 'var(--line)'}` }}>
                  <div className="flex items-center justify-between">
                    <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>end-to-end verdict</div>
                    <div className="mono text-xs px-2.5 py-1 rounded-full" style={{ color: flowRes.overall ? 'var(--good)' : 'var(--warn)', background: `color-mix(in srgb, ${flowRes.overall ? 'var(--good)' : 'var(--warn)'} 14%, transparent)` }}>{flowRes.overall ? 'SIGNED OFF' : 'NOT CLEAN'}</div>
                  </div>
                  {flowRes.stages.map((s, i) => (
                    <div key={i} className="flex items-start gap-3 rounded-lg px-3 py-2" style={{ background: 'var(--surface-2)', border: '1px solid var(--line-soft)' }}>
                      <span className="mono text-xs mt-0.5" style={{ color: s.ok ? 'var(--good)' : 'var(--bad)' }}>{s.ok ? '✓' : '✗'}</span>
                      <div><div className="text-[13px]" style={{ color: 'var(--text)' }}>{i + 1}. {s.name}</div><div className="mono text-[11px]" style={{ color: 'var(--muted)' }}>{s.detail}</div></div>
                    </div>
                  ))}
                  <p className="mono text-[11px]" style={{ color: 'var(--faint)' }}>DE-sized design ({flowRes.final_power_uw}µW) applied to the editor.</p>
                  {flowRes.layout && (
                    <div className="pt-3" style={{ borderTop: '1px solid var(--line-soft)' }}>
                      <div className="mono text-[11px] uppercase tracking-[0.16em] mb-2" style={{ color: 'var(--faint)' }}>Layout (GDSII) · {flowRes.layout.area_um2}µm² · {flowRes.layout.drc.clean ? 'DRC clean' : `${flowRes.layout.drc.n_violations} DRC violations`}</div>
                      <LayoutView data={flowRes.layout} />
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>Run the full flow: DE sizing (+ GP surrogate, MC offset) → post-layout parasitic re-sim → PVT sign-off → GDSII layout + DRC, with a per-stage verdict and the final layout (~60 s).</p>
              )}
            </div>
          )}

          {page === 'layout' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-3">
                <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Layout · GDSII synthesis + rule DRC</div>
                <button onClick={runLayout} disabled={busy || layoutLoading || apiUp === false} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
                  {layoutLoading ? 'synthesizing…' : '▧ generate layout'}
                </button>
              </div>
              {layoutRes ? (
                <div className="rounded-2xl p-5 flex flex-col gap-3" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
                  <LayoutView data={layoutRes} />
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {layoutRes.layers.filter((l) => l.rects.length).map((l) => (
                      <span key={l.name} className="mono text-[10px] flex items-center gap-1.5" style={{ color: 'var(--muted)' }}>
                        <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: l.color }} />{l.name} ({l.gds})
                      </span>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-4 items-center">
                    <span className="mono text-[12px]" style={{ color: 'var(--text)' }}>cell area <span className="tnum">{layoutRes.area_um2}</span> µm²</span>
                    <span className="mono text-xs px-2.5 py-1 rounded-full" style={{ color: layoutRes.drc.clean ? 'var(--good)' : 'var(--bad)', background: `color-mix(in srgb, ${layoutRes.drc.clean ? 'var(--good)' : 'var(--bad)'} 14%, transparent)` }}>{layoutRes.drc.clean ? 'DRC CLEAN' : `${layoutRes.drc.n_violations} DRC violations`}</span>
                  </div>
                  <p className="mono text-[11px] leading-relaxed" style={{ color: 'var(--faint)' }}>
                    Multi-finger MOS + nwell + guard ring on SKY130 stream layers. Rule DRC: {layoutRes.drc.rules}. GDSII written to <span style={{ color: 'var(--si)' }}>{layoutRes.gds_path}</span> (opens in KLayout/Magic). PoC layout, not sign-off DRC.
                  </p>
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--muted)' }}>Generate a transistor-level GDSII layout from the current sizing (multi-finger devices, nwell, guard ring) + a rule DRC check.</p>
              )}
            </div>
          )}

          <p className="mono text-[11px]" style={{ color: 'var(--faint)' }}>
            {ngspice ? `ngspice: ${ngspice}` : ''} · model: BSIM4 PTM 45nm bulk · offset via Monte-Carlo Vth mismatch
          </p>
        </div>
      </main>
    </div>
  )
}

function Detail({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="rounded-xl px-3.5 py-3" style={{ background: 'var(--surface-2)', border: '1px solid var(--line-soft)' }}>
      <div className="mono text-[10px] uppercase tracking-wider" style={{ color: 'var(--faint)' }}>{label}</div>
      <div className="mono text-sm mt-1" style={{ color: ok === undefined ? 'var(--text)' : ok ? 'var(--good)' : 'var(--bad)' }}>{value}</div>
    </div>
  )
}

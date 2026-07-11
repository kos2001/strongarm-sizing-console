import { useState } from 'react'
import type { LayoutResult, VcoDeviceKey, VcoFullflow, VcoOptimizeResult, VcoParams, VcoParetoResult, VcoPhaseNoise, VcoPushing, VcoPvtResult, VcoResult, VcoTuning, VcoWaveform } from '../types'
import { VCO_DEVICE_META } from '../types'
import { vcoFullflow, vcoLayout, vcoOptimize, vcoPareto, vcoPhaseNoise, vcoPushing, vcoPvt, vcoSimulate, vcoWaveform } from '../api'
import VcoPhaseNoiseChart from './VcoPhaseNoiseChart'
import TuningChart from './TuningChart'
import VcoSchematic from './VcoSchematic'
import { downloadNetlist } from '../netlist'
import VcoWaveformChart from './VcoWaveformChart'
import VcoPvtView from './VcoPvtView'
import VcoPushingChart from './VcoPushingChart'
import VcoParetoChart from './VcoParetoChart'
import LayoutView from './LayoutView'
import type { Lang } from '../i18n'

const VCO_DEFAULTS: VcoParams = {
  vdd: 1.0, vctrl: 0.6, n_stages: 3, cload_ff: 3.0, topology: 'xcpl',
  devices: {
    invp: { w_um: 2.0, l_nm: 45, m: 2 }, invn: { w_um: 1.0, l_nm: 45, m: 2 },
    starvep: { w_um: 2.0, l_nm: 45, m: 2 }, starven: { w_um: 1.0, l_nm: 45, m: 1 },
    xcplp: { w_um: 0.4, l_nm: 45, m: 1 }, rstp: { w_um: 2.0, l_nm: 45, m: 2 },
  },
}
const DKEYS: VcoDeviceKey[] = ['invp', 'invn', 'starvep', 'starven']
const XKEYS: VcoDeviceKey[] = [...DKEYS, 'xcplp', 'rstp']
const T = (l: Lang, ko: string, en: string) => (l === 'ko' ? ko : en)
type View = 'circuit' | 'main' | 'opt' | 'pvt' | 'pushing' | 'pareto' | 'layout' | 'flow' | 'pn'

export default function VcoPage({ lang, theme, view = 'main' }: { lang: Lang; theme: string; view?: View }) {
  const [params, setParams] = useState<VcoParams>(VCO_DEFAULTS)
  const [res, setRes] = useState<VcoResult | null>(null)
  const [tuning, setTuning] = useState<VcoTuning | null>(null)
  const [opt, setOpt] = useState<VcoOptimizeResult | null>(null)
  const [wf, setWf] = useState<VcoWaveform | null>(null)
  const [pvt, setPvt] = useState<VcoPvtResult | null>(null)
  const [push, setPush] = useState<VcoPushing | null>(null)
  const [pareto, setPareto] = useState<VcoParetoResult | null>(null)
  const [paretoSel, setParetoSel] = useState<number | null>(null) // 파레토 front 선택점(상세 패널)
  const [lay, setLay] = useState<LayoutResult | null>(null)
  const [flow, setFlow] = useState<VcoFullflow | null>(null)
  const [pn, setPn] = useState<VcoPhaseNoise | null>(null)
  const [load, setLoad] = useState('')
  const [targetF, setTargetF] = useState(1.5)
  const busy = load !== ''

  const setDev = (k: VcoDeviceKey, f: 'w_um' | 'l_nm' | 'm', v: number) =>
    setParams((p) => ({ ...p, devices: { ...p.devices, [k]: { ...p.devices[k], [f]: v } } }))
  const setTop = (f: 'vctrl' | 'n_stages' | 'cload_ff', v: number) => {
    // 링 단수 N 은 발진 조건상 홀수만 허용(짝수 입력은 위로 올림), 최소 3
    if (f === 'n_stages') v = Math.max(3, v % 2 === 0 ? v + 1 : v)
    setParams((p) => ({ ...p, [f]: v }))
  }
  // 토폴로지는 교차결합+리셋(xcpl) 단일 — 전류제한(starved) 회로는 제거됨
  const dkeys = XKEYS
  const topoBadge = (
    <span className="mono text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'var(--ag)', color: 'var(--bg)' }}>
      {T(lang, '교차결합+리셋', 'x-coupled+rst')}
    </span>
  )

  const guard = async (tag: string, fn: () => Promise<void>) => { setLoad(tag); try { await fn() } catch { /* ignore */ } finally { setLoad('') } }
  const run = () => guard('run', async () => { const r = await vcoSimulate(params, true); setRes(r); setTuning(r.tuning ?? null) })
  const optimize = () => guard('opt', async () => { const r = await vcoOptimize(params, targetF); if (!r.error) { setOpt(r); setParams((p) => ({ ...p, devices: { ...p.devices, ...r.final_params.devices } })); setRes({ nominal: r.nominal }); setTuning(r.tuning); setTimeout(() => document.getElementById('vco-tuning-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 150) } })
  const runWave = () => guard('wave', async () => { const w = await vcoWaveform(params); if (!w.error) setWf(w) })
  const runPvt = () => guard('pvt', async () => { const r = await vcoPvt(params); if (!r.error) setPvt(r) })
  const runPush = () => guard('push', async () => { const r = await vcoPushing(params); if (!r.error) setPush(r) })
  const runPareto = () => guard('pareto', async () => { const r = await vcoPareto(params); if (!r.error) setPareto(r) })
  const runLayout = () => guard('layout', async () => { const r = await vcoLayout(params); if (!r.error) setLay(r) })
  const runFlow = () => guard('flow', async () => { const r = await vcoFullflow(params); if (!r.error) { setFlow(r); setParams((p) => ({ ...p, devices: { ...p.devices, ...r.final_params.devices } })) } })
  const runPn = () => guard('pn', async () => { const r = await vcoPhaseNoise(params); if (!r.error) setPn(r) })

  const nom = res?.nominal
  const box: React.CSSProperties = { background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 14 }
  const lab = { color: 'var(--faint)' }
  const A = 'var(--ag)'
  const runBtn = (onClick: () => void, tag: string, label: string) => (
    <button onClick={onClick} disabled={busy} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50"
      style={{ color: A, border: `1px solid color-mix(in srgb, ${A} 40%, var(--line))` }}>{load === tag ? T(lang, '실행 중…', 'running…') : label}</button>
  )
  const hd = (title: string, action?: React.ReactNode) => (
    <div className="flex items-center justify-between gap-3 mb-3">
      <div className="mono text-[11px] uppercase tracking-[0.16em]" style={lab}>{title}</div>{action}
    </div>
  )

  // ---- circuit · waveform ----
  if (view === 'circuit') {
    return (
      <div className="flex flex-col gap-4">
        <div className="p-5" style={box}>
          {hd(T(lang, '회로도 · 발진 파형', 'schematic · oscillation'), <div className="flex items-center gap-2">{topoBadge}
            <button onClick={() => downloadNetlist('/api/vco/netlist', params, `vco_xcpl_N${params.n_stages}.sp`).catch(() => {})}
              className="mono text-xs px-3 py-1.5 rounded-full" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }}
              title={T(lang, '현재 파라미터의 SPICE 덱(.sp) 다운로드 — ngspice 로 직접 실행 가능', 'Download the SPICE deck (.sp) for the current parameters — runs directly in ngspice')}>
              ⤓ {T(lang, '넷리스트', 'netlist')}
            </button>
            {runBtn(runWave, 'wave', T(lang, '↻ 파형', '↻ waveform'))}</div>)}
          <div className="overflow-x-auto"><VcoSchematic devices={params.devices} nStages={params.n_stages} /></div>
          {wf ? (
            <div className="mt-4">
              <VcoWaveformChart wf={wf} theme={theme} labels={['o1', 'ob1']} />
              <p className="mono text-[11px] mt-2" style={lab}>
                {T(lang, '상보 링 노드(o1·ob1)의 실제 발진 — 리셋 해제 후 시작 — 주기', 'real oscillation of the complementary nodes (o1·ob1), starting on reset release — period')} {wf.period_ns} ns → {wf.f_osc_ghz} GHz</p>
            </div>
          ) : <p className="text-sm mt-3" style={{ color: 'var(--muted)' }}>{T(lang, '↻ 파형을 눌러 실제 발진 트랜지언트를 캡처하세요.', 'Press ↻ waveform to capture the real oscillation transient.')}</p>}
        </div>
      </div>
    )
  }

  // ---- PVT ----
  if (view === 'pvt') {
    return (
      <div className="p-5" style={box}>
        {hd(T(lang, 'PVT 코너 · 주파수 / 발진', 'PVT corners · frequency / oscillation'), runBtn(runPvt, 'pvt', T(lang, '◫ 27코너 실행', '◫ run 27 corners')))}
        {pvt ? <VcoPvtView pvt={pvt} lang={lang} /> : <p className="text-sm" style={{ color: 'var(--muted)' }}>{T(lang, '공정·전압·온도 27코너에서 발진 주파수와 발진 여부를 확인합니다.', 'Check oscillation frequency and startup across 27 process/voltage/temperature corners.')}</p>}
      </div>
    )
  }

  // ---- supply pushing ----
  if (view === 'pushing') {
    return (
      <div className="p-5" style={box}>
        {hd(T(lang, '전원 푸싱 · f vs VDD', 'supply pushing · f vs VDD'), runBtn(runPush, 'push', T(lang, '⇅ 스윕 실행', '⇅ run sweep')))}
        {push ? (
          <>
            <VcoPushingChart push={push} theme={theme} />
            <div className="mono text-[11px] mt-3 px-2.5 py-1.5 rounded-lg inline-block" style={{ color: A, background: `color-mix(in srgb, ${A} 12%, transparent)` }}>
              {T(lang, '푸싱', 'pushing')} = {push.pushing_ghz_per_v} GHz/V @ {push.nominal_vdd}V
            </div>
            <p className="mono text-[11px] mt-2" style={lab}>{T(lang, 'V_ctrl 고정, VDD를 흔들어 주파수가 얼마나 밀리는지 — 전원잡음 민감도.', 'Fixed V_ctrl; how much the supply moves the frequency — supply-noise sensitivity.')}</p>
          </>
        ) : <p className="text-sm" style={{ color: 'var(--muted)' }}>{T(lang, 'VDD를 ±15% 스윕해 주파수 푸싱(GHz/V)을 측정합니다.', 'Sweep VDD ±15% to measure frequency pushing (GHz/V).')}</p>}
      </div>
    )
  }

  // ---- phase noise / jitter ----
  if (view === 'pn') {
    return (
      <div className="p-5" style={box}>
        {hd(T(lang, '위상잡음 · L(Δf) / 지터', 'phase noise · L(Δf) / jitter'), runBtn(runPn, 'pn', T(lang, '⌇ 위상잡음 계산', '⌇ compute phase noise')))}
        {pn ? (
          <>
            <VcoPhaseNoiseChart pn={pn} theme={theme} />
            <div className="grid grid-cols-4 gap-3 mt-3">
              <Metric label="L(1MHz)" value={`${pn.L_1mhz_dbc} dBc/Hz`} big />
              <Metric label={T(lang, '주기 지터', 'period jitter')} value={`${pn.period_jitter_fs} fs`} />
              <Metric label="FoM" value={`${pn.fom_db} dB`} />
              <Metric label={T(lang, '유효 노드 C', 'C_eff / node')} value={`${pn.c_eff_ff} fF`} />
            </div>
            {pn.measured && (
              <div className="mono text-[11px] mt-3 px-2.5 py-1.5 rounded-lg" style={{ color: 'var(--si)', background: 'color-mix(in srgb, var(--si) 12%, transparent)' }}>
                {T(lang, 'SPICE trnoise 실측 교차검증', 'SPICE trnoise cross-check')}: L(1MHz) {pn.measured.L_1mhz_dbc} dBc/Hz · {T(lang, '지터', 'jitter')} {pn.measured.period_jitter_fs}±{pn.measured.jitter_spread_fs} fs ({pn.measured.n_seeds} {T(lang, '시드', 'seeds')}) · {T(lang, '해석 1/f² 영역과', 'vs analytic 1/f²')} {Math.abs(pn.L_1mhz_dbc - pn.measured.L_1mhz_dbc).toFixed(1)} dB
                {pn.measured.accum_slope != null && (
                  <span> · {T(lang, '지터-누적 기울기', 'jitter-accum slope')} {pn.measured.accum_slope} → {pn.measured.noise_type} {T(lang, '(관측 대역)', '(observed band)')}</span>
                )}
              </div>
            )}
            <p className="mono text-[11px] mt-3 leading-relaxed" style={lab}>
              {T(lang,
                '열잡음: 각 전이가 sqrt(kT·C)/I 만큼 흔들리고 주기당 2N 전이가 누적 → L(Δf)=10·log(f₀³·σ_T²/Δf²), −20dB/dec(1/f²). 근접 오프셋의 −30dB/dec(1/f³)는 가정된 플리커 코너(위 값)로 더한 것. — 실선=해석, 점선=SPICE trnoise 실측(다중 시드 평균, 열잡음 1/f² 영역만). 1차 모델이며 PSS/pnoise 사인오프는 아닙니다.',
                'Thermal: each transition jitters by sqrt(kT·C)/I, 2N per period accumulate → L(Δf)=10·log(f₀³·σ_T²/Δf²), −20 dB/dec (1/f²). The −30 dB/dec (1/f³) close-in is added from an assumed flicker corner (shown above). Solid = analytic, dashed = SPICE trnoise measured (multi-seed avg, thermal 1/f² region only). First-order model, not a PSS/pnoise sign-off.')}
            </p>
          </>
        ) : <p className="text-sm" style={{ color: 'var(--muted)' }}>{T(lang, '측정된 전력·주파수·단수로부터 열잡음 기반 위상잡음 L(Δf)·지터·FoM을 추정합니다 — VCO의 핵심 스펙.', 'Estimates thermal phase noise L(Δf), jitter, and FoM from the measured power, frequency, and stage count — the key VCO spec.')}</p>}
      </div>
    )
  }

  // ---- Pareto (power ↔ frequency, NSGA-II) ----
  if (view === 'pareto') {
    return (
      <div className="p-5" style={box}>
        {hd(T(lang, 'Pareto · 전력 ↔ 주파수 (NSGA-II)', 'Pareto · power ↔ frequency (NSGA-II)'), runBtn(runPareto, 'pareto', T(lang, '⤢ 프론트 탐색', '⤢ run NSGA-II')))}
        {pareto ? (
          <>
            <VcoParetoChart res={pareto} theme={theme} selected={paretoSel} onSelect={setParetoSel} />
            <p className="mono text-[11px] mt-2 leading-relaxed" style={lab}>
              <span style={{ color: A }}>— 프론트</span> = {pareto.front.length} {T(lang, '개 비지배 설계 (주파수별 최소 전력). 왼쪽-위가 우수(고주파·저전력) — 점을 클릭하면 상세.', 'non-dominated designs (min power per frequency). Upper-left is better — click a point for details.')}
            </p>
            {/* 선택점 상세: 측정값 + 소자 크기 + 적용/넷리스트 */}
            {paretoSel != null && pareto.front[paretoSel] && (() => {
              const pt = pareto.front[paretoSel]
              const merged = { ...params, devices: { ...params.devices, ...pt.devices } }
              return (
                <div className="rounded-xl p-3 mt-3" style={{ background: 'color-mix(in srgb, var(--warn) 7%, var(--surface-2))', border: '1px solid color-mix(in srgb, var(--warn) 35%, var(--line))' }}>
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="mono text-[11px] tnum" style={{ color: 'var(--text)' }}>
                      ◎ front #{paretoSel + 1} — <span style={{ color: A }}>{pt.f_osc_ghz} GHz</span> · {pt.power_uw} µW · N={params.n_stages}
                    </div>
                    <div className="flex gap-2">
                      <button onClick={() => setParams(merged)} className="mono text-[11px] px-2.5 py-1 rounded-full" style={{ color: A, border: `1px solid color-mix(in srgb, ${A} 40%, var(--line))` }} title={T(lang, '이 크기를 편집기에 로드', 'load into editor')}>↧ {T(lang, '적용', 'apply')}</button>
                      <button onClick={() => downloadNetlist('/api/vco/netlist', merged, `vco_front${paretoSel + 1}.sp`).catch(() => {})} className="mono text-[11px] px-2.5 py-1 rounded-full" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }} title={T(lang, '이 크기의 SPICE 덱 다운로드', 'download SPICE deck')}>⤓ {T(lang, '넷리스트', 'netlist')}</button>
                    </div>
                  </div>
                  <div className="grid gap-1.5 mt-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
                    {(Object.keys(pt.devices) as VcoDeviceKey[]).map((k) => (
                      <div key={k} className="mono text-[10.5px] tnum rounded-lg px-2 py-1.5" style={{ background: 'var(--surface)', border: '1px solid var(--line-soft)' }}>
                        <span style={{ color: 'var(--si)' }}>{VCO_DEVICE_META[k]?.name ?? k}</span>
                        <span style={{ color: 'var(--muted)' }}> {pt.devices[k]!.w_um}µ × {pt.devices[k]!.m}</span>
                        <div style={{ color: 'var(--faint)' }}>{VCO_DEVICE_META[k]?.role[lang]}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })()}
            <div className="flex flex-col gap-1.5 mt-3">
              {pareto.front.slice(0, 8).map((pt, i) => (
                <button key={i} onClick={() => setParetoSel(i)} className="mono text-[11px] tnum text-left rounded-lg px-3 py-1.5"
                  style={{ background: paretoSel === i ? 'color-mix(in srgb, var(--warn) 10%, var(--surface-2))' : 'var(--surface-2)', border: `1px solid ${paretoSel === i ? 'color-mix(in srgb, var(--warn) 40%, var(--line))' : 'var(--line-soft)'}`, color: 'var(--muted)' }} title={T(lang, '이 점의 상세 보기', 'show details')}>
                  {pt.f_osc_ghz} GHz · {pt.power_uw} µW
                </button>
              ))}
            </div>
          </>
        ) : <p className="text-sm" style={{ color: 'var(--muted)' }}>{T(lang, '전력↔주파수 트레이드오프의 최적 곡선을 NSGA-II로 찾습니다. 각 점을 눌러 그 설계를 로드.', 'NSGA-II maps the power ↔ frequency trade-off. Click a front point to load that design.')}</p>}
      </div>
    )
  }

  // ---- Layout (GDS + DRC) ----
  if (view === 'layout') {
    return (
      <div className="p-5" style={box}>
        {hd(T(lang, '레이아웃 · GDSII + DRC', 'layout · GDSII + DRC'), runBtn(runLayout, 'layout', T(lang, '▧ 레이아웃 생성', '▧ generate layout')))}
        {lay ? (
          <>
            <LayoutView data={lay} />
            <div className="flex flex-wrap gap-4 mt-3 mono text-[11px]" style={lab}>
              {lay.layers.map((l) => (<span key={l.name}><span className="sw" style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: l.color, marginRight: 5, verticalAlign: 'middle' }} />{l.name} ({l.gds})</span>))}
            </div>
            <div className="mono text-[11px] mt-3 px-2.5 py-1.5 rounded-lg inline-block" style={{ color: lay.drc.clean ? 'var(--good)' : 'var(--bad)', background: `color-mix(in srgb, ${lay.drc.clean ? 'var(--good)' : 'var(--bad)'} 12%, transparent)` }}>
              {T(lang, '셀 면적', 'cell area')} {lay.area_um2} µm² · {lay.drc.clean ? T(lang, 'DRC 통과', 'DRC CLEAN') : `${lay.drc.n_violations} DRC`}
            </div>
            <p className="mono text-[11px] mt-2" style={lab}>{T(lang, '바이어스 미러 + N단(각 Mbp/Mp/Mn/Mbn) 멀티핑거 MOS + 가드링. PoC 레이아웃(사인오프 DRC 아님).', 'bias mirror + N stages (Mbp/Mp/Mn/Mbn each) as multi-finger MOS + guard ring. PoC layout, not sign-off DRC.')}</p>
          </>
        ) : <p className="text-sm" style={{ color: 'var(--muted)' }}>{T(lang, '현재 소자 크기로 링 VCO의 트랜지스터 레벨 GDSII 레이아웃을 합성하고 규칙 DRC를 돌립니다.', 'Synthesize the transistor-level GDSII layout of the ring VCO from the current sizing and run rule DRC.')}</p>}
      </div>
    )
  }

  // ---- Full flow ----
  if (view === 'flow') {
    return (
      <div className="p-5" style={box}>
        {hd(T(lang, '전체 흐름 · 사이징 → 기생 → PVT → 레이아웃', 'full flow · size → parasitics → PVT → layout'), runBtn(runFlow, 'flow', T(lang, '⇉ 전체 실행', '⇉ run full flow')))}
        {flow ? (
          <>
            <div className="flex flex-col gap-2">
              {flow.stages.map((s, i) => (
                <div key={i} className="flex items-center gap-3 rounded-lg px-3 py-2" style={{ background: 'var(--surface-2)', border: `1px solid ${s.ok ? 'color-mix(in srgb, var(--good) 40%, var(--line))' : 'color-mix(in srgb, var(--bad) 40%, var(--line))'}` }}>
                  <span style={{ color: s.ok ? 'var(--good)' : 'var(--bad)' }}>{s.ok ? '✓' : '✗'}</span>
                  <span className="text-sm" style={{ color: 'var(--text)' }}>{s.name}</span>
                  <span className="mono text-[11px] ml-auto" style={lab}>{s.detail}</span>
                </div>
              ))}
            </div>
            <div className="mono text-sm mt-3 px-3 py-2 rounded-lg inline-block" style={{ color: flow.overall ? 'var(--good)' : 'var(--warn)', background: `color-mix(in srgb, ${flow.overall ? 'var(--good)' : 'var(--warn)'} 14%, transparent)` }}>
              {flow.overall ? T(lang, '전체 사인오프 ✓', 'SIGNED OFF ✓') : T(lang, '미완료', 'NOT CLEAN')}
            </div>
            {flow.layout && <div className="mt-4"><LayoutView data={flow.layout} /></div>}
          </>
        ) : <p className="text-sm" style={{ color: 'var(--muted)' }}>{T(lang, '자동 사이징 → 기생 재시뮬 → PVT 사인오프 → 레이아웃/DRC 를 한 번에 실행합니다.', 'Runs auto-size → parasitic re-sim → PVT sign-off → layout/DRC end to end.')}</p>}
      </div>
    )
  }

  // ---- main (sizing · tuning) & opt (auto-size): 2-column with editor ----
  return (
    <div className="grid gap-6" style={{ gridTemplateColumns: 'minmax(0,400px) 1fr' }}>
      <section className="flex flex-col gap-4">
        <div className="p-4" style={box}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <div className="mono text-[11px] uppercase tracking-[0.16em]" style={lab}>{T(lang, '링 VCO · 소자 크기', 'ring VCO · sizing')}</div>
            {topoBadge}
          </div>
          <div className="grid gap-2 mono text-[11px] uppercase tracking-wider px-1 mb-1" style={{ gridTemplateColumns: '1.6fr 1fr 1fr 0.7fr', color: 'var(--faint)' }}>
            <span>{T(lang, '소자', 'Device')}</span><span>W (µm)</span><span>L (nm)</span><span>M</span>
          </div>
          {dkeys.map((k) => (
            <div key={k} className="grid gap-2 items-center rounded-xl p-2.5 mb-2" style={{ gridTemplateColumns: '1.6fr 1fr 1fr 0.7fr', background: 'var(--surface-2)', border: '1px solid var(--line)', borderLeft: `3px solid ${A}` }}>
              <div className="min-w-0">
                <div className="mono text-sm" style={{ color: 'var(--text)' }}>{VCO_DEVICE_META[k].name}</div>
                <div className="text-xs truncate" style={{ color: 'var(--muted)' }}>{VCO_DEVICE_META[k].role[lang]}</div>
              </div>
              {(['w_um', 'l_nm', 'm'] as const).map((f) => (
                <input key={f} type="number" step={f === 'w_um' ? 0.5 : f === 'l_nm' ? 5 : 1} min={0} disabled={busy}
                  value={params.devices[k][f]} onChange={(e) => setDev(k, f, parseFloat(e.target.value) || 0)} />
              ))}
            </div>
          ))}
          <div className="grid grid-cols-3 gap-2 mt-2">
            {([['vctrl', 'V_ctrl (V)', 0.05], ['n_stages', T(lang, '단수 N', 'stages N'), 2], ['cload_ff', 'C_L (fF)', 0.5]] as const).map(([f, label, step]) => (
              <label key={f} className="mono text-[10px]" style={lab}>{label}
                <input type="number" step={step as number} min={f === 'n_stages' ? 3 : 0} disabled={busy}
                  value={params[f as 'vctrl' | 'n_stages' | 'cload_ff']} onChange={(e) => setTop(f as 'vctrl' | 'n_stages' | 'cload_ff', parseFloat(e.target.value) || 0)} style={{ width: '100%', marginTop: 3 }} />
              </label>
            ))}
          </div>
        </div>
        {view === 'main' ? (
          <button onClick={run} disabled={busy} className="py-2.5 rounded-xl font-medium disabled:opacity-50" style={{ background: A, color: 'var(--bg)' }}>
            {load === 'run' ? T(lang, '시뮬레이션 중…', 'simulating…') : T(lang, '▶ VCO 실행 (튜닝 포함)', '▶ Run VCO (with tuning)')}
          </button>
        ) : (
          <div className="flex gap-2 items-center rounded-xl p-2.5" style={{ background: 'var(--surface-2)', border: '1px solid var(--line)' }}>
            <span className="mono text-[11px]" style={lab}>{T(lang, '목표 f', 'target f')}</span>
            <input type="number" step={0.1} min={0.1} disabled={busy} value={targetF} onChange={(e) => setTargetF(parseFloat(e.target.value) || 0)} style={{ width: 64 }} />
            <span className="mono text-[11px]" style={lab}>GHz</span>
            {runBtn(optimize, 'opt', T(lang, '◴ 자동 사이징 실행', '◴ Run auto-size'))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <div className="p-5" style={box}>
          <div className="mono text-[11px] uppercase tracking-[0.16em] mb-4" style={lab}>{T(lang, '발진 측정', 'oscillation metrics')}</div>
          {res?.error ? <p className="mono text-sm" style={{ color: 'var(--bad)' }}>error: {res.error}</p> : (
            <div className="grid grid-cols-2 gap-3">
              <Metric label={T(lang, '발진 주파수', 'osc. frequency')} value={nom?.f_osc_ghz != null ? `${nom.f_osc_ghz} GHz` : '—'} big />
              <Metric label={T(lang, '발진 여부', 'oscillates')} value={nom ? (nom.oscillates ? T(lang, '발진함 ✓', 'yes ✓') : T(lang, '발진 안 함 ✗', 'no ✗')) : '—'} ok={nom?.oscillates} />
              <Metric label={T(lang, '전력', 'power')} value={nom?.power_uw != null ? `${nom.power_uw} µW` : '—'} />
              <Metric label={T(lang, '출력 스윙', 'swing (Vpp)')} value={nom?.vpp_v != null ? `${nom.vpp_v} V` : '—'} />
              {!res && <p className="col-span-2 text-sm" style={{ color: 'var(--muted)' }}>{T(lang, '소자 크기를 정하고 VCO를 실행하면 발진 주파수·전력·튜닝 곡선이 나옵니다.', 'Set the device sizes and run the VCO to see oscillation frequency, power, and the tuning curve.')}</p>}
            </div>
          )}
          {view === 'opt' && opt && (
            <div className="mono text-[11px] mt-3 px-2.5 py-1.5 rounded-lg flex items-center justify-between gap-2" style={{ color: opt.success ? 'var(--good)' : 'var(--warn)', background: `color-mix(in srgb, ${opt.success ? 'var(--good)' : 'var(--warn)'} 12%, transparent)` }}>
              <span>{opt.success ? '✓' : '≈'} {T(lang, '목표', 'target')} {opt.target_f_ghz} GHz → {opt.nominal.f_osc_ghz} GHz · {opt.nominal.power_uw} µW · {opt.n_sims} SPICE evals{opt.n_surrogate_skips ? ` · ${opt.n_surrogate_skips} ${T(lang, '스킵', 'skipped')}` : ''}</span>
              <button onClick={() => downloadNetlist('/api/vco/netlist', opt.final_params, `vco_xcpl_opt_N${opt.final_params.n_stages}.sp`).catch(() => {})}
                className="mono text-[11px] px-2.5 py-1 rounded-full shrink-0" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }}
                title={T(lang, '최적화된 소자 크기가 반영된 SPICE 덱(.sp) 다운로드', 'Download the SPICE deck (.sp) with the optimized device sizes')}>
                ⤓ {T(lang, '넷리스트', 'netlist')}
              </button>
            </div>
          )}
        </div>
        {tuning && (
          <div id="vco-tuning-card" className="p-5" style={box}>
            <div className="mono text-[11px] uppercase tracking-[0.16em] mb-3" style={lab}>{view === 'opt' ? T(lang, '최적화된 크기의 튜닝 곡선 · f vs V_ctrl', 'tuning curve of the optimized sizing · f vs V_ctrl') : T(lang, '튜닝 곡선 · f vs V_ctrl', 'tuning curve · f vs V_ctrl')}</div>
            <TuningChart tuning={tuning} theme={theme} />
            <div className="grid grid-cols-4 gap-3 mt-3">
              <Metric label={T(lang, '최소 f', 'f min')} value={tuning.f_min_ghz != null ? `${tuning.f_min_ghz} GHz` : '—'} />
              <Metric label={T(lang, '최대 f', 'f max')} value={tuning.f_max_ghz != null ? `${tuning.f_max_ghz} GHz` : '—'} />
              <Metric label={T(lang, '튜닝 범위', 'tuning range')} value={tuning.tuning_pct != null ? `${tuning.tuning_pct}%` : '—'} />
              <Metric label="Kvco" value={tuning.kvco_ghz_per_v != null ? `${tuning.kvco_ghz_per_v} GHz/V` : '—'} />
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

function Metric({ label, value, big, ok }: { label: string; value: string; big?: boolean; ok?: boolean }) {
  return (
    <div className="rounded-xl p-3" style={{ background: 'var(--surface-2)', border: '1px solid var(--line-soft)' }}>
      <div className="mono text-[10px] uppercase tracking-wider" style={{ color: 'var(--faint)' }}>{label}</div>
      <div className="mono tnum" style={{ fontSize: big ? 22 : 15, marginTop: 2, color: ok == null ? 'var(--text)' : ok ? 'var(--good)' : 'var(--bad)' }}>{value}</div>
    </div>
  )
}

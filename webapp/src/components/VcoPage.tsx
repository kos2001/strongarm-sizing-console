import { useState } from 'react'
import type { VcoDeviceKey, VcoOptimizeResult, VcoParams, VcoResult, VcoTuning } from '../types'
import { VCO_DEVICE_META } from '../types'
import { vcoOptimize, vcoSimulate } from '../api'
import TuningChart from './TuningChart'
import type { Lang } from '../i18n'

const VCO_DEFAULTS: VcoParams = {
  vdd: 1.0, vctrl: 0.6, n_stages: 5, cload_ff: 3.0,
  devices: {
    invp: { w_um: 2.0, l_nm: 45, m: 2 },
    invn: { w_um: 1.0, l_nm: 45, m: 2 },
    starvep: { w_um: 2.0, l_nm: 45, m: 2 },
    starven: { w_um: 1.0, l_nm: 45, m: 1 },
  },
}
const DKEYS: VcoDeviceKey[] = ['invp', 'invn', 'starvep', 'starven']
const T = (l: Lang, ko: string, en: string) => (l === 'ko' ? ko : en)

export default function VcoPage({ lang, theme }: { lang: Lang; theme: string }) {
  const [params, setParams] = useState<VcoParams>(VCO_DEFAULTS)
  const [res, setRes] = useState<VcoResult | null>(null)
  const [tuning, setTuning] = useState<VcoTuning | null>(null)
  const [opt, setOpt] = useState<VcoOptimizeResult | null>(null)
  const [running, setRunning] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const [targetF, setTargetF] = useState(1.5)

  const setDev = (k: VcoDeviceKey, f: 'w_um' | 'l_nm' | 'm', v: number) =>
    setParams((p) => ({ ...p, devices: { ...p.devices, [k]: { ...p.devices[k], [f]: v } } }))
  const setTop = (f: 'vctrl' | 'n_stages' | 'cload_ff' | 'vdd', v: number) =>
    setParams((p) => ({ ...p, [f]: v }))

  const run = async () => {
    setRunning(true); setOpt(null)
    try {
      const r = await vcoSimulate(params, true)
      if (!r.error) { setRes(r); setTuning(r.tuning ?? null) }
      else setRes(r)
    } catch (e) { setRes({ nominal: {} as VcoResult['nominal'], error: String(e) }) }
    finally { setRunning(false) }
  }

  const optimize = async () => {
    setOptimizing(true)
    try {
      const r = await vcoOptimize(params, targetF)
      if (!r.error) {
        setOpt(r); setParams((p) => ({ ...p, devices: r.final_params.devices }))
        setRes({ nominal: r.nominal }); setTuning(r.tuning)
      }
    } catch { /* ignore */ }
    finally { setOptimizing(false) }
  }

  const nom = res?.nominal
  const busy = running || optimizing
  const box: React.CSSProperties = { background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 14 }
  const lab = { color: 'var(--faint)' }

  return (
    <div className="grid gap-6" style={{ gridTemplateColumns: 'minmax(0,400px) 1fr' }}>
      {/* ---- controls ---- */}
      <section className="flex flex-col gap-4">
        <div className="p-4" style={box}>
          <div className="mono text-[11px] uppercase tracking-[0.16em] mb-3" style={lab}>{T(lang, '링 VCO · 소자 크기', 'ring VCO · sizing')}</div>
          <div className="grid gap-2 mono text-[11px] uppercase tracking-wider px-1 mb-1" style={{ gridTemplateColumns: '1.6fr 1fr 1fr 0.7fr', color: 'var(--faint)' }}>
            <span>{T(lang, '소자', 'Device')}</span><span>W (µm)</span><span>L (nm)</span><span>M</span>
          </div>
          {DKEYS.map((k) => (
            <div key={k} className="grid gap-2 items-center rounded-xl p-2.5 mb-2" style={{ gridTemplateColumns: '1.6fr 1fr 1fr 0.7fr', background: 'var(--surface-2)', border: '1px solid var(--line)', borderLeft: '3px solid var(--si)' }}>
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
                  value={params[f as 'vctrl' | 'n_stages' | 'cload_ff']} onChange={(e) => setTop(f as 'vctrl' | 'n_stages' | 'cload_ff', parseFloat(e.target.value) || 0)}
                  style={{ width: '100%', marginTop: 3 }} />
              </label>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <button onClick={run} disabled={busy} className="py-2.5 rounded-xl font-medium disabled:opacity-50"
            style={{ background: 'var(--si)', color: 'var(--bg)' }}>
            {running ? T(lang, '시뮬레이션 중…', 'simulating…') : T(lang, '▶ VCO 실행 (튜닝 포함)', '▶ Run VCO (with tuning)')}
          </button>
          <div className="flex gap-2 items-center rounded-xl p-2.5" style={{ background: 'var(--surface-2)', border: '1px solid var(--line)' }}>
            <span className="mono text-[11px]" style={lab}>{T(lang, '목표 f', 'target f')}</span>
            <input type="number" step={0.1} min={0.1} disabled={busy} value={targetF}
              onChange={(e) => setTargetF(parseFloat(e.target.value) || 0)} style={{ width: 64 }} />
            <span className="mono text-[11px]" style={lab}>GHz</span>
            <button onClick={optimize} disabled={busy} className="ml-auto mono text-xs px-3 py-1.5 rounded-full disabled:opacity-50"
              style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
              {optimizing ? T(lang, '탐색 중…', 'searching…') : T(lang, '◴ 자동 최적화', '◴ Auto-size')}
            </button>
          </div>
        </div>
      </section>

      {/* ---- results ---- */}
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
          {opt && (
            <div className="mono text-[11px] mt-3 px-2.5 py-1.5 rounded-lg" style={{ color: opt.success ? 'var(--good)' : 'var(--warn)', background: `color-mix(in srgb, ${opt.success ? 'var(--good)' : 'var(--warn)'} 12%, transparent)` }}>
              {opt.success ? '✓' : '≈'} {T(lang, '목표', 'target')} {opt.target_f_ghz} GHz → {opt.nominal.f_osc_ghz} GHz · {opt.nominal.power_uw} µW · {opt.n_sims} SPICE evals
            </div>
          )}
        </div>

        {tuning && (
          <div className="p-5" style={box}>
            <div className="mono text-[11px] uppercase tracking-[0.16em] mb-3" style={lab}>{T(lang, '튜닝 곡선 · f vs V_ctrl', 'tuning curve · f vs V_ctrl')}</div>
            <TuningChart tuning={tuning} theme={theme} />
            <div className="grid grid-cols-4 gap-3 mt-3">
              <Metric label={T(lang, '최소 f', 'f min')} value={tuning.f_min_ghz != null ? `${tuning.f_min_ghz} GHz` : '—'} />
              <Metric label={T(lang, '최대 f', 'f max')} value={tuning.f_max_ghz != null ? `${tuning.f_max_ghz} GHz` : '—'} />
              <Metric label={T(lang, '튜닝 범위', 'tuning range')} value={tuning.tuning_pct != null ? `${tuning.tuning_pct}%` : '—'} />
              <Metric label="Kvco" value={tuning.kvco_ghz_per_v != null ? `${tuning.kvco_ghz_per_v} GHz/V` : '—'} />
            </div>
            <p className="mono text-[11px] mt-3 leading-relaxed" style={{ color: 'var(--faint)' }}>
              {T(lang, 'V_ctrl이 스타빙 전류 → 지연 → 주파수를 조절. × = 그 전압에선 발진 안 함.', 'V_ctrl sets the starve current → delay → frequency. × = does not oscillate at that voltage.')}
            </p>
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

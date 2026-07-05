import type { VcoPvtResult } from '../types'

// 27-corner grid: 3 process rows (SS/TT/FF) × 9 cols (temp × VDD). Each cell = f_osc
// at that corner, teal-shaded by frequency; red if it fails to oscillate.
export default function VcoPvtView({ pvt, lang }: { pvt: VcoPvtResult; lang: 'ko' | 'en' }) {
  const temps = [-40, 27, 125]
  const vfs = [0.9, 1.0, 1.1]
  const procs = ['SS', 'TT', 'FF']
  const cell = (proc: string, t: number, vf: number) =>
    pvt.corners.find((c) => c.process === proc && c.temp === t && c.v_frac === vf)
  const fmin = pvt.f_min_ghz ?? 0, fmax = pvt.f_max_ghz ?? 1
  const shade = (f: number | null, osc: boolean) => {
    if (!osc || f == null) return { bg: 'color-mix(in srgb, var(--bad) 34%, transparent)', fg: 'var(--bad)' }
    const t = fmax > fmin ? (f - fmin) / (fmax - fmin) : 0.5
    return { bg: `color-mix(in srgb, var(--ag) ${12 + t * 34}%, transparent)`, fg: 'var(--text)' }
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <table className="mono text-[11px]" style={{ borderCollapse: 'separate', borderSpacing: 2, minWidth: 520 }}>
          <thead>
            <tr>
              <th></th>
              {temps.map((t) => <th key={t} colSpan={3} style={{ color: 'var(--faint)', paddingBottom: 2 }}>{t}°C</th>)}
            </tr>
            <tr>
              <th></th>
              {temps.flatMap((t) => vfs.map((vf) => <th key={`${t}-${vf}`} style={{ color: 'var(--faint)', fontWeight: 400 }}>{vf}×</th>))}
            </tr>
          </thead>
          <tbody>
            {procs.map((proc) => (
              <tr key={proc}>
                <td style={{ color: 'var(--muted)', paddingRight: 6 }}>{proc}</td>
                {temps.flatMap((t) => vfs.map((vf) => {
                  const c = cell(proc, t, vf); const sh = shade(c?.f_osc_ghz ?? null, !!c?.oscillates)
                  return (
                    <td key={`${proc}-${t}-${vf}`} className="tnum text-center" title={`${proc} ${t}°C ${c?.vdd}V`}
                      style={{ background: sh.bg, color: sh.fg, padding: '5px 7px', borderRadius: 5, minWidth: 46 }}>
                      {c?.oscillates ? c.f_osc_ghz : '✗'}
                    </td>
                  )
                }))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Stat label={lang === 'ko' ? '최소 f' : 'f min'} value={pvt.f_min_ghz != null ? `${pvt.f_min_ghz} GHz` : '—'} />
        <Stat label={lang === 'ko' ? '최대 f' : 'f max'} value={pvt.f_max_ghz != null ? `${pvt.f_max_ghz} GHz` : '—'} />
        <Stat label={lang === 'ko' ? '전 코너 발진' : 'all oscillate'} value={pvt.any_nonosc ? (lang === 'ko' ? '아니오 ✗' : 'no ✗') : (lang === 'ko' ? '예 ✓' : 'yes ✓')} ok={!pvt.any_nonosc} />
      </div>
      <p className="mono text-[11px]" style={{ color: 'var(--faint)' }}>
        {lang === 'ko'
          ? '각 칸 = 그 코너의 발진 주파수(GHz). 3행 = 공정 SS/TT/FF(±50mV Vth), 9열 = 온도×전압. 진한 색일수록 빠름, ✗ = 발진 실패.'
          : 'each cell = osc. frequency (GHz) at that corner. 3 rows = process SS/TT/FF (±50mV Vth), 9 cols = temp × VDD. Deeper = faster, ✗ = fails to oscillate.'}
      </p>
    </div>
  )
}
function Stat({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="rounded-xl p-3" style={{ background: 'var(--surface-2)', border: '1px solid var(--line-soft)' }}>
      <div className="mono text-[10px] uppercase tracking-wider" style={{ color: 'var(--faint)' }}>{label}</div>
      <div className="mono tnum" style={{ fontSize: 15, marginTop: 2, color: ok == null ? 'var(--text)' : ok ? 'var(--good)' : 'var(--bad)' }}>{value}</div>
    </div>
  )
}

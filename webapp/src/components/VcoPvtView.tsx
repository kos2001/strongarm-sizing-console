import type { VcoPvtResult } from '../types'

// Build the grid from measured process/temperature/supply coordinates. Missing
// combinations are unknown, distinct from measured startup failures.
export default function VcoPvtView({ pvt, lang }: { pvt: VcoPvtResult; lang: 'ko' | 'en' }) {
  const temps = [...new Set(pvt.corners.map(corner => corner.temp))].sort((a, b) => a - b)
  const vfs = [...new Set(pvt.corners.map(corner => corner.v_frac))].sort((a, b) => a - b)
  const order = ['SS', 'SF', 'TT', 'FS', 'FF']
  const procs = [...new Set(pvt.corners.map(corner => corner.process))].sort((a, b) => order.indexOf(a) - order.indexOf(b))
  const cell = (proc: string, t: number, vf: number) =>
    pvt.corners.find((c) => c.process === proc && c.temp === t && c.v_frac === vf)
  const complete = procs.length > 0 && procs.every(proc => temps.every(temp => vfs.every(vf => cell(proc, temp, vf))))
  const failed = pvt.any_nonosc || pvt.corners.some(corner => corner.oscillates === false)
  const fmin = pvt.f_min_ghz ?? 0, fmax = pvt.f_max_ghz ?? 1
  const shade = (f: number | null, osc: boolean) => {
    if (!osc || f == null) return { bg: 'color-mix(in srgb, var(--bad) 34%, transparent)', fg: 'var(--bad)' }
    const t = fmax > fmin ? (f - fmin) / (fmax - fmin) : 0.5
    return { bg: `color-mix(in srgb, var(--ag) ${12 + t * 34}%, transparent)`, fg: 'var(--text)' }
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <table aria-label={lang === 'ko' ? 'PVT 코너 측정값' : 'PVT corner measurements'} className="mono text-[11px]" style={{ borderCollapse: 'separate', borderSpacing: 2, minWidth: 520 }}>
          <thead>
            <tr>
              <th></th>
              {temps.map((t) => <th key={t} colSpan={vfs.length} style={{ color: 'var(--faint)', paddingBottom: 2 }}>{t}°C</th>)}
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
                  const c = cell(proc, t, vf); const sh = c ? shade(c.f_osc_ghz, c.oscillates) : { bg: 'var(--surface-2)', fg: 'var(--muted)' }
                  return (
                    <td key={`${proc}-${t}-${vf}`} className="tnum text-center" title={c ? `${proc} ${t}°C ${c.vdd}V` : (lang === 'ko' ? '측정 없음' : 'Not measured')}
                      style={{ background: sh.bg, color: sh.fg, padding: '5px 7px', borderRadius: 5, minWidth: 46 }}>
                      {!c ? '—' : c.oscillates ? (c.f_osc_ghz ?? '—') : '✗'}
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
        <Stat label={lang === 'ko' ? '전 코너 발진' : 'all oscillate'} value={failed ? (lang === 'ko' ? '아니오 ✗' : 'no ✗') : !complete ? (lang === 'ko' ? '일부 미측정' : 'Incomplete') : (lang === 'ko' ? '예 ✓' : 'yes ✓')} ok={failed ? false : complete ? true : undefined} />
      </div>
      <p className="mono text-[11px]" style={{ color: 'var(--faint)' }}>
        {lang === 'ko'
          ? `각 칸 = 발진 주파수(GHz). ${procs.length}행 = 공정 ${procs.join('/')}, ${temps.length * vfs.length}열 = 온도×전압. 진한 색일수록 빠름, ✗ = 발진 실패, — = 측정 없음.`
          : `Each cell = frequency (GHz). ${procs.length} process rows (${procs.join('/')}), ${temps.length * vfs.length} temperature × supply columns. Deeper = faster, ✗ = startup failure, — = not measured.`}
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

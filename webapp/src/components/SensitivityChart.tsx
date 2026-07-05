import { useState } from 'react'
import type { SensitivityResult, SensMetrics } from '../types'
import { DEVICE_META } from '../types'

type Metric = keyof SensMetrics
const METRICS: { key: Metric; label: string; unit: string }[] = [
  { key: 'decision_time_ps', label: 'Decision time', unit: 'ps' },
  { key: 'power_uw', label: 'Power', unit: 'µW' },
  { key: 'offset_sigma_mv', label: 'Offset σ', unit: 'mV' },
]

// Tornado: for the selected metric, each device shows a horizontal bar spanning
// its value at −δ%..+δ% width, so the widest bars are the strongest levers.
export default function SensitivityChart({ res }: { res: SensitivityResult }) {
  const [metric, setMetric] = useState<Metric>('decision_time_ps')
  const meta = METRICS.find((m) => m.key === metric)!
  const base = res.base[metric]
  const rows = res.devices
    .map((d) => ({ d, lo: d.low[metric], hi: d.high[metric] }))
    .filter((r) => r.lo != null && r.hi != null)
    .map((r) => ({ ...r, span: Math.abs((r.hi as number) - (r.lo as number)) }))
    .sort((a, b) => b.span - a.span)
  const vals = rows.flatMap((r) => [r.lo as number, r.hi as number]).concat(base != null ? [base] : [])
  const vmin = Math.min(...vals), vmax = Math.max(...vals)
  const pad = (vmax - vmin) * 0.08 || 1
  const lo = vmin - pad, hi = vmax + pad
  const W = 100 // percent-based viewBox
  const X = (v: number) => ((v - lo) / (hi - lo || 1)) * W

  return (
    <div>
      <div className="flex gap-1.5 mb-3">
        {METRICS.map((m) => (
          <button
            key={m.key}
            onClick={() => setMetric(m.key)}
            className="mono text-[11px] px-2.5 py-1 rounded-full transition-colors"
            style={{
              color: metric === m.key ? 'var(--bg)' : 'var(--muted)',
              background: metric === m.key ? 'var(--si)' : 'transparent',
              border: `1px solid ${metric === m.key ? 'var(--si)' : 'var(--line)'}`,
            }}
          >
            {m.label}
          </button>
        ))}
      </div>
      <div className="flex flex-col gap-2.5">
        {rows.map(({ d, lo: rlo, hi: rhi }) => {
          const a = X(Math.min(rlo as number, rhi as number))
          const b = X(Math.max(rlo as number, rhi as number))
          const higherWithWiderW = (rhi as number) > (rlo as number) // +W increases metric?
          return (
            <div key={d.key} className="flex items-center gap-3">
              <div className="mono text-[11px] w-24 shrink-0" style={{ color: 'var(--muted)' }}>{DEVICE_META[d.key].name}</div>
              <div className="relative flex-1 h-6 rounded" style={{ background: 'var(--surface-2)' }}>
                {/* base reference */}
                {base != null && <div className="absolute top-0 bottom-0" style={{ left: `${X(base)}%`, width: 1, background: 'var(--faint)' }} />}
                <div className="absolute top-1 bottom-1 rounded" style={{ left: `${a}%`, width: `${Math.max(b - a, 0.6)}%`, background: `color-mix(in srgb, var(--si) 55%, transparent)`, border: '1px solid var(--si)' }} />
                <div className="absolute inset-0 flex items-center justify-between px-2 mono text-[10px]" style={{ color: 'var(--faint)' }}>
                  <span>{higherWithWiderW ? '−' : '+'}{res.delta_pct}% : {(rlo as number).toFixed(metric === 'offset_sigma_mv' ? 2 : 1)}</span>
                  <span>{(rhi as number).toFixed(metric === 'offset_sigma_mv' ? 2 : 1)} : {higherWithWiderW ? '+' : '−'}{res.delta_pct}%</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <p className="mono text-[11px] mt-3" style={{ color: 'var(--muted)' }}>
        base {meta.label} = <span style={{ color: 'var(--text)' }}>{base != null ? `${base}${meta.unit}` : '—'}</span> · bar = value at ±{res.delta_pct}% W · widest bar = strongest lever. Offset responds to input-pair W only (Pelgrom).
      </p>
    </div>
  )
}

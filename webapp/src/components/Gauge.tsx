interface GaugeProps {
  label: string
  value: number | null
  limit: number
  unit: string
  pass: boolean | null
}

export default function Gauge({ label, value, limit, unit, pass }: GaugeProps) {
  const has = value !== null && value !== undefined
  const max = has ? Math.max(limit * 1.4, value! * 1.12) : limit * 1.4
  const fillPct = has ? Math.min((value! / max) * 100, 100) : 0
  const targetPct = (limit / max) * 100
  const color = pass === null ? 'var(--muted)' : pass ? 'var(--si)' : 'var(--bad)'

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <div className="text-sm">
          {label}{' '}
          <span className="mono text-xs" style={{ color: 'var(--faint)' }}>
            ≤ {limit} {unit}
          </span>
        </div>
        <div
          className="mono text-xs px-2 py-0.5 rounded-full"
          style={{
            color,
            background: pass === null ? 'transparent' : `color-mix(in srgb, ${color} 15%, transparent)`,
          }}
        >
          {pass === null ? '—' : pass ? 'PASS' : 'FAIL'}
        </div>
      </div>
      <div
        className="relative h-9 rounded-lg overflow-hidden"
        style={{ background: 'var(--surface-2)', border: '1px solid var(--line-soft)' }}
      >
        <div
          className="absolute inset-y-0 left-0 rounded-l-lg transition-all duration-500"
          style={{
            width: `${fillPct}%`,
            background:
              pass === false
                ? 'linear-gradient(90deg, color-mix(in srgb, var(--bad) 55%, #000), var(--bad))'
                : 'linear-gradient(90deg, var(--si-dim), var(--si))',
            opacity: 0.85,
          }}
        />
        <div
          className="absolute -top-1 -bottom-1"
          style={{ left: `${targetPct}%`, width: '2px', background: 'var(--warn)' }}
        />
        <div
          className="absolute right-2.5 top-1/2 -translate-y-1/2 mono tnum text-sm"
          style={{ color: 'var(--text)' }}
        >
          {has ? `${value} ${unit}` : '—'}
        </div>
      </div>
    </div>
  )
}

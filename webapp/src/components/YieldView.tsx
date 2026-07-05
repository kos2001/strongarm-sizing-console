import type { YieldResult } from '../types'

// Parametric yield: a big pass-rate dial, a fail-mode breakdown, and a scatter of
// the Monte-Carlo samples (offset vs decision time) coloured pass/fail with the
// spec box drawn in.
export default function YieldView({ res }: { res: YieldResult }) {
  const s = res.samples
  const decs = s.map((x) => x.decision_ps ?? res.targets.decision_time_ps * 1.5)
  const offs = s.map((x) => Math.abs(x.offset_mv))
  const dmax = Math.max(res.targets.decision_time_ps * 1.2, ...decs) * 1.05
  const omax = Math.max(res.targets.offset_mv * 1.2, ...offs) * 1.05
  const W = 100, H = 60
  const X = (o: number) => (o / (omax || 1)) * W
  const Y = (d: number) => H - (d / (dmax || 1)) * H
  const good = res.yield_pct >= 99 ? 'var(--good)' : res.yield_pct >= 90 ? 'var(--warn)' : 'var(--bad)'
  const fb = res.fail_breakdown

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-6">
        <div className="flex flex-col">
          <div className="mono text-[11px]" style={{ color: 'var(--faint)' }}>PARAMETRIC YIELD</div>
          <div className="mono tnum" style={{ color: good, fontSize: 44, lineHeight: 1.1 }}>{res.yield_pct}%</div>
          <div className="mono text-[11px]" style={{ color: 'var(--muted)' }}>{res.pass}/{res.n} samples · mismatch × PVT</div>
        </div>
        <div className="flex flex-col gap-1.5 flex-1">
          {([['offset', 'offset > spec'], ['speed', 'too slow at corner'], ['decision_wrong', 'wrong / no decision']] as const).map(([k, label]) => (
            <div key={k} className="flex items-center gap-2">
              <div className="mono text-[11px] w-36 shrink-0" style={{ color: 'var(--muted)' }}>{label}</div>
              <div className="relative flex-1 h-3 rounded" style={{ background: 'var(--surface-2)' }}>
                <div className="absolute top-0 bottom-0 left-0 rounded" style={{ width: `${(fb[k] / res.n) * 100}%`, background: 'color-mix(in srgb, var(--bad) 60%, transparent)' }} />
              </div>
              <div className="mono text-[11px] w-8 text-right tnum" style={{ color: 'var(--muted)' }}>{fb[k]}</div>
            </div>
          ))}
        </div>
      </div>

      <svg viewBox={`-8 -6 ${W + 16} ${H + 18}`} width="100%" style={{ maxHeight: 300, display: 'block', background: 'var(--surface-2)', borderRadius: 10 }} role="img" aria-label="Yield sample scatter">
        {/* spec box (pass region: offset <= target AND decision <= target) */}
        <rect x={0} y={Y(res.targets.decision_time_ps)} width={X(res.targets.offset_mv)} height={H - Y(res.targets.decision_time_ps)} fill="color-mix(in srgb, var(--good) 12%, transparent)" stroke="color-mix(in srgb, var(--good) 45%, transparent)" strokeWidth={0.3} strokeDasharray="1 1" />
        {/* axes */}
        <line x1={0} y1={0} x2={0} y2={H} stroke="var(--line)" strokeWidth={0.3} />
        <line x1={0} y1={H} x2={W} y2={H} stroke="var(--line)" strokeWidth={0.3} />
        {s.map((x, i) => (
          <circle key={i} cx={X(Math.abs(x.offset_mv))} cy={Y(x.decision_ps ?? dmax)} r={0.9} fill={x.pass ? 'var(--si)' : 'var(--bad)'} fillOpacity={0.85} />
        ))}
        <text x={W} y={H + 12} fontSize={3} fill="var(--faint)" textAnchor="end" fontFamily="ui-monospace, monospace">|offset| mV →</text>
        <text x={2} y={6} fontSize={3} fill="var(--faint)" fontFamily="ui-monospace, monospace">decision ps ↑</text>
      </svg>
      <p className="mono text-[11px]" style={{ color: 'var(--muted)' }}>
        each dot = one chip drawn from Vth mismatch × random process/temp/VDD. <span style={{ color: 'var(--si)' }}>teal</span> = meets offset ≤ {res.targets.offset_mv} mV and decision ≤ {res.targets.decision_time_ps} ps (green box); <span style={{ color: 'var(--bad)' }}>red</span> = fails. Yield couples mismatch and corner variation into one number.
      </p>
    </div>
  )
}

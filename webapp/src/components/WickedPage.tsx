import { useState } from 'react'
import type { Params, WcdResult, WickedCornersResult, WickedFlowResult, WickedImportanceResult } from '../types'
import { wickedCorners, wickedFullflow, wickedImportance, wickedWcd } from '../api'

// WiCkeD-inspired robustness console (wicked.py bridge): worst-case distance β,
// importance-sampled high-sigma yield, worst-case corner extraction, and the
// end-to-end FEO→DNO→WCO→WCD flow. Complements the 48-sample MC yield page —
// β-based estimates resolve the ≥3σ region a small Monte-Carlo cannot.
interface Props {
  params: Params
  targets: Record<string, number>
  busy: boolean
  apiUp: boolean | null
  onApply: (p: Params) => void
}

// compact one-line rendering of a stage-detail object (scalars only)
const fmtDetail = (d: unknown): string => {
  if (d == null) return ''
  if (typeof d !== 'object') return String(d)
  return Object.entries(d as Record<string, unknown>)
    .filter(([, v]) => v == null || typeof v !== 'object')
    .slice(0, 6)
    .map(([k, v]) => `${k}=${typeof v === 'number' ? +v.toFixed(3) : String(v)}`)
    .join(' · ')
}

const sigmaColor = (beta: number) => (beta >= 3 ? 'var(--good)' : beta >= 2 ? 'var(--warn)' : 'var(--bad)')

export default function WickedPage({ params, targets, busy, apiUp, onApply }: Props) {
  const [wcd, setWcd] = useState<WcdResult | null>(null)
  const [wcdLoading, setWcdLoading] = useState(false)
  const [imp, setImp] = useState<WickedImportanceResult | null>(null)
  const [impLoading, setImpLoading] = useState(false)
  const [corners, setCorners] = useState<WickedCornersResult | null>(null)
  const [cornersLoading, setCornersLoading] = useState(false)
  const [flow, setFlow] = useState<WickedFlowResult | null>(null)
  const [flowLoading, setFlowLoading] = useState(false)

  const anyLoading = wcdLoading || impLoading || cornersLoading || flowLoading
  const disabled = busy || anyLoading || apiUp === false

  const runWcd = async () => {
    setWcdLoading(true)
    try {
      const r = await wickedWcd(params, targets)
      if (!r.error) setWcd(r)
    } catch {
      /* ignore */
    } finally {
      setWcdLoading(false)
    }
  }
  const runImp = async () => {
    setImpLoading(true)
    try {
      const r = await wickedImportance(params, targets)
      if (!r.error) setImp(r)
    } catch {
      /* ignore */
    } finally {
      setImpLoading(false)
    }
  }
  const runCorners = async () => {
    setCornersLoading(true)
    try {
      const r = await wickedCorners(params, targets)
      if (!r.error) setCorners(r)
    } catch {
      /* ignore */
    } finally {
      setCornersLoading(false)
    }
  }
  const runFlow = async () => {
    setFlowLoading(true)
    try {
      const r = await wickedFullflow(params, targets)
      if (!r.error) {
        setFlow(r)
        onApply(r.final_params) // land the flow's sized design in the editor
      }
    } catch {
      /* ignore */
    } finally {
      setFlowLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* WCD + importance sampling side by side */}
      <div className="grid gap-4" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="rounded-2xl p-5 flex flex-col gap-3" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
          <div className="flex items-center justify-between gap-3">
            <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Worst-case distance · β</div>
            <button onClick={runWcd} disabled={disabled} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
              {wcdLoading ? 'sampling… (~30s)' : 'β run WCD (24)'}
            </button>
          </div>
          {wcd ? (
            <>
              <div className="flex items-baseline gap-4">
                <span className="mono tnum text-4xl font-semibold" style={{ color: sigmaColor(wcd.beta_sigma) }}>{wcd.beta_sigma}σ</span>
                <span className="mono text-sm tnum" style={{ color: 'var(--text)' }}>≈ {wcd.estimated_yield_pct}% yield</span>
              </div>
              <div className="flex flex-col gap-1.5">
                {wcd.candidates.map((c) => (
                  <div key={c.metric} className="flex items-center justify-between rounded-lg px-3 py-1.5" style={{ background: 'var(--surface-2)', border: '1px solid var(--line-soft)' }}>
                    <span className="mono text-[11px]" style={{ color: c.metric === wcd.limiting_mechanism.metric ? 'var(--warn)' : 'var(--muted)' }}>
                      {c.metric === wcd.limiting_mechanism.metric ? '▶ ' : ''}{c.metric}
                    </span>
                    <span className="mono text-[11px] tnum" style={{ color: 'var(--text)' }}>{c.beta != null && Number.isFinite(c.beta) ? `β=${(+c.beta).toFixed(2)}` : '∞'}</span>
                  </div>
                ))}
              </div>
              <p className="mono text-[11px] leading-relaxed" style={{ color: 'var(--faint)' }}>
                ▶ = limiting mechanism · predicted offset σ {wcd.predicted_offset_sigma_mv} mV · {wcd.note}
              </p>
            </>
          ) : (
            <p className="text-sm" style={{ color: 'var(--muted)' }}>
              Distance (in σ units) from the design point to the nearest spec failure — analytic Pelgrom offset distance + 24 ngspice-sampled PVT boundary probes. β ≥ 3 ≈ 99.87% yield.
            </p>
          )}
        </div>

        <div className="rounded-2xl p-5 flex flex-col gap-3" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
          <div className="flex items-center justify-between gap-3">
            <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>High-sigma yield · importance sampling</div>
            <button onClick={runImp} disabled={disabled} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
              {impLoading ? 'sampling… (~60s)' : '∿ run IS (24)'}
            </button>
          </div>
          {imp ? (
            <>
              <div className="flex items-baseline gap-4">
                <span className="mono tnum text-4xl font-semibold" style={{ color: imp.estimated_yield_pct >= (targets.yield_pct ?? 99) ? 'var(--good)' : 'var(--warn)' }}>{imp.estimated_yield_pct}%</span>
                <span className="mono text-sm tnum" style={{ color: 'var(--muted)' }}>P(fail) {imp.weighted_failure_prob.toExponential(2)}</span>
              </div>
              <div className="mono text-[11px]" style={{ color: 'var(--muted)' }}>
                shifted β={imp.shift_beta} toward the WCD failure direction · {imp.raw_failures}/{imp.n} raw failures, Gaussian-reweighted
              </div>
              <div className="pt-2" style={{ borderTop: '1px solid var(--line-soft)' }}>
                <div className="mono text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--faint)' }}>mismatch budget (input-referred σ, mV)</div>
                <div className="flex flex-col gap-1">
                  {imp.mismatch_budget.contributors.map((c) => {
                    const frac = c.input_referred_sigma_mv / (imp.mismatch_budget.total_sigma_mv || 1)
                    return (
                      <div key={c.device} className="flex items-center gap-2">
                        <span className="mono text-[11px] w-10" style={{ color: 'var(--muted)' }}>{c.device}</span>
                        <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--surface-2)' }}>
                          <div className="h-full rounded-full" style={{ width: `${Math.min(100, 100 * frac)}%`, background: c.device === imp.mismatch_budget.dominant.device ? 'var(--warn)' : 'var(--si)' }} />
                        </div>
                        <span className="mono text-[11px] tnum w-14 text-right" style={{ color: 'var(--text)' }}>{c.input_referred_sigma_mv}</span>
                      </div>
                    )
                  })}
                </div>
                <p className="mono text-[11px] mt-1.5" style={{ color: 'var(--faint)' }}>total σ {imp.mismatch_budget.total_sigma_mv} mV · {imp.mismatch_budget.note}</p>
              </div>
            </>
          ) : (
            <p className="text-sm" style={{ color: 'var(--muted)' }}>
              Monte-Carlo shifted toward the WCD failure region, unbiased by the Gaussian likelihood ratio — resolves failure probabilities far below what {'>'}1000 plain MC samples could see, at 24 SPICE runs.
            </p>
          )}
        </div>
      </div>

      {/* worst-case corners */}
      <div className="rounded-2xl p-5 flex flex-col gap-3" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }}>
        <div className="flex items-center justify-between gap-3">
          <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>Worst-case corner extraction · 27-corner PVT grid</div>
          <button onClick={runCorners} disabled={disabled} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
            {cornersLoading ? 'sweeping… (~30s)' : '◫ extract corners'}
          </button>
        </div>
        {corners ? (
          <>
            <div className="flex items-center gap-3">
              <span className="mono text-xs px-2.5 py-1 rounded-full" style={{ color: corners.n_failing === 0 ? 'var(--good)' : 'var(--bad)', background: `color-mix(in srgb, ${corners.n_failing === 0 ? 'var(--good)' : 'var(--bad)'} 14%, transparent)` }}>
                {corners.n_failing === 0 ? 'ALL CORNERS PASS' : `${corners.n_failing}/${corners.total_corners} CORNERS FAIL`}
              </span>
              {corners.near_margin_corners.length > 0 && (
                <span className="mono text-[11px]" style={{ color: 'var(--warn)' }}>{corners.near_margin_corners.length} corners within 15% margin</span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full" style={{ borderCollapse: 'collapse' }}>
                <thead>
                  <tr className="mono text-[10px] uppercase tracking-wider" style={{ color: 'var(--faint)' }}>
                    {['#', 'process', 'temp (°C)', 'VDD (V)', 'decision (ps)', 'power (µW)', 'margin'].map((h) => (
                      <th key={h} className="text-left px-2 py-1.5" style={{ borderBottom: '1px solid var(--line-soft)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {corners.worst_5.map((c, i) => {
                    const m = c.decision_margin
                    const ok = m != null && m >= 0 && c.functional
                    return (
                      <tr key={i} className="mono text-[12px] tnum" style={{ color: 'var(--text)' }}>
                        <td className="px-2 py-1.5" style={{ color: 'var(--faint)' }}>{i + 1}</td>
                        <td className="px-2 py-1.5">{c.process}</td>
                        <td className="px-2 py-1.5">{c.temp}</td>
                        <td className="px-2 py-1.5">{c.vdd}</td>
                        <td className="px-2 py-1.5">{c.decision_time_ps ?? '—'}</td>
                        <td className="px-2 py-1.5">{c.power_uw ?? '—'}</td>
                        <td className="px-2 py-1.5" style={{ color: ok ? 'var(--good)' : 'var(--bad)' }}>{m != null ? `${(100 * m).toFixed(1)}%` : c.functional ? '—' : 'no resolve'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="mono text-[11px]" style={{ color: 'var(--faint)' }}>{corners.note} — fix these corners first; the other {corners.total_corners - 5} have more margin.</p>
          </>
        ) : (
          <p className="text-sm" style={{ color: 'var(--muted)' }}>
            Ranks the full process × temperature × VDD grid by decision-time margin and returns the 5 most-limiting corners — so sizing effort goes where the design actually fails.
          </p>
        )}
      </div>

      {/* full WiCkeD flow */}
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>WiCkeD flow · FEO → DNO → WCO → WCD → IS → screening → post-layout</div>
          <button onClick={runFlow} disabled={disabled} className="mono text-[11px] px-2.5 py-1 rounded-full disabled:opacity-50" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}>
            {flowLoading ? 'running flow… (~3min)' : '⇉ run WiCkeD flow'}
          </button>
        </div>
        {flow ? (
          <div className="rounded-2xl p-5 flex flex-col gap-3" style={{ background: 'var(--surface)', border: `1px solid ${flow.overall ? 'color-mix(in srgb, var(--good) 45%, var(--line))' : 'var(--line)'}` }}>
            <div className="flex items-center justify-between">
              <div className="mono text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--faint)' }}>robustness sign-off verdict</div>
              <div className="mono text-xs px-2.5 py-1 rounded-full" style={{ color: flow.overall ? 'var(--good)' : 'var(--warn)', background: `color-mix(in srgb, ${flow.overall ? 'var(--good)' : 'var(--warn)'} 14%, transparent)` }}>{flow.overall ? 'SIGNED OFF' : 'NOT CLEAN'}</div>
            </div>
            {flow.stages.map((s, i) => (
              <div key={i} className="flex items-start gap-3 rounded-lg px-3 py-2" style={{ background: 'var(--surface-2)', border: '1px solid var(--line-soft)' }}>
                <span className="mono text-xs mt-0.5" style={{ color: s.ok ? 'var(--good)' : 'var(--bad)' }}>{s.ok ? '✓' : '✗'}</span>
                <div className="min-w-0">
                  <div className="text-[13px]" style={{ color: 'var(--text)' }}>{i + 1}. {s.name}</div>
                  <div className="mono text-[11px] break-words" style={{ color: 'var(--muted)' }}>{fmtDetail(s.detail)}</div>
                </div>
              </div>
            ))}
            <p className="mono text-[11px]" style={{ color: 'var(--faint)' }}>Flow-refined sizing applied to the editor.</p>
          </div>
        ) : (
          <p className="text-sm" style={{ color: 'var(--muted)' }}>
            End-to-end robustness sign-off: feasibility check → sensitivity-guided nominal refinement → worst-case-operation refinement → 27-corner WCO → WCD/yield proxy → mismatch budget → importance-sampled high-sigma check → parameter screening → post-layout WCD (~3 min). The refined sizing lands in the editor.
          </p>
        )}
      </div>
    </div>
  )
}

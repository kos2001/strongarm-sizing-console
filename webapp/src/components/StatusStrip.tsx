import { t, UI, type Lang } from '../i18n'

/** One row, on every page: does the current design meet its spec?
 *
 * Before this, that answer lived only on the Sizing page's gauges. Every other page
 * showed one facet of the design with no indication of whether the thing being analysed
 * was even passing — so the user had to hold four numbers in their head while navigating,
 * or keep going back. The strip is deliberately the same on all 28 pages: it is the
 * fixed reference point the rest of the console is read against.
 *
 * It also states the *unrun* case explicitly. A blank strip would read as "no data";
 * "not measured yet" plus the name of the button that fixes it is what a newcomer needs.
 */
export interface StatusMetric {
  key: string
  label: string
  value: number | null
  /** null = informational only: shown, but makes no pass/fail claim and does not affect the
   *  headline. Used where the UI has no user-set spec for the quantity — inventing a limit
   *  so the row looks complete would be fabricating a spec the user never chose. */
  limit: number | null
  unit: string
  /** 'max' — pass when value <= limit (a budget). 'target' — pass when value is within
   *  `tol` of limit (a frequency a VCO must actually hit). Without this distinction the
   *  strip would mark a VCO running exactly on target as passing only by accident, and a
   *  VCO at half the requested frequency as comfortably passing. Defaults to 'max'. */
  mode?: 'max' | 'target'
  /** fractional tolerance for mode 'target'; default 0.10 */
  tol?: number
}

const ok_of = (m: StatusMetric) =>
  m.value == null || m.limit == null ? null
    : m.mode === 'target' ? Math.abs(m.value / m.limit - 1) <= (m.tol ?? 0.10)
    : m.value <= m.limit

interface Props {
  lang: Lang
  metrics: StatusMetric[]
  /** Where to go next when the design misses. "Misses spec" on its own leaves the reader
   *  with the diagnosis and no move; the binding metric plus the page that acts on it is
   *  the whole point of having a status row rather than four numbers. */
  onFix?: (metricKey: string) => void
  fixLabel?: string
  /** null while nothing has been run — distinct from "ran and failed" */
  functional: boolean | null
  profileLabel: string
  error?: string | null
  onRun?: () => void
  busy?: boolean
}

/** Digits that fit: 530 ps needs none, 1.87 mV needs two. */
const fmt = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2))

export default function StatusStrip({ lang, metrics, functional, profileLabel, error, onRun, busy, onFix, fixLabel }: Props) {
  const measured = metrics.filter((m) => m.value != null && m.limit != null)
  const failing = measured.filter((m) => ok_of(m) === false)
  const state: 'unrun' | 'error' | 'pass' | 'fail' =
    error ? 'error' : functional === null || !measured.length ? 'unrun' : functional === false || failing.length ? 'fail' : 'pass'

  // "worst" = furthest past its limit in relative terms, which is the one to fix first.
  // Absolute overshoot would rank a 30 ps miss above a 2x power miss.
  const worst = failing.length
    ? failing.reduce((a, b) => (Math.abs(a.value! / a.limit! - 1) >= Math.abs(b.value! / b.limit! - 1) ? a : b))
    : null
  const tone = { unrun: 'var(--faint)', error: 'var(--bad)', pass: 'var(--good)', fail: 'var(--bad)' }[state]
  const headline = {
    unrun: t(lang, UI.statusUnrun),
    error: t(lang, UI.statusError),
    pass: t(lang, UI.statusPass),
    fail: functional === false ? t(lang, UI.statusNonFunctional) : t(lang, UI.statusFail),
  }[state]

  return (
    <div
      className="rounded-xl px-3.5 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-2"
      style={{
        background: `color-mix(in srgb, ${tone} 7%, var(--surface))`,
        border: `1px solid color-mix(in srgb, ${tone} 30%, var(--line))`,
      }}
    >
      <div className="flex items-center gap-2 shrink-0">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: tone }} />
        <span className="text-sm font-medium" style={{ color: tone }}>{headline}</span>
        <span className="mono text-[10px] px-1.5 py-0.5 rounded" style={{ color: 'var(--faint)', background: 'var(--surface-2)' }}>{profileLabel}</span>
      </div>

      {state === 'unrun' && onRun && (
        <button
          onClick={onRun}
          disabled={busy}
          className="mono text-xs px-3 py-1 rounded-full disabled:opacity-40"
          style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }}
        >
          ▶ {t(lang, UI.statusRunNow)}
        </button>
      )}

      {state === 'error' && <span className="mono text-[11px] truncate" style={{ color: 'var(--bad)' }}>{error}</span>}

      {/* the binding metric, named, with the one action that addresses it */}
      {state === 'fail' && worst && onFix && (
        <button
          onClick={() => onFix(worst.key)}
          className="mono text-[11px] px-2.5 py-1 rounded-full shrink-0"
          style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }}
          title={`${worst.label} is the binding constraint`}
        >
          {worst.label} → {fixLabel ?? t(lang, UI.statusFixIt)}
        </button>
      )}

      {/* Every metric always shown, in the same order, whether it passes or not. Hiding the
          passing ones would make the row jump around between pages and lose its value as a
          fixed reference. */}
      {state !== 'unrun' && state !== 'error' && (
        <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5">
          {metrics.map((m) => {
            const has = m.value != null
            const judged = ok_of(m)
            const ok = judged === true
            const col = !has || judged === null ? 'var(--muted)' : ok ? 'var(--si)' : 'var(--bad)'
            const ratio = has && m.limit != null ? m.value! / m.limit : null
            return (
              <div key={m.key} className="flex items-baseline gap-1.5"
                   title={m.limit == null
                     ? `${m.label}: ${has ? fmt(m.value!) : '—'} ${m.unit} — no spec set, shown for reference`
                     : `${m.label}: ${has ? fmt(m.value!) : '—'} ${m.mode === 'target' ? 'target' : 'limit'} ${m.limit} ${m.unit}`}>
                <span className="mono text-[10px] uppercase tracking-wide" style={{ color: 'var(--faint)' }}>{m.label}</span>
                <span className="mono text-xs tnum" style={{ color: col }}>{has ? fmt(m.value!) : '—'}</span>
                {/* "≤" for a budget, "→" for a target: the comparison the metric is judged by,
                    spelled out rather than left for the reader to assume. No spec, no claim. */}
                <span className="mono text-[10px] tnum" style={{ color: 'var(--faint)' }}>
                  {m.limit == null ? m.unit : `${m.mode === 'target' ? '→' : '≤'} ${m.limit} ${m.unit}`}
                </span>
                {/* Headroom — the number a designer acts on. The arrow carries the meaning,
                    not the sign: a bare "63%" next to a bare "+33%" left the reader working
                    out from the colour alone which one was margin and which was overage. */}
                {ratio != null && (() => {
                  const dev = Math.round((ratio - 1) * 100)
                  // For a target, any deviation is a deviation — being 20% FAST is as wrong
                  // as being 20% slow, so the badge shows signed offset from target rather
                  // than "margin", which would be meaningless here.
                  const text = m.mode === 'target'
                    ? (dev === 0 ? 'on target' : `${dev > 0 ? '↑' : '↓'}${Math.abs(dev)}%`)
                    : ok ? `↓${-dev}%` : `↑${dev}%`
                  const tip = m.mode === 'target'
                    ? `${Math.abs(dev)}% ${dev > 0 ? 'above' : 'below'} the target frequency`
                    : ok ? `${-dev}% below the limit` : `${dev}% over the limit`
                  return (
                    <span className="mono text-[10px] tnum px-1 rounded" title={tip}
                          style={{ color: col, background: `color-mix(in srgb, ${col} 12%, transparent)` }}>{text}</span>
                  )
                })()}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

import { useEffect, useRef } from 'react'
import type { Offset } from '../types'

// Visualizes the Monte-Carlo offset run: each sample is one random Vth-mismatch
// draw whose input-referred offset was found by bisection. Shows the histogram,
// individual samples (rug), mean, ±σ band, a fitted normal curve, and the
// ±spec limit. When `before` (a second measured MC) is given, its distribution
// is overlaid faintly for a pre/post-optimization comparison.
export default function MonteCarloChart({ offset, before, targetMv, theme }: { offset: Offset; before?: Offset | null; targetMv: number; theme: string }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const cv = ref.current
    const s = offset.samples_mv
    if (!cv || !s?.length) return
    const sb = before?.samples_mv ?? null
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim()

    const draw = () => {
      const rect = cv.getBoundingClientRect()
      const W = rect.width, H = rect.height
      cv.width = W * dpr; cv.height = H * dpr
      const ctx = cv.getContext('2d')!
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, W, H)

      const padL = 8, padR = 8, padT = 10, padB = 26
      const x0 = padL, x1 = W - padR, yBase = H - padB, yTop = padT
      const sig = offset.offset_sigma_mv
      const mean = offset.offset_mean_mv
      const allAbs = [...s, ...(sb ?? [])].map((v) => Math.abs(v))
      const M = Math.max(targetMv * 1.25, Math.max(...allAbs) * 1.1, sig * 3.2, (before?.offset_sigma_mv ?? 0) * 3.2, 1)
      const X = (v: number) => x0 + ((v + M) / (2 * M)) * (x1 - x0)
      const nb = 15
      const bw = (x1 - x0) / nb
      const binW = (2 * M) / nb

      const hist = (arr: number[]) => {
        const b = new Array(nb).fill(0)
        arr.forEach((v) => { const i = Math.max(0, Math.min(nb - 1, Math.floor(((v + M) / (2 * M)) * nb))); b[i]++ })
        return b
      }
      const binsA = hist(s)
      const binsB = sb ? hist(sb) : null
      const bmax = Math.max(...binsA, ...(binsB ?? [0]), 1)

      // ±sigma band (after)
      ctx.fillStyle = css('--si'); ctx.globalAlpha = 0.1
      ctx.fillRect(X(mean - sig), yTop, X(mean + sig) - X(mean - sig), yBase - yTop)
      ctx.globalAlpha = 1

      // before histogram (faint outline) under after
      if (binsB) {
        ctx.strokeStyle = css('--faint'); ctx.globalAlpha = 0.6; ctx.lineWidth = 1
        for (let i = 0; i < nb; i++) {
          if (!binsB[i]) continue
          const h = (binsB[i] / bmax) * (yBase - yTop - 4)
          ctx.strokeRect(x0 + i * bw + 1, yBase - h, bw - 2, h)
        }
        ctx.globalAlpha = 1
      }
      // after histogram (filled)
      ctx.fillStyle = css('--si'); ctx.globalAlpha = 0.7
      for (let i = 0; i < nb; i++) {
        if (!binsA[i]) continue
        const h = (binsA[i] / bmax) * (yBase - yTop - 4)
        ctx.fillRect(x0 + i * bw + 1, yBase - h, bw - 2, h)
      }
      ctx.globalAlpha = 1

      // fitted normal curves
      const gauss = (x: number, mu: number, sg: number) => Math.exp(-((x - mu) ** 2) / (2 * sg * sg)) / (sg * Math.sqrt(2 * Math.PI))
      const curve = (arr: number[], mu: number, sg: number, color: string, dash: number[], alpha: number) => {
        if (!sg || sg <= 0) return
        ctx.beginPath()
        for (let px = x0; px <= x1; px += 2) {
          const v = -M + ((px - x0) / (x1 - x0)) * (2 * M)
          const cnt = arr.length * binW * gauss(v, mu, sg)
          const y = yBase - Math.min(cnt / bmax, 1.08) * (yBase - yTop - 4)
          px === x0 ? ctx.moveTo(px, y) : ctx.lineTo(px, y)
        }
        ctx.strokeStyle = color; ctx.lineWidth = 1.8; ctx.setLineDash(dash); ctx.globalAlpha = alpha
        ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1
      }
      if (sb && before) curve(sb, before.offset_mean_mv, before.offset_sigma_mv, css('--faint'), [4, 3], 0.85)
      curve(s, mean, sig, css('--si'), [], 0.95)

      // target limits (±)
      const vlim = (v: number, color: string, label: string) => {
        const x = X(v)
        ctx.strokeStyle = color; ctx.setLineDash([4, 3]); ctx.globalAlpha = 0.8
        ctx.beginPath(); ctx.moveTo(x, yTop); ctx.lineTo(x, yBase); ctx.stroke()
        ctx.setLineDash([]); ctx.globalAlpha = 1
        ctx.font = '9px ui-monospace, monospace'; ctx.fillStyle = color
        ctx.fillText(label, x + 2, yTop + 8)
      }
      vlim(targetMv, css('--warn'), `+${targetMv}`)
      vlim(-targetMv, css('--warn'), `−${targetMv}`)

      // mean line (after)
      ctx.strokeStyle = css('--text'); ctx.lineWidth = 1.5
      ctx.beginPath(); ctx.moveTo(X(mean), yTop); ctx.lineTo(X(mean), yBase); ctx.stroke()

      // rug: before (faint, lower) then after
      if (sb) sb.forEach((v) => { ctx.beginPath(); ctx.arc(X(v), yBase + 12, 1.8, 0, 7); ctx.fillStyle = css('--faint'); ctx.globalAlpha = 0.6; ctx.fill(); ctx.globalAlpha = 1 })
      s.forEach((v) => {
        ctx.beginPath(); ctx.arc(X(v), yBase + 6, 2.2, 0, 7)
        ctx.fillStyle = Math.abs(v) <= targetMv ? css('--si') : css('--bad')
        ctx.globalAlpha = 0.85; ctx.fill(); ctx.globalAlpha = 1
      })

      // axis
      ctx.strokeStyle = css('--line'); ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(x0, yBase); ctx.lineTo(x1, yBase); ctx.stroke()
      ctx.font = '9px ui-monospace, monospace'; ctx.fillStyle = css('--faint')
      ctx.fillText(`−${M.toFixed(1)}`, x0, H - 4)
      ctx.fillText('0 mV', X(0) - 10, H - 4)
      ctx.fillText(`+${M.toFixed(1)}`, x1 - 24, H - 4)
    }

    draw()
    const ro = new ResizeObserver(draw)
    ro.observe(cv)
    return () => ro.disconnect()
  }, [offset, before, targetMv, theme])

  return <canvas ref={ref} style={{ width: '100%', height: '160px', display: 'block' }} aria-label="Monte-Carlo offset distribution" />
}

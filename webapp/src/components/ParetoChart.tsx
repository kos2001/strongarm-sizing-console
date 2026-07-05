import { useEffect, useRef } from 'react'
import type { ParetoResult } from '../types'

// Scatter of the power–decision trade-off: all evaluated designs (faint) + the
// non-dominated Pareto front (connected teal). Target lines mark the spec box.
export default function ParetoChart({ res, pTarget, dTarget, theme }: { res: ParetoResult; pTarget: number; dTarget: number; theme: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim()
    const draw = () => {
      const r = cv.getBoundingClientRect()
      const W = r.width, H = r.height
      cv.width = W * dpr; cv.height = H * dpr
      const ctx = cv.getContext('2d')!
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, W, H)
      const padL = 40, padR = 12, padT = 12, padB = 30
      const pts = [...res.all.filter((p) => p.power_uw != null && p.decision_time_ps != null),
        ...res.front.filter((p) => p.power_uw != null && p.decision_time_ps != null)]
      if (!pts.length) return
      const pw = pts.map((p) => p.power_uw as number)
      const dc = pts.map((p) => p.decision_time_ps as number)
      const pmax = Math.max(...pw, pTarget) * 1.1, pmin = Math.min(...pw) * 0.9
      const dmax = Math.max(...dc, dTarget) * 1.1, dmin = Math.min(...dc) * 0.9
      const X = (v: number) => padL + ((v - pmin) / (pmax - pmin || 1)) * (W - padL - padR)
      const Y = (v: number) => (H - padB) - ((v - dmin) / (dmax - dmin || 1)) * (H - padT - padB)

      ctx.strokeStyle = css('--line-soft'); ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(padL, padT); ctx.lineTo(padL, H - padB); ctx.lineTo(W - padR, H - padB); ctx.stroke()
      // spec target lines
      ctx.strokeStyle = css('--warn'); ctx.setLineDash([4, 3]); ctx.globalAlpha = 0.7
      ctx.beginPath(); ctx.moveTo(X(pTarget), padT); ctx.lineTo(X(pTarget), H - padB); ctx.stroke()
      ctx.beginPath(); ctx.moveTo(padL, Y(dTarget)); ctx.lineTo(W - padR, Y(dTarget)); ctx.stroke()
      ctx.setLineDash([]); ctx.globalAlpha = 1

      // all evaluated points (faint)
      for (const p of res.all) {
        if (p.power_uw == null || p.decision_time_ps == null) continue
        ctx.beginPath(); ctx.arc(X(p.power_uw), Y(p.decision_time_ps), 2, 0, 7)
        ctx.fillStyle = p.feasible ? css('--muted') : css('--bad')
        ctx.globalAlpha = 0.35; ctx.fill(); ctx.globalAlpha = 1
      }
      // Pareto front (connected)
      const fr = res.front.filter((p) => p.power_uw != null && p.decision_time_ps != null)
      ctx.beginPath()
      fr.forEach((p, i) => { const x = X(p.power_uw!), y = Y(p.decision_time_ps!); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
      ctx.strokeStyle = css('--si'); ctx.lineWidth = 1.6; ctx.stroke()
      for (const p of fr) {
        ctx.beginPath(); ctx.arc(X(p.power_uw!), Y(p.decision_time_ps!), 3.2, 0, 7)
        ctx.fillStyle = css('--si'); ctx.fill()
      }
      ctx.font = '10px ui-monospace, monospace'; ctx.fillStyle = css('--faint')
      ctx.fillText('power µW →', W - 90, H - 8)
      ctx.save(); ctx.translate(11, padT + 70); ctx.rotate(-Math.PI / 2); ctx.fillText('decision ps →', 0, 0); ctx.restore()
    }
    draw()
    const ro = new ResizeObserver(draw); ro.observe(cv)
    return () => ro.disconnect()
  }, [res, pTarget, dTarget, theme])
  return <canvas ref={ref} style={{ width: '100%', height: '260px', display: 'block' }} aria-label="Power vs decision-time Pareto front" />
}

import { useEffect, useRef } from 'react'
import type { VcoParetoResult } from '../types'

// Power ↔ frequency trade-off: all evaluated designs (faint) + the non-dominated
// front (indigo, connected). Upper-left is better (high f, low power).
export default function VcoParetoChart({ res, theme }: { res: VcoParetoResult; theme: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const draw = () => {
      const r = cv.getBoundingClientRect(); const W = r.width, H = r.height
      cv.width = W * dpr; cv.height = H * dpr
      const ctx = cv.getContext('2d')!; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H)
      ctx.fillStyle = '#04090a'; ctx.fillRect(0, 0, W, H)
      const padL = 46, padR = 14, padT = 14, padB = 32
      const pts = [...res.all, ...res.front].filter((p) => p.power_uw != null && p.f_osc_ghz != null)
      if (!pts.length) return
      const pw = pts.map((p) => p.power_uw as number), fq = pts.map((p) => p.f_osc_ghz as number)
      const pmin = Math.min(...pw) * 0.9, pmax = Math.max(...pw) * 1.05
      const fmin = Math.min(...fq) * 0.95, fmax = Math.max(...fq) * 1.05
      const X = (v: number) => padL + ((v - pmin) / (pmax - pmin || 1)) * (W - padL - padR)
      const Y = (v: number) => (H - padB) - ((v - fmin) / (fmax - fmin || 1)) * (H - padT - padB)
      ctx.strokeStyle = '#143433'; ctx.lineWidth = 1; ctx.strokeRect(padL, padT, W - padL - padR, H - padT - padB)
      ctx.font = '10px ui-monospace, monospace'; ctx.fillStyle = '#4f7f7d'
      ctx.fillText(`${Math.round(pmin)}`, padL, H - 16); ctx.fillText(`${Math.round(pmax)}µW`, W - padR - 40, H - 16)
      ctx.fillText(fmax.toFixed(1), 8, Y(fmax) + 8); ctx.fillText(fmin.toFixed(1), 8, Y(fmin))
      // all points (faint)
      for (const p of res.all) {
        if (p.power_uw == null || p.f_osc_ghz == null) continue
        ctx.beginPath(); ctx.arc(X(p.power_uw), Y(p.f_osc_ghz), 2, 0, 7)
        ctx.fillStyle = p.feasible ? '#4f7f7d' : '#ff6fae'; ctx.globalAlpha = 0.4; ctx.fill(); ctx.globalAlpha = 1
      }
      // front (connected, indigo)
      const fr = res.front.filter((p) => p.power_uw != null && p.f_osc_ghz != null)
      ctx.beginPath(); fr.forEach((p, i) => { const x = X(p.power_uw!), y = Y(p.f_osc_ghz!); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
      ctx.strokeStyle = '#8f6fff'; ctx.lineWidth = 1.8; ctx.stroke()
      for (const p of fr) { ctx.beginPath(); ctx.arc(X(p.power_uw!), Y(p.f_osc_ghz!), 3.4, 0, 7); ctx.fillStyle = '#8f6fff'; ctx.fill() }
      ctx.fillStyle = '#4f7f7d'; ctx.fillText('power µW →', W - 96, H - 3)
      ctx.save(); ctx.translate(12, padT + 70); ctx.rotate(-Math.PI / 2); ctx.fillText('f_osc GHz →', 0, 0); ctx.restore()
    }
    draw(); const ro = new ResizeObserver(draw); ro.observe(cv); return () => ro.disconnect()
  }, [res, theme])
  return <canvas ref={ref} style={{ width: '100%', height: '260px', display: 'block' }} aria-label="VCO power vs frequency Pareto front" />
}

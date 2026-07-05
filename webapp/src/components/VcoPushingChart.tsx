import { useEffect, useRef } from 'react'
import type { VcoPushing } from '../types'

// Supply pushing: oscillation frequency vs VDD (fixed V_ctrl). Slope = pushing (GHz/V).
export default function VcoPushingChart({ push, theme }: { push: VcoPushing; theme: string }) {
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
      const padL = 46, padR = 14, padT = 14, padB = 30
      const pts = push.points.filter((p) => p.f_osc_ghz != null)
      if (!pts.length) return
      const vs = push.points.map((p) => p.vdd)
      const vmin = Math.min(...vs), vmax = Math.max(...vs)
      const fmax = Math.max(...pts.map((p) => p.f_osc_ghz as number)) * 1.08
      const fmin = Math.min(...pts.map((p) => p.f_osc_ghz as number)) * 0.92
      const X = (v: number) => padL + ((v - vmin) / (vmax - vmin || 1)) * (W - padL - padR)
      const Y = (f: number) => (H - padB) - ((f - fmin) / (fmax - fmin || 1)) * (H - padT - padB)
      ctx.strokeStyle = '#143433'; ctx.lineWidth = 1; ctx.strokeRect(padL, padT, W - padL - padR, H - padT - padB)
      ctx.font = '10px ui-monospace, monospace'; ctx.fillStyle = '#4f7f7d'
      ctx.fillText(`${vmin}V`, padL, H - 14); ctx.fillText(`${vmax}V`, W - padR - 24, H - 14)
      ctx.fillText(fmax.toFixed(2), 6, Y(fmax) + 8); ctx.fillText(fmin.toFixed(2), 6, Y(fmin) - 2)
      ctx.beginPath(); pts.forEach((p, i) => { const x = X(p.vdd), y = Y(p.f_osc_ghz as number); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
      ctx.strokeStyle = '#8f6fff'; ctx.lineWidth = 2.2; ctx.shadowColor = '#8f6fff'; ctx.shadowBlur = 7; ctx.stroke(); ctx.shadowBlur = 0
      for (const p of pts) { ctx.beginPath(); ctx.arc(X(p.vdd), Y(p.f_osc_ghz as number), 3, 0, 7); ctx.fillStyle = '#8f6fff'; ctx.fill() }
      ctx.fillStyle = '#4f7f7d'; ctx.fillText('VDD →', W - 60, H - 3)
      ctx.save(); ctx.translate(12, padT + 70); ctx.rotate(-Math.PI / 2); ctx.fillText('f_osc GHz →', 0, 0); ctx.restore()
    }
    draw(); const ro = new ResizeObserver(draw); ro.observe(cv); return () => ro.disconnect()
  }, [push, theme])
  return <canvas ref={ref} style={{ width: '100%', height: '230px', display: 'block' }} aria-label="VCO supply pushing: frequency vs VDD" />
}

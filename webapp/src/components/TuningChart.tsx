import { useEffect, useRef } from 'react'
import type { VcoTuning } from '../types'

// VCO transfer curve: oscillation frequency vs control voltage. Non-oscillating
// points are dropped; the linear region's slope is Kvco. Dark ViVA-like canvas.
export default function TuningChart({ tuning, theme }: { tuning: VcoTuning; theme: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const draw = () => {
      const r = cv.getBoundingClientRect()
      const W = r.width, H = r.height
      cv.width = W * dpr; cv.height = H * dpr
      const ctx = cv.getContext('2d')!
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, W, H)
      ctx.fillStyle = '#04090a'; ctx.fillRect(0, 0, W, H)
      const padL = 46, padR = 14, padT = 14, padB = 32
      const pts = tuning.points.filter((p) => p.f_osc_ghz != null)
      if (!pts.length) return
      const vs = tuning.points.map((p) => p.vctrl_v)
      const vmin = Math.min(...vs), vmax = Math.max(...vs)
      const fmax = Math.max(...pts.map((p) => p.f_osc_ghz as number)) * 1.1
      const X = (v: number) => padL + ((v - vmin) / (vmax - vmin || 1)) * (W - padL - padR)
      const Y = (f: number) => (H - padB) - (f / (fmax || 1)) * (H - padT - padB)

      ctx.strokeStyle = '#143433'; ctx.lineWidth = 1
      for (let i = 0; i <= 5; i++) { const x = padL + ((W - padL - padR) * i) / 5; ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke() }
      for (let i = 0; i <= 4; i++) { const y = padT + ((H - padT - padB) * i) / 4; ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke() }
      ctx.strokeStyle = '#0e2626'; ctx.strokeRect(padL, padT, W - padL - padR, H - padT - padB)

      ctx.font = '10px ui-monospace, monospace'; ctx.fillStyle = '#4f7f7d'
      for (let i = 0; i <= 4; i++) { const f = (fmax * i) / 4; ctx.fillText(f.toFixed(1), 8, Y(f) + 3) }
      ctx.fillText(`${vmin}V`, padL, H - 16); ctx.fillText(`${vmax}V`, W - padR - 22, H - 16)

      // non-oscillating markers (red x at baseline)
      for (const p of tuning.points) {
        if (p.f_osc_ghz == null) { ctx.fillStyle = '#ff6fae'; ctx.fillText('×', X(p.vctrl_v) - 3, H - padB - 3) }
      }
      // f-vs-Vctrl curve
      ctx.beginPath()
      pts.forEach((p, i) => { const x = X(p.vctrl_v), y = Y(p.f_osc_ghz as number); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
      ctx.strokeStyle = '#39d7d7'; ctx.lineWidth = 2.2; ctx.lineJoin = 'round'
      ctx.shadowColor = '#39d7d7'; ctx.shadowBlur = 8; ctx.stroke(); ctx.shadowBlur = 0
      for (const p of pts) { ctx.beginPath(); ctx.arc(X(p.vctrl_v), Y(p.f_osc_ghz as number), 3, 0, 7); ctx.fillStyle = '#39d7d7'; ctx.fill() }

      ctx.fillStyle = '#4f7f7d'
      ctx.fillText('V_ctrl →', W - 74, H - 4)
      ctx.save(); ctx.translate(12, padT + 70); ctx.rotate(-Math.PI / 2); ctx.fillText('f_osc GHz →', 0, 0); ctx.restore()
    }
    draw()
    const ro = new ResizeObserver(draw); ro.observe(cv)
    return () => ro.disconnect()
  }, [tuning, theme])
  return <canvas ref={ref} style={{ width: '100%', height: '260px', display: 'block' }} aria-label="VCO tuning curve: frequency vs control voltage" />
}

import { useEffect, useRef } from 'react'
import type { VcoPhaseNoise } from '../types'

// Ring-VCO phase noise L(Δf) vs offset frequency (log-x, dBc/Hz). The −20 dB/dec
// slope is the thermal (1/f²) region. A marker highlights the 1 MHz spot.
export default function VcoPhaseNoiseChart({ pn, theme }: { pn: VcoPhaseNoise; theme: string }) {
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
      const padL = 48, padR = 14, padT = 14, padB = 32
      const pts = pn.points
      if (!pts.length) return
      const lx = pts.map((p) => Math.log10(p.offset_hz))
      const xmin = Math.min(...lx), xmax = Math.max(...lx)
      const ys = pts.map((p) => p.L_dbc)
      const ymax = Math.max(...ys) + 5, ymin = Math.min(...ys) - 5
      const X = (l: number) => padL + ((l - xmin) / (xmax - xmin || 1)) * (W - padL - padR)
      const Y = (v: number) => padT + ((ymax - v) / (ymax - ymin || 1)) * (H - padT - padB)
      ctx.strokeStyle = '#143433'; ctx.lineWidth = 1
      for (let d = Math.ceil(xmin); d <= Math.floor(xmax); d++) {
        ctx.globalAlpha = 0.5; ctx.beginPath(); ctx.moveTo(X(d), padT); ctx.lineTo(X(d), H - padB); ctx.stroke(); ctx.globalAlpha = 1
        const hz = Math.pow(10, d)
        const lbl = hz >= 1e6 ? `${hz / 1e6}M` : hz >= 1e3 ? `${hz / 1e3}k` : `${hz}`
        ctx.fillStyle = '#4f7f7d'; ctx.font = '10px ui-monospace, monospace'; ctx.fillText(lbl, X(d) - 8, H - 16)
      }
      ctx.strokeStyle = '#143433'; ctx.strokeRect(padL, padT, W - padL - padR, H - padT - padB)
      // y labels (dBc/Hz)
      ctx.fillStyle = '#4f7f7d'
      for (let i = 0; i <= 4; i++) { const v = ymin + (ymax - ymin) * i / 4; ctx.fillText(Math.round(v).toString(), 6, Y(v) + 3) }
      // measured (trnoise) cross-check — dashed cyan, drawn under the analytic
      const meas = pn.measured?.points
      if (meas && meas.length) {
        ctx.beginPath(); meas.forEach((p, i) => { const x = X(Math.log10(p.offset_hz)), y = Y(p.L_dbc); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
        ctx.strokeStyle = '#39d7d7'; ctx.lineWidth = 1.6; ctx.setLineDash([5, 3]); ctx.stroke(); ctx.setLineDash([])
      }
      // analytic curve
      ctx.beginPath(); pts.forEach((p, i) => { const x = X(Math.log10(p.offset_hz)), y = Y(p.L_dbc); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
      ctx.strokeStyle = '#8f6fff'; ctx.lineWidth = 2.2; ctx.shadowColor = '#8f6fff'; ctx.shadowBlur = 7; ctx.stroke(); ctx.shadowBlur = 0
      for (const p of pts) { ctx.beginPath(); ctx.arc(X(Math.log10(p.offset_hz)), Y(p.L_dbc), 2.6, 0, 7); ctx.fillStyle = '#8f6fff'; ctx.fill() }
      // legend
      ctx.font = '9px ui-monospace, monospace'
      ctx.fillStyle = '#8f6fff'; ctx.fillText('— analytic', W - 130, padT + 10)
      if (meas && meas.length) { ctx.fillStyle = '#39d7d7'; ctx.fillText('-- SPICE trnoise', W - 130, padT + 22) }
      // 1 MHz marker
      const x1m = X(6)
      ctx.strokeStyle = '#e6c84f'; ctx.setLineDash([4, 3]); ctx.globalAlpha = 0.8
      ctx.beginPath(); ctx.moveTo(x1m, padT); ctx.lineTo(x1m, H - padB); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1
      ctx.fillStyle = '#e6c84f'; ctx.fillText(`${pn.L_1mhz_dbc} @1MHz`, x1m + 4, padT + 10)
      ctx.fillStyle = '#4f7f7d'; ctx.fillText('offset Δf →', W - 86, H - 3)
      ctx.save(); ctx.translate(13, padT + 84); ctx.rotate(-Math.PI / 2); ctx.fillText('L(Δf) dBc/Hz →', 0, 0); ctx.restore()
    }
    draw(); const ro = new ResizeObserver(draw); ro.observe(cv); return () => ro.disconnect()
  }, [pn, theme])
  return <canvas ref={ref} style={{ width: '100%', height: '260px', display: 'block' }} aria-label="VCO phase noise vs offset frequency" />
}

import { useEffect, useRef } from 'react'
import type { VcoWaveform } from '../types'

// Real ring-VCO oscillation: two ring nodes (o1, o2) vs time, ViVA-style dark canvas.
export default function VcoWaveformChart({ wf, theme }: { wf: VcoWaveform; theme: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const cv = ref.current
    if (!cv || !wf.t_ns?.length) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const draw = () => {
      const r = cv.getBoundingClientRect(); const W = r.width, H = r.height
      cv.width = W * dpr; cv.height = H * dpr
      const ctx = cv.getContext('2d')!; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H)
      ctx.fillStyle = '#04090a'; ctx.fillRect(0, 0, W, H)
      const padL = 34, padR = 40, padT = 12, padB = 22
      const x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB
      const tmax = wf.t_ns[wf.t_ns.length - 1] || 1
      const vmax = wf.vdd * 1.15, vmin = -0.15 * wf.vdd
      const X = (t: number) => x0 + (t / tmax) * (x1 - x0)
      const Y = (v: number) => y1 - ((v - vmin) / (vmax - vmin)) * (y1 - y0)
      ctx.strokeStyle = '#0e2626'; ctx.lineWidth = 1
      for (let i = 0; i <= 10; i++) { const x = x0 + ((x1 - x0) * i) / 10; ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke() }
      for (let i = 0; i <= 4; i++) { const y = y0 + ((y1 - y0) * i) / 4; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke() }
      ctx.strokeStyle = '#143433'; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0)
      const trace = (arr: number[], col: string, w: number, glow = false) => {
        ctx.beginPath(); wf.t_ns.forEach((t, i) => { const px = X(t), py = Y(arr[i]); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py) })
        ctx.strokeStyle = col; ctx.lineWidth = w; ctx.lineJoin = 'round'; ctx.shadowColor = col; ctx.shadowBlur = glow ? 7 : 0; ctx.stroke(); ctx.shadowBlur = 0
      }
      trace(wf.o2, '#ff6fae', 1.5)
      trace(wf.o1, '#39d7d7', 2, true)
      ctx.font = '10px ui-monospace, monospace'
      ctx.fillStyle = '#39d7d7'; ctx.fillText('o1', x1 + 4, Y(wf.o1[wf.o1.length - 1]) + 3)
      ctx.fillStyle = '#ff6fae'; ctx.fillText('o2', x1 + 4, Y(wf.o2[wf.o2.length - 1]) + 3)
      ctx.fillStyle = '#4f7f7d'; ctx.fillText('0', x0, y1 + 14); ctx.fillText(`${tmax.toFixed(1)} ns`, x1 - 32, y1 + 14)
    }
    draw(); const ro = new ResizeObserver(draw); ro.observe(cv); return () => ro.disconnect()
  }, [wf, theme])
  return <canvas ref={ref} style={{ width: '100%', height: '200px', display: 'block' }} aria-label="Ring VCO oscillation waveform" />
}

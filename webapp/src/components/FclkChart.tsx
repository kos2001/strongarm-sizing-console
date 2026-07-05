import { useEffect, useRef } from 'react'
import type { MaxFclkResult } from '../types'

// Energy per conversion vs clock frequency. Each swept period is a point (teal =
// resolves + resets within the period, red = fails); a dashed marker shows the
// maximum usable f_clk.
export default function FclkChart({ res, theme }: { res: MaxFclkResult; theme: string }) {
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
      const padL = 52, padR = 14, padT = 14, padB = 34
      const pts = res.points.filter((p) => p.energy_fj != null)
      if (!pts.length) return
      const fs = pts.map((p) => p.fclk_ghz)
      const es = pts.map((p) => p.energy_fj as number)
      const fmax = Math.max(...fs) * 1.05, fmin = 0
      const emax = Math.max(...es) * 1.05, emin = Math.min(...es) * 0.9
      const X = (v: number) => padL + ((v - fmin) / (fmax - fmin || 1)) * (W - padL - padR)
      const Y = (v: number) => (H - padB) - ((v - emin) / (emax - emin || 1)) * (H - padT - padB)

      ctx.strokeStyle = css('--line-soft'); ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(padL, padT); ctx.lineTo(padL, H - padB); ctx.lineTo(W - padR, H - padB); ctx.stroke()
      ctx.font = '10px ui-monospace, monospace'; ctx.fillStyle = css('--faint')

      // max f_clk marker
      if (res.max_fclk_ghz != null) {
        ctx.strokeStyle = css('--warn'); ctx.setLineDash([4, 3]); ctx.globalAlpha = 0.85
        ctx.beginPath(); ctx.moveTo(X(res.max_fclk_ghz), padT); ctx.lineTo(X(res.max_fclk_ghz), H - padB); ctx.stroke()
        ctx.setLineDash([]); ctx.globalAlpha = 1
        ctx.fillStyle = css('--warn'); ctx.fillText(`max ${res.max_fclk_ghz} GHz`, X(res.max_fclk_ghz) - 30, padT + 10)
      }
      // connecting line
      const sorted = [...pts].sort((a, b) => a.fclk_ghz - b.fclk_ghz)
      ctx.strokeStyle = css('--muted'); ctx.lineWidth = 1; ctx.globalAlpha = 0.5; ctx.beginPath()
      sorted.forEach((p, i) => { const x = X(p.fclk_ghz), y = Y(p.energy_fj as number); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
      ctx.stroke(); ctx.globalAlpha = 1
      // points
      for (const p of pts) {
        ctx.beginPath(); ctx.arc(X(p.fclk_ghz), Y(p.energy_fj as number), 4, 0, 7)
        ctx.fillStyle = p.ok ? css('--si') : css('--bad'); ctx.fill()
      }
      ctx.fillStyle = css('--faint')
      ctx.fillText('f_clk GHz →', W - 82, H - 6)
      ctx.save(); ctx.translate(13, padT + 84); ctx.rotate(-Math.PI / 2); ctx.fillText('energy fJ/conv →', 0, 0); ctx.restore()
    }
    draw()
    const ro = new ResizeObserver(draw); ro.observe(cv)
    return () => ro.disconnect()
  }, [res, theme])
  return <canvas ref={ref} style={{ width: '100%', height: '260px', display: 'block' }} aria-label="Energy per conversion vs clock frequency" />
}

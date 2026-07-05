import { useEffect, useRef } from 'react'
import type { BerResult } from '../types'

// Decision error rate vs input amplitude (log–log). Two curves: the per-decision
// noise floor 0.5·erfc(Vin/√2σ_vn), and the offset-broadened total. The BER
// target line marks the minimum detectable input.
export default function BerChart({ res, theme }: { res: BerResult; theme: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim()
    const FLOOR = 1e-12
    const draw = () => {
      const r = cv.getBoundingClientRect()
      const W = r.width, H = r.height
      cv.width = W * dpr; cv.height = H * dpr
      const ctx = cv.getContext('2d')!
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, W, H)
      const padL = 48, padR = 14, padT = 14, padB = 34
      const pts = res.points
      if (!pts.length) return
      const lx = pts.map((p) => Math.log10(p.vin_v))
      const xmin = Math.min(...lx), xmax = Math.max(...lx)
      const ylo = Math.log10(FLOOR), yhi = 0 // BER 1e-12 .. 1
      const X = (lv: number) => padL + ((lv - xmin) / (xmax - xmin || 1)) * (W - padL - padR)
      const Y = (b: number) => { const ly = Math.log10(Math.max(b, FLOOR)); return padT + ((yhi - ly) / (yhi - ylo)) * (H - padT - padB) }

      ctx.strokeStyle = css('--line-soft'); ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(padL, padT); ctx.lineTo(padL, H - padB); ctx.lineTo(W - padR, H - padB); ctx.stroke()
      ctx.font = '10px ui-monospace, monospace'; ctx.fillStyle = css('--faint')
      // y decade labels
      for (let d = 0; d >= -12; d -= 3) { ctx.globalAlpha = 0.22; ctx.beginPath(); ctx.moveTo(padL, Y(Math.pow(10, d))); ctx.lineTo(W - padR, Y(Math.pow(10, d))); ctx.stroke(); ctx.globalAlpha = 1; ctx.fillText(`1e${d}`, 6, Y(Math.pow(10, d)) + 3) }
      // x decade labels
      for (let d = Math.ceil(xmin); d <= Math.floor(xmax); d++) { const mv = Math.pow(10, d) * 1e3; ctx.fillText(mv >= 1 ? `${mv}mV` : `${(mv * 1e3).toFixed(0)}µV`, X(d) - 12, H - 20) }
      // BER target
      ctx.strokeStyle = css('--warn'); ctx.setLineDash([4, 3]); ctx.globalAlpha = 0.8
      ctx.beginPath(); ctx.moveTo(padL, Y(res.ber_target)); ctx.lineTo(W - padR, Y(res.ber_target)); ctx.stroke()
      ctx.setLineDash([]); ctx.globalAlpha = 1

      const line = (key: 'ber_noise' | 'ber_total', color: string) => {
        ctx.strokeStyle = color; ctx.lineWidth = 1.8; ctx.beginPath()
        pts.forEach((p, i) => { const x = X(Math.log10(p.vin_v)), y = Y(p[key]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
        ctx.stroke()
      }
      line('ber_total', css('--bad'))   // offset-broadened (worse)
      line('ber_noise', css('--si'))    // noise-only floor

      ctx.fillStyle = css('--faint')
      ctx.fillText('input Δ (log) →', W - 96, H - 6)
      ctx.save(); ctx.translate(13, padT + 60); ctx.rotate(-Math.PI / 2); ctx.fillText('BER (log) →', 0, 0); ctx.restore()
    }
    draw()
    const ro = new ResizeObserver(draw); ro.observe(cv)
    return () => ro.disconnect()
  }, [res, theme])
  return <canvas ref={ref} style={{ width: '100%', height: '270px', display: 'block' }} aria-label="Decision error rate vs input amplitude" />
}

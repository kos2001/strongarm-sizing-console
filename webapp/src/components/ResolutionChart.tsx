import { useEffect, useRef } from 'react'
import type { ResolutionResult } from '../types'

// One amplitude axis, both consequences of it.
//
// The metastability, offset and BER views were three pages describing one
// variable: how small a differential input this comparator can be given. Drawn
// apart they hide the thing that matters — at 10 µV the latch still resolves to a
// rail (metastability says "resolved") while the answer is a coin flip (BER 0.5).
// Overlaid, the useful regions are obvious: left of σ_total it is guessing, and
// right of min_input_total it is both fast and correct.
//
// Left axis: measured decision time (linear ps). Right axis: error probability
// (log). Vertical markers: σ_noise, σ_total, and the minimum input meeting the
// BER target with and without chip-to-chip offset.
export default function ResolutionChart({ res, theme }: { res: ResolutionResult; theme: string }) {
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
      const padL = 52, padR = 52, padT = 16, padB = 40
      const pts = res.points
      if (!pts.length) return

      const lx = pts.map((p) => Math.log10(p.vin_v))
      const xmin = Math.min(...lx), xmax = Math.max(...lx)
      const X = (lv: number) => padL + ((lv - xmin) / (xmax - xmin || 1)) * (W - padL - padR)
      const Xv = (v: number) => X(Math.log10(v))

      const ts = pts.map((p) => p.decision_time_ps).filter((t): t is number => t != null)
      const tmax = ts.length ? Math.max(...ts) * 1.08 : 1
      const YT = (t: number) => padT + (1 - t / tmax) * (H - padT - padB)
      const ylo = Math.log10(FLOOR), yhi = 0
      const YB = (b: number) => {
        const ly = Math.log10(Math.max(b, FLOOR))
        return padT + ((yhi - ly) / (yhi - ylo)) * (H - padT - padB)
      }

      // frame
      ctx.strokeStyle = css('--line-soft'); ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(padL, padT); ctx.lineTo(padL, H - padB); ctx.lineTo(W - padR, H - padB)
      ctx.moveTo(W - padR, padT); ctx.lineTo(W - padR, H - padB)
      ctx.stroke()
      ctx.font = '10px ui-monospace, monospace'

      // x decades
      ctx.fillStyle = css('--faint')
      for (let d = Math.ceil(xmin); d <= Math.floor(xmax); d++) {
        const mv = Math.pow(10, d) * 1e3
        ctx.fillText(mv >= 1 ? `${mv}mV` : `${(mv * 1e3).toFixed(0)}µV`, X(d) - 13, H - 24)
      }
      // right axis BER decades
      for (let d = 0; d >= -12; d -= 3) {
        ctx.globalAlpha = 0.18; ctx.strokeStyle = css('--line-soft')
        ctx.beginPath(); ctx.moveTo(padL, YB(Math.pow(10, d))); ctx.lineTo(W - padR, YB(Math.pow(10, d))); ctx.stroke()
        ctx.globalAlpha = 1
        ctx.fillText(`1e${d}`, W - padR + 6, YB(Math.pow(10, d)) + 3)
      }
      // left axis time ticks
      for (let i = 0; i <= 3; i++) {
        const t = (tmax * i) / 3
        ctx.fillText(`${Math.round(t)}`, 6, YT(t) + 3)
      }

      // region shading: below sigma_total the decision is a guess
      const sigTot = res.markers_uv.sigma_total * 1e-6
      const minTot = res.markers_uv.min_input_total * 1e-6
      ctx.fillStyle = css('--bad'); ctx.globalAlpha = 0.07
      ctx.fillRect(padL, padT, Math.max(0, Xv(sigTot) - padL), H - padT - padB)
      ctx.fillStyle = css('--ok'); ctx.globalAlpha = 0.07
      ctx.fillRect(Math.min(W - padR, Xv(minTot)), padT,
                   Math.max(0, W - padR - Xv(minTot)), H - padT - padB)
      ctx.globalAlpha = 1

      // BER target line
      ctx.strokeStyle = css('--warn'); ctx.setLineDash([4, 3]); ctx.globalAlpha = 0.8
      ctx.beginPath(); ctx.moveTo(padL, YB(res.ber_target)); ctx.lineTo(W - padR, YB(res.ber_target)); ctx.stroke()
      ctx.setLineDash([]); ctx.globalAlpha = 1

      // markers
      const marker = (v: number, color: string, label: string) => {
        const x = Xv(v)
        if (x < padL || x > W - padR) return
        ctx.strokeStyle = color; ctx.globalAlpha = 0.55; ctx.setLineDash([2, 3])
        ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke()
        ctx.setLineDash([]); ctx.globalAlpha = 1
        ctx.fillStyle = color; ctx.fillText(label, x + 3, padT + 10)
      }
      marker(res.markers_uv.sigma_noise * 1e-6, css('--si'), 'σn')
      marker(sigTot, css('--bad'), 'σtot')
      marker(minTot, css('--ok'), 'min Δ')

      // BER curves (right axis)
      const berLine = (key: 'ber_noise' | 'ber_total', color: string) => {
        ctx.strokeStyle = color; ctx.lineWidth = 1.6; ctx.beginPath()
        pts.forEach((p, i) => { const x = Xv(p.vin_v), y = YB(p[key]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
        ctx.stroke()
      }
      berLine('ber_total', css('--bad'))
      berLine('ber_noise', css('--si'))

      // decision-time curve (left axis) — thicker, it is the measured one
      ctx.strokeStyle = css('--accent') || css('--text')
      ctx.lineWidth = 2.2; ctx.beginPath()
      let started = false
      pts.forEach((p) => {
        if (p.decision_time_ps == null) return
        const x = Xv(p.vin_v), y = YT(p.decision_time_ps)
        started ? ctx.lineTo(x, y) : ctx.moveTo(x, y); started = true
      })
      ctx.stroke()
      pts.forEach((p) => {
        if (p.decision_time_ps == null) return
        ctx.fillStyle = p.resolved ? (css('--accent') || css('--text')) : css('--bad')
        ctx.beginPath(); ctx.arc(Xv(p.vin_v), YT(p.decision_time_ps), 2.4, 0, Math.PI * 2); ctx.fill()
      })

      // axis titles
      ctx.fillStyle = css('--faint')
      ctx.fillText('input Δ (log) →', W / 2 - 34, H - 8)
      ctx.save(); ctx.translate(14, padT + 76); ctx.rotate(-Math.PI / 2); ctx.fillText('t_dec (ps)', 0, 0); ctx.restore()
      ctx.save(); ctx.translate(W - 12, padT + 74); ctx.rotate(-Math.PI / 2); ctx.fillText('BER (log)', 0, 0); ctx.restore()
    }
    draw()
    const ro = new ResizeObserver(draw); ro.observe(cv)
    return () => ro.disconnect()
  }, [res, theme])
  return <canvas ref={ref} style={{ width: '100%', height: '320px', display: 'block' }}
                 aria-label="Decision time and error rate vs input amplitude on one axis" />
}

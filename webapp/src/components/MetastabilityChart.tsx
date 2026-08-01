import { useEffect, useRef } from 'react'
import type { MetastabilityResult } from '../types'

// Decision time vs input differential amplitude on a log-x axis. As Vin -> 0 the
// regeneration time diverges logarithmically; the fitted line t = tau·ln(1/Vin)+c
// (slope = regeneration time constant tau) is overlaid on the measured points.
export default function MetastabilityChart({ res, theme, selected, onSelect }: {
  res: MetastabilityResult; theme: string
  selected?: number | null; onSelect?: (idx: number | null) => void
}) {
  const ref = useRef<HTMLCanvasElement>(null)
  // 클릭 히트테스트용 — draw() 가 계산한 각 점의 픽셀 좌표(res.points 인덱스)
  const geom = useRef<{ x: number; y: number; idx: number }[]>([])
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
      const padL = 46, padR = 14, padT = 14, padB = 34
      const pts = res.points.filter((p) => p.resolved && p.decision_time_ps != null)
      if (!pts.length) return
      const lx = pts.map((p) => Math.log10(p.vin_v))
      const ty = pts.map((p) => p.decision_time_ps as number)
      const xmin = Math.min(...lx), xmax = Math.max(...lx)
      const ymin = Math.min(...ty) * 0.92, ymax = Math.max(...ty) * 1.08
      const X = (lv: number) => padL + ((lv - xmin) / (xmax - xmin || 1)) * (W - padL - padR)
      const Y = (v: number) => (H - padB) - ((v - ymin) / (ymax - ymin || 1)) * (H - padT - padB)

      // axes + decade gridlines
      ctx.strokeStyle = css('--line-soft'); ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(padL, padT); ctx.lineTo(padL, H - padB); ctx.lineTo(W - padR, H - padB); ctx.stroke()
      ctx.font = '10px ui-monospace, monospace'; ctx.fillStyle = css('--faint')
      for (let d = Math.ceil(xmin); d <= Math.floor(xmax); d++) {
        ctx.globalAlpha = 0.25; ctx.beginPath(); ctx.moveTo(X(d), padT); ctx.lineTo(X(d), H - padB); ctx.stroke(); ctx.globalAlpha = 1
        const mv = Math.pow(10, d) * 1e3
        ctx.fillText(mv >= 1 ? `${mv}mV` : `${(mv * 1e3).toFixed(0)}µV`, X(d) - 12, H - 20)
      }

      // fitted tau line: t = tau·ln(1/Vin) + c  = -tau·ln(10)·log10(Vin) + c
      if (res.tau_ps != null && res.intercept_ps != null) {
        const f = (lv: number) => -res.tau_ps! * Math.log(10) * lv + res.intercept_ps!
        ctx.strokeStyle = css('--ag'); ctx.setLineDash([5, 3]); ctx.globalAlpha = 0.8
        ctx.beginPath(); ctx.moveTo(X(xmin), Y(f(xmin))); ctx.lineTo(X(xmax), Y(f(xmax))); ctx.stroke()
        ctx.setLineDash([]); ctx.globalAlpha = 1
      }
      // measured points + connecting line
      ctx.strokeStyle = css('--si'); ctx.lineWidth = 1.6; ctx.beginPath()
      pts.forEach((p, i) => { const x = X(Math.log10(p.vin_v)), y = Y(p.decision_time_ps as number); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
      ctx.stroke()
      for (const p of pts) { ctx.beginPath(); ctx.arc(X(Math.log10(p.vin_v)), Y(p.decision_time_ps as number), 3, 0, 7); ctx.fillStyle = css('--si'); ctx.fill() }
      geom.current = pts.map((p) => ({ x: X(Math.log10(p.vin_v)), y: Y(p.decision_time_ps as number), idx: res.points.indexOf(p) }))
      // 선택점 하이라이트(링 + 값 라벨)
      if (selected != null && res.points[selected]?.decision_time_ps != null) {
        const p = res.points[selected]
        const x = X(Math.log10(p.vin_v)), y = Y(p.decision_time_ps as number)
        ctx.beginPath(); ctx.arc(x, y, 6.5, 0, 7)
        ctx.strokeStyle = css('--warn'); ctx.lineWidth = 2; ctx.stroke()
        ctx.fillStyle = css('--warn')
        const mv = p.vin_v * 1e3
        ctx.fillText(`${mv >= 1 ? mv.toFixed(mv < 10 ? 1 : 0) + 'mV' : (mv * 1e3).toFixed(0) + 'µV'} · ${p.decision_time_ps}ps`, Math.min(x + 9, W - 130), y - 9)
      }

      ctx.fillStyle = css('--faint')
      ctx.fillText('input Δ (log) →', W - 96, H - 6)
      ctx.save(); ctx.translate(12, padT + 92); ctx.rotate(-Math.PI / 2); ctx.fillText('decision ps →', 0, 0); ctx.restore()
    }
    draw()
    const ro = new ResizeObserver(draw); ro.observe(cv)
    return () => ro.disconnect()
  }, [res, theme, selected])
  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!onSelect) return
    const r = ref.current!.getBoundingClientRect()
    const mx = e.clientX - r.left, my = e.clientY - r.top
    let best: { idx: number; d2: number } | null = null
    for (const g of geom.current) {
      const d2 = (g.x - mx) ** 2 + (g.y - my) ** 2
      if (d2 <= 12 ** 2 && (!best || d2 < best.d2)) best = { idx: g.idx, d2 }
    }
    onSelect(best ? best.idx : null)
  }
  return <canvas ref={ref} onClick={handleClick}
    style={{ width: '100%', height: '270px', display: 'block', cursor: onSelect ? 'pointer' : undefined }}
    aria-label="Decision time vs input amplitude (metastability) — click a point for details" />
}

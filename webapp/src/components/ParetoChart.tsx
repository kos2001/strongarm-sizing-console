import { useEffect, useRef } from 'react'
import type { ParetoResult } from '../types'

// Scatter of the power–decision trade-off: all evaluated designs (faint) + the
// non-dominated Pareto front (connected teal). Target lines mark the spec box.
// front 점을 클릭하면 onSelect(index) 로 알린다(빈 곳 클릭 = null) — 부모가
// 소자 크기·측정값 상세 패널을 띄운다. 선택점은 링으로 하이라이트.
export default function ParetoChart({ res, pTarget, dTarget, theme, selected, onSelect }: {
  res: ParetoResult; pTarget: number; dTarget: number; theme: string
  selected?: number | null; onSelect?: (idx: number | null) => void
}) {
  const ref = useRef<HTMLCanvasElement>(null)
  // 클릭 히트테스트용 — draw() 가 계산한 front 점들의 픽셀 좌표를 보관
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
      geom.current = fr.map((p) => ({ x: X(p.power_uw!), y: Y(p.decision_time_ps!), idx: res.front.indexOf(p) }))
      ctx.beginPath()
      fr.forEach((p, i) => { const x = X(p.power_uw!), y = Y(p.decision_time_ps!); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
      ctx.strokeStyle = css('--si'); ctx.lineWidth = 1.6; ctx.stroke()
      for (const p of fr) {
        ctx.beginPath(); ctx.arc(X(p.power_uw!), Y(p.decision_time_ps!), 3.2, 0, 7)
        ctx.fillStyle = css('--si'); ctx.fill()
      }
      // 선택점 하이라이트(링 + 좌표 라벨)
      if (selected != null && res.front[selected]) {
        const p = res.front[selected]
        if (p.power_uw != null && p.decision_time_ps != null) {
          const x = X(p.power_uw), y = Y(p.decision_time_ps)
          ctx.beginPath(); ctx.arc(x, y, 6.5, 0, 7)
          ctx.strokeStyle = css('--warn'); ctx.lineWidth = 2; ctx.stroke()
          ctx.font = '10px ui-monospace, monospace'; ctx.fillStyle = css('--warn')
          ctx.fillText(`${p.power_uw}µW · ${p.decision_time_ps}ps`, Math.min(x + 9, W - 120), y - 8)
        }
      }
      ctx.font = '10px ui-monospace, monospace'; ctx.fillStyle = css('--faint')
      ctx.fillText('power µW →', W - 90, H - 8)
      ctx.save(); ctx.translate(11, padT + 70); ctx.rotate(-Math.PI / 2); ctx.fillText('decision ps →', 0, 0); ctx.restore()
    }
    draw()
    const ro = new ResizeObserver(draw); ro.observe(cv)
    return () => ro.disconnect()
  }, [res, pTarget, dTarget, theme, selected])

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
    style={{ width: '100%', height: '260px', display: 'block', cursor: onSelect ? 'pointer' : undefined }}
    aria-label="Power vs decision-time Pareto front (click a front point for details)" />
}

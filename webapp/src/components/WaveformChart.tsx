import { useEffect, useRef } from 'react'
import type { Waveform } from '../types'
import { VIVA } from '../virtuoso'

// Renders the real ngspice transient (clk, outp, outn vs time). When `before`
// is supplied, its outputs are drawn faintly underneath so the pre/post
// optimization behaviour can be compared on one axis.
export default function WaveformChart({ wf, before, theme }: { wf: Waveform; before?: Waveform | null; theme: string }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const cv = ref.current
    if (!cv || !wf.t_ns?.length) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    const draw = () => {
      const rect = cv.getBoundingClientRect()
      const W = rect.width
      const H = rect.height
      cv.width = W * dpr
      cv.height = H * dpr
      const ctx = cv.getContext('2d')!
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, W, H)

      const padL = 10, padR = 46, padT = 12, padB = 20
      const x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB
      const tmax = wf.t_ns[wf.t_ns.length - 1] || 1
      const vmax = wf.vdd * 1.08
      const X = (t: number) => x0 + (t / tmax) * (x1 - x0)
      const Y = (v: number) => y1 - (v / vmax) * (y1 - y0)

      // ViVA-style black plot canvas + fine grid
      ctx.fillStyle = VIVA.bg
      ctx.fillRect(x0, y0, x1 - x0, y1 - y0)
      ctx.lineWidth = 1
      // minor grid
      ctx.strokeStyle = VIVA.grid
      for (let i = 0; i <= 20; i++) { const x = x0 + ((x1 - x0) * i) / 20; ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke() }
      for (let i = 0; i <= 16; i++) { const y = y0 + ((y1 - y0) * i) / 16; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke() }
      // major grid
      ctx.strokeStyle = VIVA.gridMajor
      for (let i = 0; i <= 5; i++) { const x = x0 + ((x1 - x0) * i) / 5; ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke() }
      for (let i = 0; i <= 4; i++) { const y = y0 + ((y1 - y0) * i) / 4; ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke() }
      // plot border
      ctx.strokeStyle = VIVA.gridMajor; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0)

      const trace = (w: Waveform, arr: keyof Waveform, color: string, width: number, opts: { glow?: boolean; alpha?: number; dash?: number[] } = {}) => {
        const ys = w[arr] as number[]
        ctx.beginPath()
        w.t_ns.forEach((t, i) => { const px = X(t), py = Y(ys[i]); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py) })
        ctx.strokeStyle = color; ctx.lineWidth = width; ctx.lineJoin = 'round'
        ctx.globalAlpha = opts.alpha ?? 1
        ctx.setLineDash(opts.dash ?? [])
        ctx.shadowColor = color; ctx.shadowBlur = opts.glow ? 8 : 0
        ctx.stroke()
        ctx.shadowBlur = 0; ctx.globalAlpha = 1; ctx.setLineDash([])
      }

      const vline = (t: number | null | undefined, color: string, dash: number[], label: string, alpha = 0.65) => {
        if (t == null) return
        const x = X(t)
        ctx.strokeStyle = color; ctx.setLineDash(dash); ctx.globalAlpha = alpha
        ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke()
        ctx.setLineDash([]); ctx.globalAlpha = 1
        ctx.font = '9px ui-monospace, monospace'; ctx.fillStyle = color
        ctx.fillText(label, x + 3, y0 + 9)
      }

      // before (faint, underneath)
      if (before?.t_ns?.length) {
        trace(before, 'outp', VIVA.before, 1.3, { alpha: 0.5, dash: [3, 3] })
        trace(before, 'outn', VIVA.before, 1.3, { alpha: 0.4, dash: [3, 3] })
        vline(before.decision_ns, VIVA.before, [2, 3], 'before', 0.6)
      }
      // clk + decision cursors (after) — ViVA cursor lines
      vline(wf.clk_edge_ns, VIVA.clkCursor, [4, 4], 'clk ↑')
      vline(wf.decision_ns, VIVA.cursor, [2, 3], before ? 'after' : 'decide')
      // traces (ViVA): clk yellow, outn pink, outp cyan (glow)
      trace(wf, 'clk', VIVA.clk, 1.3)
      trace(wf, 'outn', VIVA.outn, 1.8)
      trace(wf, 'outp', VIVA.outp, 2.2, { glow: true })

      ctx.font = '10px ui-monospace, monospace'
      ctx.fillStyle = VIVA.outp; ctx.fillText('outp', x1 + 4, Y(wf.outp[wf.outp.length - 1]) + 3)
      ctx.fillStyle = VIVA.outn; ctx.fillText('outn', x1 + 4, Y(wf.outn[wf.outn.length - 1]) + 3)
      ctx.fillStyle = VIVA.faint
      ctx.fillText('0', x0, y1 + 14)
      ctx.fillText(`${tmax.toFixed(1)} ns`, x1 - 30, y1 + 14)
    }

    draw()
    const ro = new ResizeObserver(draw)
    ro.observe(cv)
    return () => ro.disconnect()
  }, [wf, before, theme])

  return <canvas ref={ref} style={{ width: '100%', height: '190px', display: 'block' }} aria-label="Transient waveform: comparator outputs resolving after the clock edge" />
}

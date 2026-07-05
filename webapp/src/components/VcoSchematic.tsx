import { useEffect, useRef } from 'react'
import type { Device, VcoDeviceKey } from '../types'

// Current-starved ring VCO schematic in the Virtuoso Composer idiom: one detailed
// delay cell (Mbp/Mp/Mn/Mbn stack, annotated with live W×M) beside the N-stage
// ring loop. Built imperatively into an <svg> so the geometry stays exact.
const C = { wire: '#39d7d7', sym: '#63d68a', pin: '#ff5a52', prop: '#e6c84f', net: '#57e0e0', global: '#ff8a3d', dim: '#7aa6a3', bg: '#040a0a', grid: '#0d2422' }

export default function VcoSchematic({ devices, nStages }: { devices: Record<VcoDeviceKey, Device>; nStages: number }) {
  const ref = useRef<SVGSVGElement>(null)
  useEffect(() => {
    const svg = ref.current
    if (!svg) return
    const NS = 'http://www.w3.org/2000/svg'
    while (svg.firstChild) svg.removeChild(svg.firstChild)
    const el = (t: string, a: Record<string, string | number>) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, String(a[k])); return e }
    const add = (t: string, a: Record<string, string | number>) => { const e = el(t, a); svg.appendChild(e); return e }
    const wire = (pts: number[][]) => add('polyline', { points: pts.map((p) => p.join(',')).join(' '), fill: 'none', stroke: C.wire, 'stroke-width': 1.3, 'stroke-linejoin': 'round' })
    const dot = (x: number, y: number) => add('circle', { cx: x, cy: y, r: 2.6, fill: C.wire })
    const pin = (x: number, y: number) => add('rect', { x: x - 1.9, y: y - 1.9, width: 3.8, height: 3.8, fill: C.pin })
    const txt = (x: number, y: number, s: string, col: string, size = 9.5, anchor = 'start') => { const e = add('text', { x, y, fill: col, 'font-size': size, 'font-family': 'ui-monospace,monospace', 'text-anchor': anchor }); e.textContent = s; return e }
    const sz = (k: VcoDeviceKey) => `${devices[k].w_um}u×${devices[k].m}`
    // MOSFET (gate left), drain=top, source=bottom
    const mos = (cx: number, cy: number, p: boolean, label: string, size: string) => {
      const h = 30, col = C.sym, g = add('g', { stroke: col, 'stroke-width': 1.3, fill: 'none' }) as SVGGElement
      const L = (x1: number, y1: number, x2: number, y2: number, w?: number) => g.appendChild(el('line', { x1, y1, x2, y2, ...(w ? { 'stroke-width': w } : {}) }))
      L(cx, cy - h / 2, cx, cy + h / 2, 2); L(cx - 10, cy - 9, cx - 10, cy + 9, 1.7); L(cx - 20, cy, cx - (p ? 14 : 10), cy)
      if (p) g.appendChild(el('circle', { cx: cx - 12, cy, r: 2.3 }))
      L(cx, cy - h / 2, cx + 7, cy - h / 2); L(cx, cy + h / 2, cx + 7, cy + h / 2)
        ;[[cx + 7, cy - h / 2], [cx + 7, cy + h / 2], [cx - 20, cy]].forEach(([px, py]) => pin(px, py))
      txt(cx + 11, cy - 1, label, C.sym, 8, 'start'); if (size) txt(cx + 11, cy + 7.5, size, C.prop, 8, 'start')
      return { g: [cx - 20, cy], d: [cx + 7, cy - h / 2], s: [cx + 7, cy + h / 2] }
    }
    // grid
    const grid = add('pattern', { id: 'vcg', width: 12, height: 12, patternUnits: 'userSpaceOnUse' }); grid.appendChild(el('circle', { cx: 0.6, cy: 0.6, r: 0.6, fill: C.grid })); (svg.querySelector('defs') || svg.insertBefore(el('defs', {}), svg.firstChild)).appendChild(grid)
    add('rect', { x: 0, y: 0, width: 460, height: 300, fill: 'url(#vcg)' })
    const VDD = 30, GND = 276, cxc = 120
    wire([[24, VDD], [436, VDD]]); wire([[24, GND], [436, GND]])
    txt(24, VDD - 6, 'vdd!', C.global, 10); txt(24, GND + 14, 'gnd!', C.global, 10)
    txt(120, 22, 'current-starved delay cell', C.dim, 9, 'middle')
    const mbp = mos(cxc, 70, true, 'Mbp', sz('starvep'))
    const mp = mos(cxc, 122, true, 'Mp', sz('invp'))
    const mn = mos(cxc, 190, false, 'Mn', sz('invn'))
    const mbn = mos(cxc, 242, false, 'Mbn', sz('starven'))
    const X = cxc + 7
    wire([[X, mbp.d[1]], [X, VDD]]); wire([[X, mbp.s[1]], [X, mp.d[1]]]); wire([[X, mp.s[1]], [X, mn.d[1]]]); wire([[X, mn.s[1]], [X, mbn.d[1]]]); wire([[X, mbn.s[1]], [X, GND]])
    const outY = 156; dot(X, outY); txt(X + 30, outY + 3, 'out', C.net, 9.5); wire([[X, outY], [X + 26, outY]])
    wire([[mp.g[0], mp.g[1]], [cxc - 36, 122], [cxc - 36, 190], [mn.g[0], mn.g[1]]])
    wire([[cxc - 36, 156], [cxc - 52, 156]]); dot(cxc - 36, 156); txt(cxc - 56, 159, 'in', C.net, 9.5, 'end')
    wire([[mbp.g[0], mbp.g[1]], [cxc - 40, 70]]); txt(cxc - 44, 73, 'vbp', C.net, 8.5, 'end')
    wire([[mbn.g[0], mbn.g[1]], [cxc - 40, 242]]); txt(cxc - 44, 245, 'V_ctrl', C.prop, 8.5, 'end')
    // ring loop of N inverters
    const N = Math.max(3, Math.min(nStages, 7))
    const bx = 320, top = 78, gap = Math.min(34, (GND - top - 20) / N)
    txt(bx + 14, top - 14, `ring · N=${nStages}`, C.dim, 9, 'middle')
    const inv = (x: number, y: number) => { add('polygon', { points: `${x},${y - 9} ${x},${y + 9} ${x + 17},${y}`, fill: 'none', stroke: C.sym, 'stroke-width': 1.3 }); add('circle', { cx: x + 20, cy: y, r: 2.6, fill: 'none', stroke: C.sym, 'stroke-width': 1.3 }); return { in: [x, y], out: [x + 23, y] } }
    const cells = Array.from({ length: N }, (_, i) => inv(bx, top + i * gap))
    for (let i = 0; i < N - 1; i++) wire([[...cells[i].out], [bx + 36, top + i * gap], [bx + 36, top + (i + 1) * gap], [...cells[i + 1].in]])
    wire([[...cells[N - 1].out], [bx + 58, top + (N - 1) * gap], [bx + 58, top - 20], [bx - 20, top - 20], [bx - 20, top], [...cells[0].in]])
    dot(bx - 20, top); txt(bx + 62, top + (N - 1) * gap + 3, 'f_out', C.net, 9)
  }, [devices, nStages])
  return <svg ref={ref} viewBox="0 0 460 300" width="100%" style={{ display: 'block', maxHeight: 340, background: C.bg, borderRadius: 8 }} role="img" aria-label="Current-starved ring VCO schematic" />
}

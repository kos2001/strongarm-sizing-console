import { useEffect, useRef } from 'react'
import type { Device, VcoDeviceKey, VcoTopology } from '../types'

// Ring VCO schematic in the Virtuoso Composer idiom: one detailed delay cell
// beside the N-stage ring loop. Two topologies:
//   starved — Mbp/Mp/Mn/Mbn stack (current-starved inverter)
//   xcpl    — pseudo-differential: two starved inverter rails tied by a
//             cross-coupled PMOS pair (Mx/Mxb, gates crossed) + reset PMOS
//             (Mrst) clamping o1 while rstb is low
// Built imperatively into an <svg> so the geometry stays exact.
const C = { wire: '#39d7d7', sym: '#63d68a', pin: '#ff5a52', prop: '#e6c84f', net: '#57e0e0', global: '#ff8a3d', dim: '#7aa6a3', bg: '#040a0a', grid: '#0d2422' }

export default function VcoSchematic({ devices, nStages, topology = 'starved' }: { devices: Record<VcoDeviceKey, Device>; nStages: number; topology?: VcoTopology }) {
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
    const sz = (k: VcoDeviceKey) => (devices[k] ? `${devices[k].w_um}u×${devices[k].m}` : '')
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
    const W = topology === 'xcpl' ? 760 : 460
    svg.setAttribute('viewBox', `0 0 ${W} 300`)
    // grid
    const grid = add('pattern', { id: 'vcg', width: 12, height: 12, patternUnits: 'userSpaceOnUse' }); grid.appendChild(el('circle', { cx: 0.6, cy: 0.6, r: 0.6, fill: C.grid })); (svg.querySelector('defs') || svg.insertBefore(el('defs', {}), svg.firstChild)).appendChild(grid)
    add('rect', { x: 0, y: 0, width: W, height: 300, fill: 'url(#vcg)' })
    const VDD = 30, GND = 276
    wire([[24, VDD], [W - 24, VDD]]); wire([[24, GND], [W - 24, GND]])
    txt(24, VDD - 6, 'vdd!', C.global, 10); txt(24, GND + 14, 'gnd!', C.global, 10)

    // one starved inverter stack (Mbp/Mp/Mn/Mbn) -> output-node x position.
    // Input tap: y=156 stub (starved) or top of the gate bus (xcpl, keeps the
    // channel between the rails free for the cross-coupled pair).
    const stack = (cxc: number, suffix: string, tapTop: boolean, inLabel: string) => {
      const mbp = mos(cxc, 70, true, `Mbp${suffix}`, sz('starvep'))
      const mp = mos(cxc, 122, true, `Mp${suffix}`, sz('invp'))
      const mn = mos(cxc, 190, false, `Mn${suffix}`, sz('invn'))
      const mbn = mos(cxc, 242, false, `Mbn${suffix}`, sz('starven'))
      const X = cxc + 7, bus = cxc - 36
      wire([[X, mbp.d[1]], [X, VDD]]); wire([[X, mbp.s[1]], [X, mp.d[1]]]); wire([[X, mp.s[1]], [X, mn.d[1]]]); wire([[X, mn.s[1]], [X, mbn.d[1]]]); wire([[X, mbn.s[1]], [X, GND]])
      wire([[mp.g[0], mp.g[1]], [bus, 122], [bus, 190], [mn.g[0], mn.g[1]]])
      if (tapTop) { wire([[bus, 122], [bus - 18, 122]]); dot(bus, 122); txt(bus - 21, 125, inLabel, C.net, 8.5, 'end') }
      else { wire([[bus, 156], [bus - 16, 156]]); dot(bus, 156); txt(bus - 20, 159, inLabel, C.net, 9.5, 'end') }
      wire([[mbp.g[0], mbp.g[1]], [cxc - 40, 70]]); txt(cxc - 44, 73, 'vbp', C.net, 8.5, 'end')
      wire([[mbn.g[0], mbn.g[1]], [cxc - 40, 242]]); txt(cxc - 44, 245, 'V_ctrl', C.prop, 8.5, 'end')
      return X
    }
    // ring loop of N inverters at bx (annotation), twin = xcpl double rail
    const ring = (bx: number, title: string, twin: boolean) => {
      const N = Math.max(3, Math.min(nStages, 7))
      const top = 78, gap = Math.min(34, (GND - top - 20) / N)
      txt(bx + 14, top - 26, title, C.dim, 9, 'middle')
      const inv = (x: number, y: number) => { add('polygon', { points: `${x},${y - 9} ${x},${y + 9} ${x + 17},${y}`, fill: 'none', stroke: C.sym, 'stroke-width': 1.3 }); add('circle', { cx: x + 20, cy: y, r: 2.6, fill: 'none', stroke: C.sym, 'stroke-width': 1.3 }); return { in: [x, y], out: [x + 23, y] } }
      const cells = Array.from({ length: N }, (_, i) => inv(bx, top + i * gap))
      for (let i = 0; i < N - 1; i++) wire([[...cells[i].out], [bx + 36, top + i * gap], [bx + 36, top + (i + 1) * gap], [...cells[i + 1].in]])
      wire([[...cells[N - 1].out], [bx + 58, top + (N - 1) * gap], [bx + 58, top - 20], [bx - 20, top - 20], [bx - 20, top], [...cells[0].in]])
      dot(bx - 20, top); txt(bx + 62, top + (N - 1) * gap + 3, 'f_out', C.net, 9)
      if (twin) {
        // per-stage cross-coupling to the anti-phase twin rail (drawn as ×)
        for (let i = 0; i < N; i++) {
          const y = top + i * gap
          add('line', { x1: bx - 40, y1: y - 5, x2: bx - 26, y2: y + 5, stroke: C.prop, 'stroke-width': 1.1 })
          add('line', { x1: bx - 40, y1: y + 5, x2: bx - 26, y2: y - 5, stroke: C.prop, 'stroke-width': 1.1 })
        }
        txt(bx - 33, top + (N - 1) * gap + 20, '× = Mx/Mxb → ob rail', C.prop, 8, 'middle')
      }
    }

    if (topology === 'xcpl') {
      txt(300, 22, 'cross-coupled pseudo-differential delay cell', C.dim, 9, 'middle')
      const XA = stack(100, '', true, 'o[i-1]')     // rail A -> node o
      const XB = stack(490, 'b', true, 'ob[i-1]')   // rail B -> node ob
      const outY = 156
      // node stubs: o runs right into the middle channel (Mrst/Mx land on it),
      // ob runs left from rail B (Mxb lands on it; crosses rail-B gate bus, no dot)
      const mr = mos(190, 76, true, 'Mrst', sz('rstp'))
      const mx = mos(270, 76, true, 'Mx', sz('xcplp'))
      const mxb = mos(350, 76, true, 'Mxb', sz('xcplp'))
      dot(XA, outY); wire([[XA, outY], [mx.s[0] + 10, outY]]); txt(mx.s[0] + 16, outY + 3, 'o', C.net, 9.5)
      dot(XB, outY); wire([[XB, outY], [mxb.s[0], outY]]); txt(XB + 6, outY - 6, 'ob', C.net, 9.5)
      // sources at vdd
      wire([[mr.d[0], mr.d[1]], [mr.d[0], VDD]]); wire([[mx.d[0], mx.d[1]], [mx.d[0], VDD]]); wire([[mxb.d[0], mxb.d[1]], [mxb.d[0], VDD]])
      // reset PMOS: clamps o (stage 1) to vdd while rstb is low
      wire([[mr.s[0], mr.s[1]], [mr.s[0], outY]]); dot(mr.s[0], outY)
      wire([[mr.g[0], mr.g[1]], [mr.g[0] - 8, mr.g[1]]]); txt(mr.g[0] - 11, 79, 'rstb', C.prop, 8, 'end')
      // cross-coupled PMOS pair (P1): drains on o/ob, gates crossed (X)
      wire([[mx.s[0], mx.s[1]], [mx.s[0], outY]]); dot(mx.s[0], outY)                     // Mx -> o
      wire([[mxb.s[0], mxb.s[1]], [mxb.s[0], outY]]); dot(mxb.s[0], outY)                 // Mxb -> ob
      wire([[mx.g[0], mx.g[1]], [mx.g[0], 100], [mxb.s[0], 120]]); dot(mxb.s[0], 120)     // Mx gate = ob
      wire([[mxb.g[0], mxb.g[1]], [mxb.g[0], 96], [mx.s[0], 116]]); dot(mx.s[0], 116)     // Mxb gate = o
      ring(620, `ring ×2 rails · N=${nStages} (odd)`, true)
    } else {
      txt(120, 22, 'current-starved delay cell', C.dim, 9, 'middle')
      const XA = stack(120, '', false, 'in')
      const outY = 156
      dot(XA, outY); txt(XA + 30, outY + 3, 'out', C.net, 9.5); wire([[XA, outY], [XA + 26, outY]])
      ring(320, `ring · N=${nStages}`, false)
    }
  }, [devices, nStages, topology])
  return <svg ref={ref} viewBox="0 0 460 300" width="100%" style={{ display: 'block', maxHeight: 340, background: C.bg, borderRadius: 8 }} role="img"
    aria-label={topology === 'xcpl' ? 'Cross-coupled pseudo-differential ring VCO schematic' : 'Current-starved ring VCO schematic'} />
}

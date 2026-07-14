import { useEffect, useRef } from 'react'
import type { Device, VcoDeviceKey } from '../types'

// Ring VCO schematic in the Virtuoso Composer idiom — 교차결합+리셋(xcpl) 단일:
// pseudo-differential 딜레이 셀(두 starved 인버터 레일 + cross-coupled PMOS
// 쌍 Mx/Mxb(X 결선) + 리셋 PMOS Mrst) 옆에 수평 2-레일 링(매 단 back-to-back
// 래치 커플러, 참고 그림 Fig.1 형태)을 그린다. 전류제한(starved) 단일 토폴로지는 제거됨.
// Built imperatively into an <svg> so the geometry stays exact.
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
    const sz = (k: VcoDeviceKey) => (devices[k] ? `${devices[k].w_um}u×${devices[k].m}` : '')
    // MOSFET (gate left; flip=true 면 좌우반전 — 게이트 오른쪽), drain=top, source=bottom
    const mos = (cx: number, cy: number, p: boolean, label: string, size: string, flip = false) => {
      const h = 30, col = C.sym
      const g = add('g', { stroke: col, 'stroke-width': 1.3, fill: 'none', ...(flip ? { transform: `translate(${2 * cx},0) scale(-1,1)` } : {}) }) as SVGGElement
      const L = (x1: number, y1: number, x2: number, y2: number, w?: number) => g.appendChild(el('line', { x1, y1, x2, y2, ...(w ? { 'stroke-width': w } : {}) }))
      L(cx, cy - h / 2, cx, cy + h / 2, 2); L(cx - 10, cy - 9, cx - 10, cy + 9, 1.7); L(cx - 20, cy, cx - (p ? 14 : 10), cy)
      if (p) g.appendChild(el('circle', { cx: cx - 12, cy, r: 2.3 }))
      L(cx, cy - h / 2, cx + 7, cy - h / 2); L(cx, cy + h / 2, cx + 7, cy + h / 2)
      const gx = flip ? cx + 20 : cx - 20, dx = flip ? cx - 7 : cx + 7
        ;[[dx, cy - h / 2], [dx, cy + h / 2], [gx, cy]].forEach(([px, py]) => pin(px, py))
      txt(flip ? cx - 11 : cx + 11, cy - 1, label, C.sym, 8, flip ? 'end' : 'start'); if (size) txt(flip ? cx - 11 : cx + 11, cy + 7.5, size, C.prop, 8, flip ? 'end' : 'start')
      return { g: [gx, cy], d: [dx, cy - h / 2], s: [dx, cy + h / 2] }
    }
    // 링 단수 N: 홀수만(발진 조건), 3~9. 짝수가 들어오면 아래로 내림.
    const N = (() => { let n = Math.max(3, Math.min(nStages, 9)); if (n % 2 === 0) n -= 1; return n })()
    const RING_P = 52 // 수평 링 stage pitch
    const W = 640 + N * RING_P + 70
    svg.setAttribute('viewBox', `0 0 ${W} 300`)
    // 원본 크기 유지 — 좁은 패널에서는 부모(overflow-x-auto)가 가로 스크롤 제공
    svg.style.minWidth = `${W}px`
    // grid
    const grid = add('pattern', { id: 'vcg', width: 12, height: 12, patternUnits: 'userSpaceOnUse' }); grid.appendChild(el('circle', { cx: 0.6, cy: 0.6, r: 0.6, fill: C.grid })); (svg.querySelector('defs') || svg.insertBefore(el('defs', {}), svg.firstChild)).appendChild(grid)
    add('rect', { x: 0, y: 0, width: W, height: 300, fill: 'url(#vcg)' })
    const VDD = 30, GND = 276
    wire([[24, VDD], [W - 24, VDD]]); wire([[24, GND], [W - 24, GND]])
    txt(24, VDD - 6, 'vdd!', C.global, 10); txt(24, GND + 14, 'gnd!', C.global, 10)

    // 유닛 인버터(Mp/Mn — 레일 직결, 스타빙 없음) -> output-node x position.
    // 유닛 셀 = NMOS 2 + PMOS 4 (인버터 2쌍 + 래치 PMOS 2) — 전류원 없음.
    const stack = (cxc: number, suffix: string, inLabel: string) => {
      const mp = mos(cxc, 122, true, `Mp${suffix}`, sz('invp'))
      const mn = mos(cxc, 190, false, `Mn${suffix}`, sz('invn'))
      const X = cxc + 7, bus = cxc - 36
      wire([[X, mp.d[1]], [X, VDD]]); wire([[X, mp.s[1]], [X, mn.d[1]]]); wire([[X, mn.s[1]], [X, GND]])
      wire([[mp.g[0], mp.g[1]], [bus, 122], [bus, 190], [mn.g[0], mn.g[1]]])
      wire([[bus, 122], [bus - 18, 122]]); dot(bus, 122); txt(bus - 21, 125, inLabel, C.net, 8.5, 'end')
      return X
    }
    // 레일 인버터 심볼 — 참조 그림(vco_cap.png)대로 반전 bubble 포함(▷○).
    // '반전 신호가 없다'는 것은 커플러(래치) 쪽 — 커플러만 bubble 없이 그린다.
    const inv = (x: number, y: number) => { add('polygon', { points: `${x},${y - 9} ${x},${y + 9} ${x + 17},${y}`, fill: 'none', stroke: C.sym, 'stroke-width': 1.3 }); add('circle', { cx: x + 20, cy: y, r: 2.6, fill: 'none', stroke: C.sym, 'stroke-width': 1.3 }); return { in: [x, y], out: [x + 23, y] } }
    // pseudo-differential 수평 2-레일 링(참고 그림 Fig.1 형태).
    // 위/아래 레일에 각각 N개 인버터, 매 단 출력 사이를 등을 맞댄 인버터 쌍
    // (back-to-back latch)으로 결합, 레일별 피드백은 상/하로 랩어라운드.
    const ringTwin = (bx: number, title: string) => {
      const T = 108, B = 208, mid = (T + B) / 2
      txt(bx + (N * RING_P) / 2, T - 40, title, C.dim, 9, 'middle')
      const topCells = Array.from({ length: N }, (_, i) => inv(bx + i * RING_P, T))
      const botCells = Array.from({ length: N }, (_, i) => inv(bx + i * RING_P, B))
      // 체인 배선(수평)
      for (let i = 0; i < N - 1; i++) {
        wire([[...topCells[i].out], [...topCells[i + 1].in]])
        wire([[...botCells[i].out], [...botCells[i + 1].in]])
      }
      // 매 단 출력의 레일 간 래치 커플러: ▽△ (anti-parallel inverter pair)
      const coupler = (x: number) => {
        const h = 11, w = 7, g2 = 9 // 삼각형 높이/반폭, 좌우 오프셋
        wire([[x, T], [x, mid - h - 4]]); wire([[x, mid + h + 4], [x, B]])
        dot(x, T); dot(x, B)
        // 상하 연결 바(커플러 입출력 공유 노드)
        wire([[x - g2 - w, mid - h - 4], [x + g2 + w, mid - h - 4]])
        wire([[x - g2 - w, mid + h + 4], [x + g2 + w, mid + h + 4]])
        // 반전 신호 없음 — 커플러는 PMOS 래치(비반전 결합): bubble 없는
        // 맞물린 삼각형 쌍으로 표기
        add('polygon', { points: `${x - g2 - w},${mid - h} ${x - g2 + w},${mid - h} ${x - g2},${mid + h + 2}`, fill: 'none', stroke: C.sym, 'stroke-width': 1.2 })
        wire([[x - g2, mid - h - 4], [x - g2, mid - h]])
        add('polygon', { points: `${x + g2 - w},${mid + h} ${x + g2 + w},${mid + h} ${x + g2},${mid - h - 2}`, fill: 'none', stroke: C.sym, 'stroke-width': 1.2 })
        wire([[x + g2, mid + h + 4], [x + g2, mid + h]])
      }
      for (let i = 0; i < N; i++) coupler(bx + i * RING_P + 23)
      // 피드백 랩어라운드: 위 레일은 위로, 아래 레일은 아래로
      const xo = bx + (N - 1) * RING_P + 23
      wire([[xo, T], [xo + 18, T], [xo + 18, T - 26], [bx - 16, T - 26], [bx - 16, T], [...topCells[0].in]])
      wire([[xo, B], [xo + 18, B], [xo + 18, B + 26], [bx - 16, B + 26], [bx - 16, B], [...botCells[0].in]])
      txt(xo + 22, T - 6, 'f_out', C.net, 9)
      txt(xo + 22, B + 14, 'f_outb', C.net, 9)
    }

    {
      txt(300, 22, 'unit cell: 2 NMOS + 4 PMOS (2 latched) — no current starving', C.dim, 9, 'middle')
      const XA = stack(100, '', 'o[i-1]')     // rail A -> node o
      const XB = stack(490, 'b', 'ob[i-1]')   // rail B -> node ob
      const outY = 156
      // node stubs: o runs right into the middle channel (Mrst/Mx land on it),
      // ob runs left from rail B (Mxb lands on it; crosses rail-B gate bus, no dot)
      const mr = mos(190, 76, true, 'Mrst', sz('rstp'))
      const mx = mos(270, 76, true, 'Mx', sz('xcplp'))
      const mxb = mos(350, 76, true, 'Mxb', sz('xcplp'), true) // flip — 게이트가 안쪽(X 결선)
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
      // 게이트를 반대편 출력 레일에 대각선으로 연결 — 두 줄이 중앙에서 X 로 교차(래치 표기)
      wire([[mx.g[0], mx.g[1]], [mx.g[0], 96], [mxb.s[0], 128]]); dot(mxb.s[0], 128)      // Mx gate = ob
      wire([[mxb.g[0], mxb.g[1]], [mxb.g[0], 96], [mx.s[0], 128]]); dot(mx.s[0], 128)     // Mxb gate = o
      ringTwin(640, `pseudo-diff ring · N=${N} (odd)`)
    }
  }, [devices, nStages])
  return <svg ref={ref} viewBox="0 0 866 300" width="100%" style={{ display: 'block', maxHeight: 340, background: C.bg, borderRadius: 8 }} role="img"
    aria-label="Cross-coupled pseudo-differential ring VCO schematic" />
}

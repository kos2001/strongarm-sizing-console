import type { Device, DeviceKey } from '../types'
import { V } from '../virtuoso'

// Transistor-level StrongARM schematic drawn in the Cadence Virtuoso "Composer"
// idiom: pure-black canvas with a dim snap-grid, thin cyan interconnect, green
// analogLib-style MOSFET symbols with source arrows + red pin squares, yellow
// instance-property labels, and orange global-net names (vdd!/gnd!). `changed`
// flashes the device the optimizer just adjusted (amber, glowing).
export default function Schematic({ devices, changed }: { devices: Record<DeviceKey, Device>; changed?: DeviceKey | null }) {
  const d = devices
  const sz = (k: DeviceKey) => `${d[k].w_um}u×${d[k].m}`
  const REF: Record<DeviceKey, string> = { pre: 'MP1', pcc: 'MP3', ncc: 'MN3', input: 'MN1', tail: 'MT' }

  // one analogLib-style MOSFET symbol. anchors: drain=top, source=bottom, gate=left.
  const Mos = ({ cx, cy, p, hot, flash }: { cx: number; cy: number; p?: boolean; hot?: boolean; flash?: boolean }) => {
    const h = 26
    const col = flash ? V.changed : hot ? V.symHot : V.sym
    const sy = cy + h / 2 // source y (bottom)
    return (
      <g stroke={col} strokeWidth={flash ? 2 : 1.3} fill="none" style={flash ? { filter: `drop-shadow(0 0 4px ${V.changed})` } : undefined}>
        {/* channel bar */}
        <line x1={cx} y1={cy - h / 2} x2={cx} y2={cy + h / 2} strokeWidth={flash ? 2.4 : 1.8} />
        {/* gate electrode + lead */}
        <line x1={cx - 9} y1={cy - 9} x2={cx - 9} y2={cy + 9} strokeWidth={flash ? 2.2 : 1.6} />
        <line x1={cx - 18} y1={cy} x2={cx - (p ? 13 : 9)} y2={cy} />
        {p && <circle cx={cx - 11} cy={cy} r={2.3} />}
        {/* drain / source connector stubs */}
        <line x1={cx} y1={cy - h / 2} x2={cx + 7} y2={cy - h / 2} />
        <line x1={cx} y1={sy} x2={cx + 7} y2={sy} />
        {/* source-direction arrow (analogLib): nmos points in, pmos points out */}
        {p
          ? <polygon points={`${cx + 7},${sy} ${cx + 3},${sy - 2.6} ${cx + 3},${sy + 2.6}`} fill={col} stroke="none" />
          : <polygon points={`${cx},${sy} ${cx + 4},${sy - 2.6} ${cx + 4},${sy + 2.6}`} fill={col} stroke="none" />}
        {/* pin squares at the three external terminals */}
        {[[cx + 7, cy - h / 2], [cx + 7, sy], [cx - 18, cy]].map(([px, py], i) => (
          <rect key={i} x={px - 1.6} y={py - 1.6} width={3.2} height={3.2} fill={V.pin} stroke="none" />
        ))}
      </g>
    )
  }
  const cl = (k: DeviceKey) => (changed === k ? V.changed : V.prop)
  const Wire = ({ d: pts }: { d: string }) => <polyline points={pts} fill="none" stroke={V.wire} strokeWidth={1.1} />
  const Dot = ({ x, y }: { x: number; y: number }) => <circle cx={x} cy={y} r={2.2} fill={V.wire} stroke="none" />
  const T = ({ x, y, children, anchor = 'start', c = V.faint, sz: fs = 8 }: { x: number; y: number; children: string; anchor?: 'start' | 'middle' | 'end'; c?: string; sz?: number }) => (
    <text x={x} y={y} fontSize={fs} fontFamily="ui-monospace, monospace" fill={c} textAnchor={anchor}>{children}</text>
  )
  // property label = instance ref (green) + W×M (yellow), Virtuoso instance-label style
  const Prop = ({ x, y, k }: { x: number; y: number; k: DeviceKey }) => (
    <g>
      <T x={x} y={y - 8} c={changed === k ? V.changed : V.sym} sz={7.5}>{REF[k]}</T>
      <T x={x} y={y} c={cl(k)} sz={7.5}>{sz(k)}</T>
    </g>
  )

  const V0 = 24, GND = 300, LX = 128, RX = 232, CX = 180
  const yPre = 52, yLatP = 96, yOut = 150, yLatN = 196, yIn = 244, yTail = 282

  return (
    <svg viewBox="0 0 360 320" width="100%" style={{ display: 'block', maxHeight: 460, background: V.bg, borderRadius: 8 }} role="img" aria-label="StrongARM latch transistor schematic (Virtuoso style)">
      <defs>
        <pattern id="vgrid" width={12} height={12} patternUnits="userSpaceOnUse">
          <circle cx={0.6} cy={0.6} r={0.6} fill={V.grid} />
        </pattern>
      </defs>
      {/* snap grid */}
      <rect x={0} y={0} width={360} height={320} fill="url(#vgrid)" />

      {/* power rails + global nets */}
      <line x1={20} y1={V0} x2={340} y2={V0} stroke={V.wire} strokeWidth={1.5} />
      <line x1={20} y1={GND} x2={340} y2={GND} stroke={V.wire} strokeWidth={1.5} />
      <T x={20} y={V0 - 5} c={V.netGlobal} sz={9}>vdd!</T>
      <T x={20} y={GND + 12} c={V.netGlobal} sz={9}>gnd!</T>

      {/* CLK bus (left) */}
      <line x1={30} y1={V0 + 8} x2={30} y2={yTail} stroke={V.wire} strokeWidth={1} strokeDasharray="3 3" opacity={0.8} />
      <T x={32} y={yTail + 2} c={V.net} sz={8.5}>clk</T>

      {/* precharge PMOS (gate clk): vdd! -> Out */}
      <Mos cx={LX} cy={yPre} p flash={changed === 'pre'} />
      <Mos cx={RX} cy={yPre} p flash={changed === 'pre'} />
      <Wire d={`${LX},${V0} ${LX},${yPre - 13}`} />
      <Wire d={`${RX},${V0} ${RX},${yPre - 13}`} />
      <Wire d={`30,${yPre} ${LX - 18},${yPre}`} />
      <Wire d={`30,${yPre} ${RX - 18},${yPre}`} />
      <Prop x={LX + 12} y={yPre} k="pre" />

      {/* latch PMOS (cross-coupled): vdd! -> Out */}
      <Mos cx={LX} cy={yLatP} p hot flash={changed === 'pcc'} />
      <Mos cx={RX} cy={yLatP} p hot flash={changed === 'pcc'} />
      <Wire d={`${LX},${yPre + 13} ${LX},${yLatP - 13}`} />
      <Wire d={`${RX},${yPre + 13} ${RX},${yLatP - 13}`} />
      <Prop x={LX + 12} y={yLatP} k="pcc" />

      {/* Out nodes */}
      <Wire d={`${LX},${yLatP + 13} ${LX},${yLatN - 13}`} />
      <Wire d={`${RX},${yLatP + 13} ${RX},${yLatN - 13}`} />
      <Dot x={LX} y={yOut} /><Dot x={RX} y={yOut} />
      <T x={LX - 6} y={yOut - 4} anchor="end" c={V.net} sz={8.5}>outp</T>
      <T x={RX + 6} y={yOut - 4} c={V.net} sz={8.5}>outn</T>

      {/* latch NMOS (cross-coupled): Out -> X/Y */}
      <Mos cx={LX} cy={yLatN} hot flash={changed === 'ncc'} />
      <Mos cx={RX} cy={yLatN} hot flash={changed === 'ncc'} />
      <Prop x={LX + 12} y={yLatN + 11} k="ncc" />

      {/* cross-couple wiring */}
      <Wire d={`${LX - 18},${yLatP} 70,${yLatP} 70,${yOut - 22} ${RX},${yOut - 22} ${RX},${yOut}`} />
      <Wire d={`${LX - 18},${yLatN} 70,${yLatN} 70,${yOut + 22} ${RX},${yOut + 22} ${RX},${yOut}`} />
      <Wire d={`${RX - 18},${yLatP} 290,${yLatP} 290,${yOut - 30} ${LX},${yOut - 30} ${LX},${yOut}`} />
      <Wire d={`${RX - 18},${yLatN} 290,${yLatN} 290,${yOut + 30} ${LX},${yOut + 30} ${LX},${yOut}`} />

      {/* input pair: X/Y -> tail */}
      <Wire d={`${LX},${yLatN + 13} ${LX},${yIn - 13}`} />
      <Wire d={`${RX},${yLatN + 13} ${RX},${yIn - 13}`} />
      <Mos cx={LX} cy={yIn} flash={changed === 'input'} />
      <Mos cx={RX} cy={yIn} flash={changed === 'input'} />
      <Wire d={`${LX - 18},${yIn} 96,${yIn}`} />
      <Wire d={`${RX - 18},${yIn} 264,${yIn}`} />
      <T x={92} y={yIn - 4} anchor="end" c={V.net} sz={8.5}>vinp</T>
      <T x={268} y={yIn - 4} c={V.net} sz={8.5}>vinn</T>
      <Prop x={LX + 12} y={yIn + 11} k="input" />

      {/* tail switch: sources -> tail node -> gnd! */}
      <Wire d={`${LX},${yIn + 13} ${LX},${yTail - 18} ${CX},${yTail - 18} ${CX},${yTail - 13}`} />
      <Wire d={`${RX},${yIn + 13} ${RX},${yTail - 18} ${CX},${yTail - 18}`} />
      <Dot x={CX} y={yTail - 18} />
      <Mos cx={CX} cy={yTail} flash={changed === 'tail'} />
      <Wire d={`${CX},${yTail + 13} ${CX},${GND}`} />
      <Wire d={`30,${yTail} ${CX - 18},${yTail}`} />
      <Prop x={CX + 12} y={yTail + 11} k="tail" />
    </svg>
  )
}

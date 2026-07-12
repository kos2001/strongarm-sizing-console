import type { Device, DeviceKey } from '../types'
import { V } from '../virtuoso'

// Transistor-level StrongARM schematic drawn in the Cadence Virtuoso "Composer"
// idiom: pure-black canvas with a dim snap-grid, thin cyan interconnect, green
// analogLib-style MOSFET symbols with source arrows + red pin squares, yellow
// instance-property labels, and orange global-net names (vdd!/gnd!). `changed`
// flashes the device the optimizer just adjusted (amber, glowing).
export default function Schematic({ devices, changed, topology = 'strongarm' }: { devices: Record<DeviceKey, Device>; changed?: DeviceKey | null; topology?: 'strongarm' | 'doubletail' }) {
  const d = devices
  const sz = (k: DeviceKey) => `${d[k].w_um}u×${d[k].m}`
  const REF: Record<DeviceKey, string> = topology === 'doubletail'
    ? { pre: 'M3/4', pcc: 'M5/6', ncc: 'M7~10', input: 'M1/2', tail: 'Mt1·2' }
    : { pre: 'MP1', pcc: 'MP3', ncc: 'MN3', input: 'MN1', tail: 'MT' }

  // one analogLib-style MOSFET symbol. anchors: drain=top, source=bottom,
  // gate=left (flip=true 면 좌우반전 — 게이트가 오른쪽을 향한다).
  const Mos = ({ cx, cy, p, hot, flash, flip }: { cx: number; cy: number; p?: boolean; hot?: boolean; flash?: boolean; flip?: boolean }) => {
    const h = 26
    const col = flash ? V.changed : hot ? V.symHot : V.sym
    const sy = cy + h / 2 // source y (bottom)
    return (
      <g stroke={col} strokeWidth={flash ? 2 : 1.3} fill="none" transform={flip ? `translate(${2 * cx},0) scale(-1,1)` : undefined} style={flash ? { filter: `drop-shadow(0 0 4px ${V.changed})` } : undefined}>
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

  // ── double-tail (Schinkel) — 2단: 입력단(tail1) + 래치단(tail2, clkb) ──
  if (topology === 'doubletail') {
    const V0 = 24, GND = 300
    return (
      <svg viewBox="0 0 520 320" width="100%" style={{ display: 'block', maxHeight: 460, background: V.bg, borderRadius: 8 }} role="img" aria-label="Double-tail latch comparator schematic (Virtuoso style)">
        <defs><pattern id="vgrid2" width={12} height={12} patternUnits="userSpaceOnUse"><circle cx={0.6} cy={0.6} r={0.6} fill={V.grid} /></pattern></defs>
        <rect x={0} y={0} width={520} height={320} fill="url(#vgrid2)" />
        <line x1={20} y1={V0} x2={500} y2={V0} stroke={V.wire} strokeWidth={1.5} />
        <line x1={20} y1={GND} x2={500} y2={GND} stroke={V.wire} strokeWidth={1.5} />
        <T x={20} y={V0 - 5} c={V.netGlobal} sz={9}>vdd!</T>
        <T x={20} y={GND + 12} c={V.netGlobal} sz={9}>gnd!</T>
        {/* clk 버스 */}
        <line x1={30} y1={V0 + 8} x2={30} y2={210} stroke={V.wire} strokeWidth={1} strokeDasharray="3 3" opacity={0.8} />
        <T x={32} y={222} c={V.net} sz={8.5}>clk</T>

        {/* ── stage 1 ── */}
        <T x={120} y={44} anchor="middle" c={V.faint} sz={8}>stage 1</T>
        <Mos cx={90} cy={64} p flash={changed === 'pre'} />
        <Mos cx={150} cy={64} p flash={changed === 'pre'} />
        <Wire d={`90,${V0} 90,51`} /><Wire d={`150,${V0} 150,51`} />
        <Wire d={`30,64 72,64`} /><Wire d={`30,64 132,64`} />
        <Prop x={162} y={60} k="pre" />
        <Wire d={`90,77 90,137`} /><Wire d={`150,77 150,137`} />
        <Dot x={90} y={110} /><Dot x={150} y={110} />
        <T x={82} y={106} anchor="end" c={V.net} sz={8.5}>fp</T>
        <T x={158} y={106} c={V.net} sz={8.5}>fn</T>
        <Mos cx={90} cy={150} flash={changed === 'input'} />
        <Mos cx={150} cy={150} flip flash={changed === 'input'} />
        <Wire d={`72,150 48,150`} /><Wire d={`168,150 192,150`} />
        <T x={44} y={146} anchor="end" c={V.net} sz={8.5}>vinp</T>
        <T x={196} y={146} c={V.net} sz={8.5}>vinn</T>
        <Prop x={96} y={196} k="input" />
        <Wire d={`90,163 90,180 120,180`} /><Wire d={`150,163 150,180 120,180`} /><Dot x={120} y={180} />
        <Mos cx={120} cy={210} flash={changed === 'tail'} />
        <Wire d={`120,180 120,197`} /><Wire d={`120,223 120,${GND}`} />
        <Wire d={`30,210 102,210`} />
        <Prop x={134} y={226} k="tail" />

        {/* ── stage 2 ── */}
        <T x={380} y={44} anchor="middle" c={V.faint} sz={8}>stage 2</T>
        <Mos cx={380} cy={56} p flash={changed === 'tail'} />
        <Wire d={`380,43 380,${V0}`} />
        <Wire d={`362,56 340,56`} /><T x={336} y={59} anchor="end" c={V.prop} sz={8.5}>clkb</T>
        <Wire d={`380,69 380,88`} /><Dot x={380} y={88} />
        <Mos cx={340} cy={118} p flip flash={changed === 'pcc'} />
        <Mos cx={420} cy={118} p flash={changed === 'pcc'} />
        <Wire d={`340,105 340,96 380,88`} /><Wire d={`420,105 420,96 380,88`} />
        <Prop x={432} y={108} k="pcc" />
        <Wire d={`340,131 340,177`} /><Wire d={`420,131 420,177`} />
        <Dot x={340} y={150} /><Dot x={420} y={150} />
        <T x={332} y={146} anchor="end" c={V.net} sz={8.5}>outp</T>
        <T x={428} y={146} c={V.net} sz={8.5}>outn</T>
        <Mos cx={340} cy={190} flip flash={changed === 'ncc'} />
        <Mos cx={420} cy={190} flash={changed === 'ncc'} />
        <Prop x={432} y={204} k="ncc" />
        <Wire d={`340,203 340,${GND}`} /><Wire d={`420,203 420,${GND}`} />
        {/* 래치 X 결선 */}
        <Wire d={`358,118 358,190`} /><Wire d={`402,118 402,190`} />
        <Wire d={`358,138 420,170`} /><Wire d={`402,138 340,170`} />
        <Dot x={358} y={138} /><Dot x={402} y={138} /><Dot x={340} y={170} /><Dot x={420} y={170} />
        {/* 결합/리셋 NMOS — 게이트 = fn/fp */}
        <Mos cx={280} cy={190} flash={changed === 'ncc'} />
        <Wire d={`280,177 280,150 340,150`} />
        <Wire d={`280,203 280,${GND}`} />
        <Wire d={`150,110 212,110 212,190 262,190`} />
        <Mos cx={480} cy={190} flash={changed === 'ncc'} />
        <Wire d={`480,177 480,150 420,150`} />
        <Wire d={`480,203 480,${GND}`} />
        <Wire d={`90,110 60,110 60,250 448,250 448,190 462,190`} />
      </svg>
    )
  }

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

      {/* latch PMOS (cross-coupled): vdd! -> Out. 왼쪽은 flip — 게이트가 중앙 채널을 향해 X 결선이 가능 */}
      <Mos cx={LX} cy={yLatP} p hot flip flash={changed === 'pcc'} />
      <Mos cx={RX} cy={yLatP} p hot flash={changed === 'pcc'} />
      <Wire d={`${LX},${yPre + 13} ${LX},${yLatP - 13}`} />
      <Wire d={`${RX},${yPre + 13} ${RX},${yLatP - 13}`} />
      <Prop x={RX + 12} y={yLatP} k="pcc" />

      {/* Out nodes */}
      <Wire d={`${LX},${yLatP + 13} ${LX},${yLatN - 13}`} />
      <Wire d={`${RX},${yLatP + 13} ${RX},${yLatN - 13}`} />
      <Dot x={LX} y={yOut} /><Dot x={RX} y={yOut} />
      <T x={LX - 6} y={yOut - 4} anchor="end" c={V.net} sz={8.5}>outp</T>
      <T x={RX + 6} y={yOut - 4} c={V.net} sz={8.5}>outn</T>

      {/* latch NMOS (cross-coupled): Out -> X/Y. 왼쪽은 flip(위와 동일) */}
      <Mos cx={LX} cy={yLatN} hot flip flash={changed === 'ncc'} />
      <Mos cx={RX} cy={yLatN} hot flash={changed === 'ncc'} />
      <Prop x={RX + 12} y={yLatN + 11} k="ncc" />

      {/* cross-couple wiring — 래치 표기: 좌우 게이트 버스를 반대편 출력 노드에
          대각선 두 줄로 연결해 중앙에서 X 로 교차시킨다(참고 자료의 latch 표기). */}
      <Wire d={`${LX + 18},${yLatP} ${LX + 18},${yLatN}`} />
      <Wire d={`${RX - 18},${yLatP} ${RX - 18},${yLatN}`} />
      <Wire d={`${LX + 18},125 ${RX},172`} />
      <Wire d={`${RX - 18},125 ${LX},172`} />
      <Dot x={LX + 18} y={125} /><Dot x={RX - 18} y={125} />
      <Dot x={LX} y={172} /><Dot x={RX} y={172} />

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

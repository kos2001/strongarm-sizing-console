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
    ? { pre: 'M3/4', prei: '—', pcc: 'M5/6', ncc: 'M7~10', input: 'M1/2', tail: 'Mt1·2' }
    : { pre: 'S3/4', prei: 'S1/2', pcc: 'M5/6', ncc: 'M3/4', input: 'M1/2', tail: 'M7' }

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
        {/* 래치 X 결선 — 쌍별 소형 X */}
        <Wire d={`358,118 420,140`} /><Wire d={`402,118 340,140`} />
        <Dot x={340} y={140} /><Dot x={420} y={140} />
        <Wire d={`358,190 420,168`} /><Wire d={`402,190 340,168`} />
        <Dot x={340} y={168} /><Dot x={420} y={168} />
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

  // ── StrongARM — new_cmp.png(Razavi 스타일 (b)) 배치 ─────────────────────
  // 상단 한 줄에 PMOS 6개: S1·S3 | M5×M6(교차) | S4·S2 — S1/S2 는 내부 노드
  // P/Q 를, S3/S4 는 출력 X/Y 를 프리차지. 그 아래 X/Y(Vout 단자) → 교차
  // NMOS M3/M4 → P/Q → 입력쌍 M1/M2(게이트 바깥향) → 테일 M7 → 접지 심볼.
  const V0 = 26
  const S1X = 58, S3X = 118, M5X = 192, M6X = 268, S4X = 342, S2X = 402
  const yP = 58, yXY = 108, yN = 148, yPQ = 186, yIn = 216, yTail = 272
  const gnd = 296

  const CkDot = ({ x, y, right }: { x: number; y: number; right?: boolean }) => (
    <g>
      <circle cx={x} cy={y} r={2.6} fill={V.wire} stroke="none" />
      <T x={right ? x + 6 : x - 6} y={y + 3} anchor={right ? 'start' : 'end'} c={V.net} sz={9}>CK</T>
    </g>
  )
  const OutTerm = ({ x, y }: { x: number; y: number }) => (
    <circle cx={x} cy={y} r={2.8} fill="none" stroke={V.wire} strokeWidth={1.1} />
  )
  const Name = ({ x, y, k, children, anchor = 'start' }: { x: number; y: number; k: DeviceKey; children: string; anchor?: 'start' | 'middle' | 'end' }) => (
    <T x={x} y={y} anchor={anchor} c={changed === k ? V.changed : V.sym} sz={7.5}>{children}</T>
  )

  return (
    <svg viewBox="0 0 460 330" width="100%" style={{ display: 'block', maxHeight: 460, background: V.bg, borderRadius: 8 }} role="img" aria-label="StrongARM latch transistor schematic (Virtuoso style, Razavi fig. b layout)">
      <defs>
        <pattern id="vgrid" width={12} height={12} patternUnits="userSpaceOnUse">
          <circle cx={0.6} cy={0.6} r={0.6} fill={V.grid} />
        </pattern>
      </defs>
      <rect x={0} y={0} width={460} height={330} fill="url(#vgrid)" />

      {/* VDD rail */}
      <line x1={30} y1={V0} x2={430} y2={V0} stroke={V.wire} strokeWidth={1.5} />
      <T x={430} y={V0 - 5} anchor="end" c={V.netGlobal} sz={9}>vdd!</T>

      {/* ── 상단 PMOS 행: S1 S3 M5 M6 S4 S2 (전원 → 각 드레인) ── */}
      {[S1X, S3X, S4X, S2X].map((x) => <Wire key={x} d={`${x},${V0} ${x},${yP - 13}`} />)}
      <Wire d={`${M5X},${V0} ${M5X},${yP - 13}`} /><Wire d={`${M6X},${V0} ${M6X},${yP - 13}`} />
      <Mos cx={S1X} cy={yP} p flash={changed === 'prei'} />
      <Mos cx={S3X} cy={yP} p flash={changed === 'pre'} />
      <Mos cx={M5X} cy={yP} p hot flip flash={changed === 'pcc'} />
      <Mos cx={M6X} cy={yP} p hot flash={changed === 'pcc'} />
      <Mos cx={S4X} cy={yP} p flip flash={changed === 'pre'} />
      <Mos cx={S2X} cy={yP} p flip flash={changed === 'prei'} />
      <Name x={S1X - 4} y={yP - 16} k="prei" anchor="middle">S1</Name>
      <Name x={S3X - 4} y={yP - 16} k="pre" anchor="middle">S3</Name>
      <Name x={M5X - 14} y={yP - 16} k="pcc" anchor="middle">M5</Name>
      <Name x={M6X + 14} y={yP - 16} k="pcc" anchor="middle">M6</Name>
      <Name x={S4X + 4} y={yP - 16} k="pre" anchor="middle">S4</Name>
      <Name x={S2X + 4} y={yP - 16} k="prei" anchor="middle">S2</Name>
      <Prop x={S3X - 34} y={yP + 26} k="pre" />
      <Prop x={S2X - 6} y={yP + 26} k="prei" />
      <Prop x={M6X + 24} y={yP + 30} k="pcc" />

      {/* CK — 왼쪽(S1·S3)과 오른쪽(S4·S2) */}
      <CkDot x={26} y={yP} />
      <Wire d={`26,${yP} ${S1X - 18},${yP}`} />
      <Wire d={`${S1X - 18},${yP} ${S3X - 18},${yP}`} />
      <CkDot x={434} y={yP} right />
      <Wire d={`434,${yP} ${S2X + 18},${yP}`} />
      <Wire d={`${S2X + 18},${yP} ${S4X + 18},${yP}`} />

      {/* M5/M6 교차(게이트 ↔ 반대편 드레인 기둥) */}
      <Wire d={`${M5X + 18},${yP} ${M6X},${yP + 24}`} />
      <Wire d={`${M6X - 18},${yP} ${M5X},${yP + 24}`} />
      <Dot x={M5X} y={yP + 24} /><Dot x={M6X} y={yP + 24} />

      {/* ── X/Y 노드 행 + Vout 단자 ── */}
      <Wire d={`${M5X},${yP + 13} ${M5X},${yN - 13}`} />
      <Wire d={`${M6X},${yP + 13} ${M6X},${yN - 13}`} />
      <Wire d={`${S3X},${yP + 13} ${S3X},${yXY} ${M5X},${yXY}`} />
      <Wire d={`${S4X},${yP + 13} ${S4X},${yXY} ${M6X},${yXY}`} />
      <Dot x={M5X} y={yXY} /><Dot x={M6X} y={yXY} />
      <T x={M5X - 6} y={yXY + 12} anchor="end" c={V.net} sz={8.5}>X·outp</T>
      <T x={M6X + 6} y={yXY + 12} c={V.net} sz={8.5}>Y·outn</T>
      <Wire d={`${M5X},${yXY} ${M5X + 22},${yXY - 6} ${M5X + 30},${yXY - 6}`} />
      <Wire d={`${M6X},${yXY} ${M6X - 22},${yXY - 6} ${M6X - 30},${yXY - 6}`} />
      <OutTerm x={M5X + 33} y={yXY - 6} /><OutTerm x={M6X - 33} y={yXY - 6} />
      <T x={(M5X + M6X) / 2} y={yXY - 10} anchor="middle" c={V.net} sz={8.5}>Vout</T>

      {/* ── 교차 NMOS M3/M4: X/Y → P/Q ── */}
      <Mos cx={M5X} cy={yN} hot flip flash={changed === 'ncc'} />
      <Mos cx={M6X} cy={yN} hot flash={changed === 'ncc'} />
      <Name x={M5X - 14} y={yN + 4} k="ncc" anchor="end">M3</Name>
      <Name x={M6X + 14} y={yN + 4} k="ncc">M4</Name>
      <Prop x={M6X + 24} y={yN + 22} k="ncc" />
      <Wire d={`${M5X + 18},${yN} ${M6X},${yN - 22}`} />
      <Wire d={`${M6X - 18},${yN} ${M5X},${yN - 22}`} />
      <Dot x={M5X} y={yN - 22} /><Dot x={M6X} y={yN - 22} />

      {/* ── P/Q 노드 (S1/S2 프리차지가 바깥 기둥으로 내려온다) ── */}
      <Wire d={`${M5X},${yN + 13} ${M5X},${yIn - 13}`} />
      <Wire d={`${M6X},${yN + 13} ${M6X},${yIn - 13}`} />
      <Dot x={M5X} y={yPQ} /><Dot x={M6X} y={yPQ} />
      <T x={M5X - 6} y={yPQ - 4} anchor="end" c={V.net} sz={8.5}>P·nX</T>
      <T x={M6X + 6} y={yPQ - 4} c={V.net} sz={8.5}>Q·nY</T>
      <Wire d={`${S1X},${yP + 13} ${S1X},${yPQ} ${M5X},${yPQ}`} />
      <Wire d={`${S2X},${yP + 13} ${S2X},${yPQ} ${M6X},${yPQ}`} />

      {/* ── 입력쌍 M1/M2 (게이트 바깥향, Vin 단자) ── */}
      <Mos cx={M5X} cy={yIn} flash={changed === 'input'} />
      <Mos cx={M6X} cy={yIn} flip flash={changed === 'input'} />
      <Name x={M5X + 12} y={yIn - 14} k="input">M1</Name>
      <Name x={M6X - 12} y={yIn - 14} k="input" anchor="end">M2</Name>
      <Prop x={M5X - 66} y={yIn + 22} k="input" />
      <Wire d={`${M5X - 18},${yIn} ${M5X - 44},${yIn}`} />
      <Wire d={`${M6X + 18},${yIn} ${M6X + 44},${yIn}`} />
      <OutTerm x={M5X - 47} y={yIn} /><OutTerm x={M6X + 47} y={yIn} />
      <T x={M5X - 54} y={yIn + 3} anchor="end" c={V.net} sz={8.5}>vinp</T>
      <T x={M6X + 54} y={yIn + 3} c={V.net} sz={8.5}>vinn</T>

      {/* ── 공통 소스 → 테일 M7 → 접지 심볼 ── */}
      <Wire d={`${M5X},${yIn + 13} ${M5X},${yTail - 26} 230,${yTail - 26} 230,${yTail - 13}`} />
      <Wire d={`${M6X},${yIn + 13} ${M6X},${yTail - 26} 230,${yTail - 26}`} />
      <Dot x={230} y={yTail - 26} />
      <Mos cx={230} cy={yTail} flash={changed === 'tail'} />
      <Name x={230 + 14} y={yTail + 4} k="tail">M7</Name>
      <Prop x={230 + 40} y={yTail + 4} k="tail" />
      <CkDot x={168} y={yTail} />
      <Wire d={`168,${yTail} ${230 - 18},${yTail}`} />
      {/* ground symbol */}
      <Wire d={`230,${yTail + 13} 230,${gnd}`} />
      <line x1={218} y1={gnd} x2={242} y2={gnd} stroke={V.wire} strokeWidth={1.5} />
      <line x1={223} y1={gnd + 5} x2={237} y2={gnd + 5} stroke={V.wire} strokeWidth={1.3} />
      <line x1={227} y1={gnd + 10} x2={233} y2={gnd + 10} stroke={V.wire} strokeWidth={1.1} />
    </svg>
  )
}

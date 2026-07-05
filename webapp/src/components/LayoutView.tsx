import type { LayoutResult } from '../types'
import { LAYER_STYLE, V, type Hatch } from '../virtuoso'

// GDS layout drawn in the Cadence Virtuoso "Layout XL" idiom: pure-black canvas,
// each mask layer rendered as a semi-transparent colour with its own
// stipple/hatch pattern (so overlapping layers stay legible) plus a bright
// boundary — the way real EDA layout editors distinguish layers. Y is flipped so
// the origin reads bottom-left.
export default function LayoutView({ data }: { data: LayoutResult }) {
  const { bbox } = data
  const W = bbox.w, H = bbox.h
  const layers = [...data.layers].sort((a, b) => a.z - b.z)
  const Y = (ry: number, rh: number) => bbox.y0 + H - (ry + rh)
  const s = 0.42 // hatch tile (µm)
  const sw = 0.045

  // one hatch tile for a layer colour
  const tile = (name: string, color: string, hatch: Hatch) => {
    const g: React.ReactNode[] = []
    if (hatch === 'dots') g.push(<circle key="d" cx={s / 2} cy={s / 2} r={0.06} fill={color} />)
    if (hatch === 'diag' || hatch === 'cross') g.push(<line key="a" x1={0} y1={s} x2={s} y2={0} stroke={color} strokeWidth={sw} />)
    if (hatch === 'backdiag' || hatch === 'cross') g.push(<line key="b" x1={0} y1={0} x2={s} y2={s} stroke={color} strokeWidth={sw} />)
    if (hatch === 'vert') g.push(<line key="v" x1={s / 2} y1={0} x2={s / 2} y2={s} stroke={color} strokeWidth={sw} />)
    return (
      <pattern key={name} id={`hx-${name}`} width={s} height={s} patternUnits="userSpaceOnUse">
        {g}
      </pattern>
    )
  }

  return (
    <svg
      viewBox={`${-0.2} ${-0.2} ${W + 0.4} ${H + 0.4}`}
      width="100%"
      style={{ maxHeight: 440, display: 'block', background: V.bg, borderRadius: 8 }}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="StrongARM comparator GDS layout (Virtuoso Layout XL style)"
    >
      <defs>
        <pattern id="lgrid" width={0.5} height={0.5} patternUnits="userSpaceOnUse">
          <circle cx={0} cy={0} r={0.012} fill={V.grid} />
        </pattern>
        {layers.map((l) => {
          const st = LAYER_STYLE[l.name] || { color: l.color, hatch: 'solid' as Hatch }
          return st.hatch === 'solid' ? null : tile(l.name, st.color, st.hatch)
        })}
      </defs>

      {/* black canvas + dim snap grid */}
      <rect x={-0.2} y={-0.2} width={W + 0.4} height={H + 0.4} fill={V.bg} />
      <rect x={-0.2} y={-0.2} width={W + 0.4} height={H + 0.4} fill="url(#lgrid)" />

      {layers.map((l) => {
        const st = LAYER_STYLE[l.name] || { color: l.color, hatch: 'solid' as Hatch, op: 0.5 }
        return l.rects.map((r, i) => (
          <g key={`${l.name}-${i}`}>
            {/* body tint */}
            <rect x={r[0]} y={Y(r[1], r[3])} width={r[2]} height={r[3]} fill={st.color} fillOpacity={st.hatch === 'solid' ? st.op : 0.16} />
            {/* stipple/hatch overlay */}
            {st.hatch !== 'solid' && <rect x={r[0]} y={Y(r[1], r[3])} width={r[2]} height={r[3]} fill={`url(#hx-${l.name})`} />}
            {/* bright layer boundary */}
            <rect x={r[0]} y={Y(r[1], r[3])} width={r[2]} height={r[3]} fill="none" stroke={st.color} strokeWidth={0.02} strokeOpacity={0.9} />
          </g>
        ))
      })}

      {data.labels.map((lb, i) => (
        <text key={i} x={lb.x + lb.w / 2} y={H - 0.12} fontSize={0.32} fill={V.net} textAnchor="middle" fontFamily="ui-monospace, monospace">
          {lb.name}
        </text>
      ))}
    </svg>
  )
}

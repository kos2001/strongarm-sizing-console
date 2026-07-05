// Cadence Virtuoso visual signature — used to give the circuit views (schematic
// Composer, Layout XL, ViVA waveform) the authentic EDA-tool look: pure-black
// canvas, dim snap-grid, thin cyan wires, red pin squares, yellow property
// labels, and per-layer stipple/hatch fills. Committed dark regardless of the
// app theme — Virtuoso canvases are always black.
export const V = {
  bg: '#040a0a', // near-black canvas
  grid: '#0d2422', // dim teal snap-grid dots
  gridMajor: '#123230',
  wire: '#39d7d7', // cyan interconnect
  sym: '#63d68a', // instance/symbol green (analogLib)
  symHot: '#8fe6ff', // active/regenerating device
  pin: '#ff5a52', // pin squares (red)
  prop: '#e6c84f', // instance property labels (yellow)
  net: '#57e0e0', // net-name labels (cyan)
  netGlobal: '#ff8a3d', // global nets (vdd!/gnd!) — orange
  changed: '#ffb02e', // just-edited device (amber, glows)
  text: '#cfe9e6',
  faint: '#4f7f7d',
}

// ViVA (waveform) trace colors — bright on black, distinct hues.
export const VIVA = {
  bg: '#04090a',
  grid: '#0e2626',
  gridMajor: '#143433',
  clk: '#e6c84f', // yellow
  outp: '#39d7d7', // cyan
  outn: '#ff6fae', // magenta/pink
  cursor: '#8fe6a0', // green cursor
  clkCursor: '#e6c84f',
  before: '#4f7f7d',
  text: '#bfe4e0',
  faint: '#4f7f7d',
}

// SKY130-ish layer draw style for the Layout XL look: color + a stipple/hatch
// pattern id (defined in LayoutView <defs>) so overlapping layers stay legible.
export type Hatch = 'dots' | 'diag' | 'backdiag' | 'cross' | 'solid' | 'vert'
export const LAYER_STYLE: Record<string, { color: string; hatch: Hatch; op: number }> = {
  nwell: { color: '#59c08a', hatch: 'dots', op: 0.9 },
  diff: { color: '#2fbf6b', hatch: 'solid', op: 0.55 },
  tap: { color: '#8a8f98', hatch: 'cross', op: 0.8 },
  poly: { color: '#e5544a', hatch: 'backdiag', op: 0.9 },
  licon: { color: '#d7dbe2', hatch: 'solid', op: 0.85 },
  li1: { color: '#4a90d9', hatch: 'diag', op: 0.85 },
  met1: { color: '#f0a500', hatch: 'diag', op: 0.9 },
}

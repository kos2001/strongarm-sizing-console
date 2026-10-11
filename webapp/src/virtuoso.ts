// Cadence Virtuoso visual signature — used to give the circuit views (schematic
// Composer, Layout XL, ViVA waveform) the authentic EDA-tool look: pure-black
// canvas, dim snap-grid, thin cyan wires, red pin squares, yellow property
// labels, and per-layer stipple/hatch fills. Light mode uses a paper background
// and deeper ink colors for the same circuit and signal roles.
// SVG colors resolve CSS variables, so memoized schematics update with the theme.
export const V = {
  bg: 'var(--circuit-bg)', grid: 'var(--circuit-grid)', gridMajor: 'var(--circuit-grid-major)',
  wire: 'var(--circuit-wire)', sym: 'var(--circuit-symbol)', symHot: 'var(--circuit-active)',
  pin: 'var(--circuit-pin)', prop: 'var(--circuit-property)', net: 'var(--circuit-net)',
  netGlobal: 'var(--circuit-global)', changed: 'var(--circuit-changed)',
  text: 'var(--circuit-text)', faint: 'var(--circuit-faint)',
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

export type WaveformPalette = typeof VIVA
const LIGHT_VIVA: WaveformPalette = {
  bg: '#f8fbff', grid: '#e7eef8', gridMajor: '#d1dff0',
  clk: '#955700', outp: '#1d4ed8', outn: '#be185d',
  cursor: '#087f5b', clkCursor: '#955700', before: '#64748b',
  text: '#334968', faint: '#536581',
}
// Canvas requires resolved colors; use the explicit theme instead of CSS strings.
export const waveformPalette = (theme: string): WaveformPalette => theme === 'light' ? LIGHT_VIVA : VIVA

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

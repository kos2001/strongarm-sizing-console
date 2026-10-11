import { nearestSample, traceIndices, type TimeRange } from './waveform'
import type { WaveformPalette } from './virtuoso'

export interface Trace { name: string; times: number[]; values: number[]; color: string; dashed?: boolean }
export interface Marker { time: number | null | undefined; label: string; color: string }
export const LEFT = 38, RIGHT = 12, TOP = 20, BOTTOM = 24, HEIGHT = 210

export function createPlotGeometry(width: number, range: TimeRange, voltage: TimeRange) {
  const plotWidth = Math.max(1, width - LEFT - RIGHT)
  return {
    plotWidth,
    x: (time: number) => LEFT + (time - range[0]) / (range[1] - range[0] || 1) * plotWidth,
    y: (value: number) => HEIGHT - BOTTOM - (value - voltage[0]) / (voltage[1] - voltage[0] || 1) * (HEIGHT - TOP - BOTTOM),
  }
}
type Geometry = ReturnType<typeof createPlotGeometry>

export function createTracePaths(traces: Trace[], range: TimeRange, geometry: Geometry) {
  const plotWidth = geometry.plotWidth
  return traces.map(trace => {
    const path = new Path2D()
    traceIndices(trace.times, trace.values, range, plotWidth).forEach((i, n) => {
      const px = geometry.x(trace.times[i]), py = geometry.y(trace.values[i])
      if (n) path.lineTo(px, py)
      else path.moveTo(px, py)
    })
    return path
  })
}

function prepareCanvas(cv: HTMLCanvasElement, width: number) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  cv.width = Math.round(width * dpr); cv.height = HEIGHT * dpr
  const ctx = cv.getContext('2d')!
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  return ctx
}

interface PlotScene {
  width: number
  range: TimeRange
  geometry: Geometry
  traces: Trace[]
  hidden: string[]
  palette: WaveformPalette
}

export function drawWaveform(cv: HTMLCanvasElement, { width, range, geometry, traces, hidden, palette, voltage, paths, markers }: PlotScene & {
  voltage: TimeRange; paths: Path2D[]; markers: Marker[]
}) {
  const ctx = prepareCanvas(cv, width)
  const plotWidth = geometry.plotWidth
  ctx.fillStyle = palette.bg; ctx.fillRect(0, 0, width, HEIGHT)
  ctx.font = '10px ui-monospace, monospace'; ctx.lineWidth = 1
  for (let i = 0; i <= 10; i++) {
    const px = LEFT + plotWidth * i / 10
    ctx.strokeStyle = i % 2 ? palette.grid : palette.gridMajor
    ctx.beginPath(); ctx.moveTo(px, TOP); ctx.lineTo(px, HEIGHT - BOTTOM); ctx.stroke()
    if (i % 2 === 0) {
      ctx.fillStyle = palette.text
      const text = (range[0] + (range[1] - range[0]) * i / 10).toFixed(2)
      ctx.fillText(text, Math.max(0, Math.min(width - ctx.measureText(text).width, px - 12)), HEIGHT - 6)
    }
  }
  for (let i = 0; i <= 4; i++) {
    const value = voltage[0] + (voltage[1] - voltage[0]) * i / 4, py = geometry.y(value)
    ctx.strokeStyle = palette.gridMajor
    ctx.beginPath(); ctx.moveTo(LEFT, py); ctx.lineTo(width - RIGHT, py); ctx.stroke()
    ctx.fillStyle = palette.text; ctx.fillText(value.toFixed(2), 2, py + 3)
  }
  ctx.fillText('V', 2, 12); ctx.fillText('ns', width - 16, 12)
  ctx.save(); ctx.beginPath(); ctx.rect(LEFT, TOP, plotWidth, HEIGHT - TOP - BOTTOM); ctx.clip()
  markers.forEach(marker => {
    if (marker.time == null || marker.time < range[0] || marker.time > range[1]) return
    const px = geometry.x(marker.time)
    ctx.strokeStyle = marker.color; ctx.setLineDash([3, 4])
    ctx.beginPath(); ctx.moveTo(px, TOP); ctx.lineTo(px, HEIGHT - BOTTOM); ctx.stroke()
    ctx.fillStyle = marker.color; ctx.fillText(marker.label, px + 3, TOP + 10)
  })
  traces.forEach((trace, i) => {
    if (hidden.includes(trace.name)) return
    ctx.strokeStyle = trace.color; ctx.lineWidth = trace.dashed ? 1 : 1.7
    ctx.globalAlpha = trace.dashed ? .5 : 1; ctx.setLineDash(trace.dashed ? [3, 3] : [])
    ctx.stroke(paths[i])
  })
  ctx.restore()
}

export function drawCursor(cv: HTMLCanvasElement, { width, range, geometry, traces, hidden, palette }: PlotScene, times: number[], index: number) {
  const ctx = prepareCanvas(cv, width)
  if (index < 0 || times[index] < range[0] || times[index] > range[1]) return
  const px = geometry.x(times[index])
  ctx.strokeStyle = palette.cursor; ctx.lineWidth = 1; ctx.setLineDash([3, 3])
  ctx.beginPath(); ctx.moveTo(px, TOP); ctx.lineTo(px, HEIGHT - BOTTOM); ctx.stroke(); ctx.setLineDash([])
  traces.forEach(trace => {
    if (hidden.includes(trace.name)) return
    const sample = nearestSample(trace.times, times[index])
    if (sample < 0 || !Number.isFinite(trace.values[sample])) return
    ctx.fillStyle = trace.color; ctx.beginPath(); ctx.arc(px, geometry.y(trace.values[sample]), 3, 0, Math.PI * 2); ctx.fill()
  })
}

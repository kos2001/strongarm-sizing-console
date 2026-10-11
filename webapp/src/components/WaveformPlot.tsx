import { memo, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { Lang } from '../i18n'
import { nearestSample, zoomRange, type TimeRange } from '../waveform'
import { VIVA, type WaveformPalette } from '../virtuoso'

import { LEFT, HEIGHT, createPlotGeometry, createTracePaths, drawWaveform, drawCursor, type Trace, type Marker } from '../waveformCanvas'

const EMPTY_MARKERS: Marker[] = []

/** The cursor has its own canvas so pointer movement never rebuilds trace paths. */
function WaveformPlot({ times, traces, markers = EMPTY_MARKERS, voltage, label, palette = VIVA, lang = 'en' }: {
  times: number[]; traces: Trace[]; markers?: Marker[]; voltage: TimeRange; label: string; palette?: WaveformPalette; lang?: Lang
}) {
  const ko = lang === 'ko'
  const id = useId()
  const canvas = useRef<HTMLCanvasElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const pointerFrame = useRef(0)
  const [width, setWidth] = useState(0)
  const [hidden, setHidden] = useState<string[]>([])
  const [selection, setSelection] = useState<{ times: number[]; index: number } | null>(null)
  const index = selection?.times === times ? selection.index : -1
  const full = useMemo<TimeRange>(() => [times[0] ?? 0, times.at(-1) || 1], [times])
  const [viewport, setViewport] = useState<{ times: number[]; range: TimeRange } | null>(null)
  const range = viewport?.times === times ? viewport.range : full
  const geometry = useMemo(() => createPlotGeometry(width, range, voltage), [width, range, voltage])

  useEffect(() => {
    const cv = canvas.current
    if (!cv) return
    let frame = 0
    const measure = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => setWidth(cv.getBoundingClientRect().width))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(cv)
    return () => { observer.disconnect(); cancelAnimationFrame(frame); cancelAnimationFrame(pointerFrame.current) }
  }, [!!times.length])

  const paths = useMemo(() => createTracePaths(traces, range, geometry), [traces, range, geometry])

  useEffect(() => {
    const cv = canvas.current
    if (!cv || !width) return
    drawWaveform(cv, { width, range, geometry, traces, hidden, palette, voltage, paths, markers })
  }, [paths, hidden, markers, width, range, voltage, traces, geometry, palette])

  useEffect(() => {
    const cv = overlay.current
    if (!cv || !width) return
    drawCursor(cv, { width, range, geometry, traces, hidden, palette }, times, index)
  }, [index, width, times, range, hidden, traces, geometry, palette])

  const plotWidth = geometry.plotWidth
  const zoom = (factor: number) => {
    const anchor = index >= 0 && times[index] >= range[0] && times[index] <= range[1] ? times[index] : (range[0] + range[1]) / 2
    setViewport({ times, range: zoomRange(range, full, factor, anchor) })
  }
  const zoomed = range[0] !== full[0] || range[1] !== full[1]
  const first = Math.max(0, nearestSample(times, range[0])), last = Math.max(0, nearestSample(times, range[1]))
  if (!times.length) return <p role="status">{ko ? '파형 샘플이 없습니다.' : 'No waveform samples.'}</p>
  return <div className="waveform-plot" role="group" aria-label={label}>
    <div className="waveform-toolbar">
      <div className="waveform-signals">{traces.map(trace => <button key={trace.name} aria-pressed={!hidden.includes(trace.name)}
        style={{ color: trace.color }} onClick={() => setHidden(previous => previous.includes(trace.name) ? previous.filter(name => name !== trace.name) : [...previous, trace.name])}>
        <span aria-hidden="true">{trace.dashed ? '┄' : '━'}</span> {trace.name}
      </button>)}</div>
      <div className="waveform-zoom">
        <button onClick={() => zoom(.5)} disabled={range[1] - range[0] <= (full[1] - full[0]) / 1024} aria-label={ko ? '파형 확대' : 'Zoom in'}>＋</button>
        <button onClick={() => zoom(2)} disabled={!zoomed} aria-label={ko ? '파형 축소' : 'Zoom out'}>−</button>
        <button onClick={() => setViewport(null)} disabled={!zoomed}>{ko ? '전체 보기' : 'Reset view'}</button>
      </div>
    </div>
    <div className="waveform-canvas" style={{ height: HEIGHT }}>
      <canvas ref={canvas} aria-label={label} />
      <canvas ref={overlay} aria-hidden="true" onPointerMove={event => {
        const rect = event.currentTarget.getBoundingClientRect()
        const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left - LEFT) / plotWidth))
        const next = nearestSample(times, range[0] + fraction * (range[1] - range[0]))
        cancelAnimationFrame(pointerFrame.current)
        pointerFrame.current = requestAnimationFrame(() => setSelection({ times, index: next }))
      }} />
    </div>
    <label className="waveform-cursor" htmlFor={id}>{ko ? '측정 커서' : 'Measurement cursor'}
      <input id={id} type="range" min={first} max={last} value={index < 0 ? first : Math.max(first, Math.min(last, index))}
        onChange={event => setSelection({ times, index: Number(event.target.value) })} />
    </label>
    <div className="waveform-readout mono tnum" role="status" aria-live="off">
      {index < 0 ? (ko ? '파형 위에서 이동하거나 커서를 조절하여 값을 확인하세요.' : 'Move over the waveform or adjust the cursor to inspect samples.')
        : <><span>t = {times[index].toFixed(4)} ns</span>{traces.filter(trace => !hidden.includes(trace.name)).map(trace => {
          const sample = nearestSample(trace.times, times[index])
          return <span key={trace.name} style={{ color: trace.color }}>{trace.name} = {sample >= 0 && Number.isFinite(trace.values[sample]) ? trace.values[sample].toFixed(4) : '—'} V</span>
        })}</>}
    </div>
  </div>
}
export default memo(WaveformPlot)

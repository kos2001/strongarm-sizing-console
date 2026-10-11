import { memo, useMemo } from 'react'
import type { Waveform } from '../types'
import type { Lang } from '../i18n'
import { waveformPalette } from '../virtuoso'
import WaveformPlot from './WaveformPlot'
import type { Trace, Marker } from '../waveformCanvas'
import type { TimeRange } from '../waveform'

function WaveformChart({ wf, before, lang, theme }: { wf: Waveform; before?: Waveform | null; theme: string; lang?: Lang }) {
  const palette = waveformPalette(theme)
  const traces = useMemo<Trace[]>(() => [
    ...(before?.t_ns?.length ? [
      { name: 'before outp', times: before.t_ns, values: before.outp, color: palette.before, dashed: true },
      { name: 'before outn', times: before.t_ns, values: before.outn, color: palette.before, dashed: true },
    ] : []),
    { name: 'clk', times: wf.t_ns, values: wf.clk, color: palette.clk },
    { name: 'outn', times: wf.t_ns, values: wf.outn, color: palette.outn },
    { name: 'outp', times: wf.t_ns, values: wf.outp, color: palette.outp },
  ], [wf, before, palette])
  const markers = useMemo<Marker[]>(() => [
    { time: before?.decision_ns, label: 'before', color: palette.before },
    { time: wf.clk_edge_ns, label: 'clk ↑', color: palette.clkCursor },
    { time: wf.decision_ns, label: before ? 'after' : 'decide', color: palette.cursor },
  ], [wf, before, palette])
  const voltage = useMemo<TimeRange>(() => [0, Math.max(wf.vdd, before?.vdd ?? 0) * 1.08], [wf.vdd, before?.vdd])
  return <WaveformPlot times={wf.t_ns} traces={traces} palette={palette} markers={markers} voltage={voltage} lang={lang}
    label="Transient waveform: comparator outputs resolving after the clock edge" />
}
export default memo(WaveformChart)

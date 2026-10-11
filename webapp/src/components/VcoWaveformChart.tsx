import { memo, useMemo } from 'react'
import type { VcoWaveform } from '../types'
import type { Lang } from '../i18n'
import type { TimeRange } from '../waveform'
import { waveformPalette } from '../virtuoso'
import WaveformPlot from './WaveformPlot'
import type { Trace } from '../waveformCanvas'

function VcoWaveformChart({ wf, labels = ['o1', 'o2'], lang, theme }: { wf: VcoWaveform; theme: string; labels?: [string, string]; lang?: Lang }) {
  const palette = waveformPalette(theme)
  const traces = useMemo<Trace[]>(() => [
    { name: labels[0], times: wf.t_ns, values: wf.o1, color: palette.outp },
    { name: labels[1], times: wf.t_ns, values: wf.o2, color: palette.outn },
  ], [wf, labels[0], labels[1], palette])
  const voltage = useMemo<TimeRange>(() => [-.15 * wf.vdd, 1.15 * wf.vdd], [wf.vdd])
  return <WaveformPlot times={wf.t_ns} traces={traces} palette={palette} voltage={voltage} lang={lang} label="Ring VCO oscillation waveform" />
}
export default memo(VcoWaveformChart)

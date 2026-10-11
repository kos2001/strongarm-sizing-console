export type TimeRange = readonly [number, number]

export function lowerBound(times: readonly number[], time: number) {
  let lo = 0, hi = times.length
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (times[mid] < time) lo = mid + 1
    else hi = mid
  }
  return lo
}

export function nearestSample(times: readonly number[], time: number) {
  if (!times.length) return -1
  const i = lowerBound(times, time)
  if (i === 0) return 0
  if (i === times.length) return i - 1
  return time - times[i - 1] <= times[i] - time ? i - 1 : i
}

/** Retain first/last and both extrema per screen pixel, including narrow pulses.
 * Cursor measurements continue to use the original, unreduced samples. */
export function traceIndices(times: readonly number[], values: readonly number[], range: TimeRange, pixels: number) {
  const length = Math.min(times.length, values.length)
  if (!length) return []
  const start = Math.max(0, lowerBound(times, range[0]) - 1)
  const end = Math.min(length, lowerBound(times, range[1]) + 1)
  const width = Math.max(1, Math.floor(pixels))
  if (end - start <= width * 4) return Array.from({ length: Math.max(0, end - start) }, (_, i) => start + i)
  const result: number[] = []
  const span = range[1] - range[0] || 1
  let first = start, min = start, max = start, bucket = -Infinity
  const emit = (last: number) => {
    for (const i of [...new Set([first, min, max, last])].sort((a, b) => a - b)) result.push(i)
  }
  for (let i = start; i < end; i++) {
    const next = Math.max(0, Math.min(width - 1, Math.floor((times[i] - range[0]) / span * width)))
    if (next !== bucket) {
      if (i > start) emit(i - 1)
      first = min = max = i
      bucket = next
    }
    if (values[i] < values[min]) min = i
    if (values[i] > values[max]) max = i
  }
  emit(end - 1)
  return result
}

export function zoomRange(range: TimeRange, full: TimeRange, factor: number, anchor: number): TimeRange {
  const fullSpan = full[1] - full[0]
  if (fullSpan <= 0) return full
  const span = range[1] - range[0]
  const nextSpan = Math.min(fullSpan, Math.max(fullSpan / 1024, span * factor))
  const fraction = Math.max(0, Math.min(1, (anchor - range[0]) / (span || 1)))
  const start = Math.max(full[0], Math.min(full[1] - nextSpan, anchor - nextSpan * fraction))
  return [start, start + nextSpan]
}

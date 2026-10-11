import { test } from 'node:test'
import assert from 'node:assert/strict'
import { nearestSample, traceIndices, zoomRange } from '../src/waveform.ts'

test('cursor locates the original nearest sample in irregularly spaced data', () => {
  const times = [0, .01, .02, 1, 10]
  assert.equal(nearestSample(times, .021), 2)
  assert.equal(nearestSample(times, .8), 3)
  assert.equal(nearestSample(times, -1), 0)
  assert.equal(nearestSample(times, 99), 4)
  assert.equal(nearestSample([], 1), -1)
})

test('large traces preserve narrow spikes, troughs, endpoints and sample order', () => {
  const times = Array.from({ length: 100_000 }, (_, i) => i / 1000)
  const values = times.map(() => 0)
  values[12222] = 8
  values[12223] = -3
  const indices = traceIndices(times, values, [0, times.at(-1)], 500)
  assert(indices.includes(12222))
  assert(indices.includes(12223))
  assert.equal(indices[0], 0)
  assert.equal(indices.at(-1), times.length - 1)
  assert(indices.length <= 2000)
  assert(indices.every((value, i) => !i || value > indices[i - 1]))
})

test('zoom keeps crossing segments and clips work to the visible samples', () => {
  const times = [0, 1, 2, 3, 4, 5, 6]
  assert.deepEqual(traceIndices(times, times, [2.2, 3.8], 200), [2, 3, 4])
  assert.deepEqual(traceIndices([], [], [0, 1], 200), [])
  assert.deepEqual(traceIndices(times, [], [0, 1], 200), [])
})

test('zoom stays bounded, is anchored at the cursor, and resets to full extent', () => {
  assert.deepEqual(zoomRange([0, 10], [0, 10], .5, 5), [2.5, 7.5])
  assert.deepEqual(zoomRange([0, 10], [0, 10], .5, 0), [0, 5])
  assert.deepEqual(zoomRange([5, 10], [0, 10], .5, 10), [7.5, 10])
  assert.deepEqual(zoomRange([2.5, 7.5], [0, 10], 10, 5), [0, 10])
  assert.deepEqual(zoomRange([0, 0], [0, 0], .5, 0), [0, 0])
  const small = zoomRange([0, .01], [0, 10], .001, .005)
  assert(small[1] - small[0] >= 10 / 1024)
})

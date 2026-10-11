import test from 'node:test'
import assert from 'node:assert/strict'
import { createComparatorReport } from '../src/report.ts'
import { DEFAULTS, SPEC_PROFILES } from '../src/comparator.ts'

const generated = '2026-10-11T01:02:03.000Z'
const input = {
  params: structuredClone(DEFAULTS),
  targets: { ...SPEC_PROFILES[0].targets },
  profile: 'P1',
  result: {
    nominal: { decision_time_ps: 180, power_uw: 125, noise_uv_rms: 0, functional: true },
    offset: { offset_sigma_mv: 2.5 },
    verdicts: {},
  },
}

test('report uses current measurements, sizing and targets, including zero values', () => {
  const report = createComparatorReport(input, generated)
  assert.ok(report.includes(`- Generated: ${generated}`))
  assert.ok(report.includes('- Spec profile: P1 · SAR-ADC'))
  assert.match(report, /\(input\) \| 8 \| 80 \| 4 \|/)
  assert.ok(report.includes('| Decision time | 180 ps | ≤ 400 ps | PASS |'))
  assert.ok(report.includes('| Power | 125 µW | ≤ 100 µW | FAIL |'))
  assert.ok(report.includes('| Input noise | 0 µV | ≤ 250 µV | PASS |'))
})

test('unmeasured metrics are left unknown rather than marked as passing', () => {
  const report = createComparatorReport({ ...input, profile: 'custom', result: { nominal: input.result.nominal } }, generated)
  assert.ok(report.includes('- Spec profile: custom'))
  assert.ok(report.includes('| Offset σ | — | ≤ 5 mV | — |'))
  const empty = createComparatorReport({ ...input, result: null }, generated)
  assert.ok(empty.includes('| Decision time | — | ≤ 400 ps | — |'))
})

test('optional analysis sections and raw JSON preserve their measured results', () => {
  const metaRes = { tau_ps: 25, min_resolved_v: 0.00002 }
  const pvtRes = { worst: { decision_time_ps: 450, power_uw: 140, any_nonfunctional: true } }
  const report = createComparatorReport({ ...input, metaRes, pvtRes }, generated)
  assert.ok(report.includes('- Regeneration τ: 25 ps'))
  assert.ok(report.includes('- Min resolved input: 20.0 µV'))
  assert.ok(report.includes('- All corners resolve: NO'))
  assert.ok(!report.includes('## Noise / BER'))
  const raw = JSON.parse(report.match(/```json\n([\s\S]*?)\n```/)[1])
  assert.deepEqual(raw.result, input.result)
  assert.deepEqual(raw.params, input.params)
  assert.deepEqual(raw.targets, input.targets)
  assert.deepEqual(raw.metaRes, metaRes)
  assert.deepEqual(raw.pvtRes, pvtRes.worst)
  assert.equal(raw.generated, generated)
})

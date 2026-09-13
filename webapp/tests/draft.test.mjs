import { test } from 'node:test'
import assert from 'node:assert/strict'
import { decodeDraft, matchesInputs } from '../src/draft.ts'

const defaults = { vdd: 0.7, devices: { input: { w_um: 8, l_nm: 80, m: 4 } } }
const validate = matchesInputs(defaults)
const encode = (value, version = 1) => JSON.stringify({ version, value, savedAt: 1234 })
test('restores all design fields, including optional model settings', () => {
  const value = { ...defaults, model: 'asap7', vdd: 0.65 }
  assert.deepEqual(decodeDraft(encode(value), validate).value, value)
})
test('ignores corrupted, incomplete, and future-version drafts', () => {
  for (const raw of [null, '', '{broken', 'null', '{}', encode(defaults, 2), encode({ vdd: 0.7 }), encode({ ...defaults, vdd: 'bad' })]) {
    assert.equal(decodeDraft(raw, validate), null)
  }
})
test('rejects non-finite inputs and malformed timestamps', () => {
  assert.equal(validate({ ...defaults, vdd: NaN }), false)
  assert.equal(validate({ ...defaults, extra: { x: Infinity } }), false)
  assert.equal(decodeDraft('{"version":1,"value":{},"savedAt":"today"}', validate), null)
})

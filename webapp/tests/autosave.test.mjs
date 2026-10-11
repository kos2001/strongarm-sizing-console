import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createAutosave } from '../src/autosave.ts'

test('rapid edits coalesce into a single write containing the latest value', context => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  const writes = []
  const saver = createAutosave(value => writes.push(value))
  for (let i = 0; i < 20; i++) { saver.schedule(i); context.mock.timers.tick(10) }
  assert.deepEqual(writes, [])
  context.mock.timers.tick(250)
  assert.deepEqual(writes, [19])
})

test('lifecycle flush saves immediately and cancels duplicate delayed writes', context => {
  context.mock.timers.enable({ apis: ['setTimeout'] })
  const writes = []
  const saver = createAutosave(value => writes.push(value))
  saver.schedule('latest input')
  saver.flush()
  saver.flush()
  context.mock.timers.tick(1000)
  assert.deepEqual(writes, ['latest input'])
  saver.schedule('next edit')
  context.mock.timers.tick(250)
  assert.deepEqual(writes, ['latest input', 'next edit'])
})

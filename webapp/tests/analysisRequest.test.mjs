import test from 'node:test'
import assert from 'node:assert/strict'
import { runAnalysisRequest } from '../src/analysisRequest.ts'

function lifecycle() {
  const events = []
  return {
    events,
    setLoading: value => events.push(['loading', value]),
    setError: value => events.push(['error', value]),
  }
}

test('analysis remains loading until work and result updates finish', async () => {
  const state = lifecycle()
  let resolve
  const pending = new Promise(done => { resolve = done })
  const request = runAnalysisRequest(async () => {
    await pending
    state.events.push(['result', 42])
  }, state)
  assert.deepEqual(state.events, [['loading', true], ['error', null]])
  resolve()
  await request
  assert.deepEqual(state.events, [
    ['loading', true], ['error', null], ['result', 42], ['loading', false],
  ])
})

test('failed work reports an error, releases loading, and clears the error on retry', async () => {
  for (const failure of [new Error('Backend offline'), 'Request cancelled']) {
    const state = lifecycle()
    await runAnalysisRequest(async () => { throw failure }, state)
    assert.deepEqual(state.events, [
      ['loading', true], ['error', null],
      ['error', failure instanceof Error ? failure.message : failure], ['loading', false],
    ])
    await runAnalysisRequest(async () => {}, state)
    assert.deepEqual(state.events.slice(-3), [['loading', true], ['error', null], ['loading', false]])
  }
})

test('discarding a stale result still releases loading', async () => {
  const state = lifecycle()
  let resultUpdates = 0
  const isCurrent = () => false
  await runAnalysisRequest(async () => {
    if (!isCurrent()) return
    resultUpdates++
  }, state)
  assert.equal(resultUpdates, 0)
  assert.equal(state.events.at(-1)[1], false)
})

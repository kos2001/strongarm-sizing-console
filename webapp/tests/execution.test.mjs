import { test } from 'node:test'
import assert from 'node:assert/strict'
import { requestJson, getExecutions, subscribeExecutions } from '../src/execution.ts'

test('identical in-flight requests share a fetch but not mutable result objects', async t => {
  let resolve, calls = 0
  t.mock.method(globalThis, 'fetch', () => { calls++; return new Promise(done => { resolve = done }) })
  const a = requestJson('/api/pvt', { params: { vdd: .7, model: 'ptm' } })
  const b = requestJson('/api/pvt', { params: { model: 'ptm', vdd: .7 } })
  await Promise.resolve()
  assert.equal(calls, 1)
  assert.equal(getExecutions().filter(record => record.state === 'running').length, 1)
  resolve(Response.json({ corners: [1, 2] }))
  const [first, second] = await Promise.all([a, b])
  first.corners.push(3)
  assert.deepEqual(second.corners, [1, 2])
  assert.equal(getExecutions()[0].state, 'succeeded')
})
test('status remains running until the response body has been decoded', async t => {
  let stream
  const body = new ReadableStream({ start(controller) { stream = controller } })
  t.mock.method(globalThis, 'fetch', async () => new Response(body))
  const pending = requestJson('/api/layout', { params: {} })
  await Promise.resolve()
  assert.equal(getExecutions().find(record => record.path === '/api/layout').state, 'running')
  stream.enqueue(new TextEncoder().encode('{"area":10}'))
  stream.close()
  await pending
  assert.equal(getExecutions().find(record => record.path === '/api/layout').state, 'succeeded')
})
test('failed HTTP/JSON/network responses are visible and a retry performs new work', async t => {
  let attempt = 0
  t.mock.method(globalThis, 'fetch', async () => {
    attempt++
    if (attempt === 1) return Response.json({ error: 'Model unavailable' }, { status: 503 })
    if (attempt === 2) return new Response('<html>proxy error</html>')
    if (attempt === 3) throw new Error('Network offline')
    return Response.json({ nominal: {} })
  })
  for (const message of [/Model unavailable/, /Invalid server response/, /Network offline/]) {
    await assert.rejects(requestJson('/api/vco/simulate', { params: {} }), message)
    assert.equal(getExecutions()[0].state, 'failed')
    assert.equal(getExecutions()[0].domain, 'vco')
    assert.equal(getExecutions()[0].page, 'vco')
  }
  await requestJson('/api/vco/simulate', { params: {} })
  assert.equal(attempt, 4)
  assert.equal(getExecutions()[0].state, 'succeeded')
})
test('different inputs are independent and monitoring reads do not enter execution history', async t => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => { calls++; return Response.json({ ok: true }) })
  const before = getExecutions()
  await requestJson('/api/health')
  assert.equal(getExecutions(), before)
  let events = 0
  const unsubscribe = subscribeExecutions(() => events++)
  await Promise.all([requestJson('/api/simulate', { params: { vdd: .7 } }), requestJson('/api/simulate', { params: { vdd: .8 } })])
  unsubscribe()
  assert.equal(calls, 3)
  assert.equal(events, 4)
})
test('completed history is bounded while active work is retained', async t => {
  let release
  t.mock.method(globalThis, 'fetch', async path => path === '/api/vco/phasenoise'
    ? new Promise(resolve => { release = resolve }) : Response.json({ ok: true }))
  const pending = requestJson('/api/vco/phasenoise', { params: {} })
  for (let n = 0; n < 25; n++) await requestJson('/api/wicked/wcd', { n })
  assert.equal(getExecutions().length, 21)
  assert.equal(getExecutions()[0].state, 'running')
  assert.equal(getExecutions()[0].page, 'vcopn')
  assert.equal(getExecutions()[1].page, 'wicked')
  release(Response.json({ ok: true }))
  await pending
  assert.equal(getExecutions().length, 20)
})

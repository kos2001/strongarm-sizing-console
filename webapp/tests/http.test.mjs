import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readJson } from '../src/http.ts'

test('preserves valid measurement results', async () => {
  assert.deepEqual(await readJson(Response.json({ power_uw: 12 })), { power_uw: 12 })
})
test('reports backend errors on success and failure status codes', async () => {
  for (const status of [200, 400, 500]) {
    await assert.rejects(readJson(Response.json({ error: 'Model unavailable' }, { status })), /Model unavailable/)
  }
})
test('handles proxy HTML and empty responses', async () => {
  await assert.rejects(readJson(new Response('<html>Bad gateway</html>', { status: 502 })), /HTTP 502/)
  await assert.rejects(readJson(new Response(null, { status: 204 })), /HTTP 204/)
})
test('reports status when server has no error message', async () => {
  await assert.rejects(readJson(Response.json({}, { status: 503 })), /HTTP 503/)
})

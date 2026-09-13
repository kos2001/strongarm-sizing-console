import { navigate } from './navigation.mjs'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const baseURL = process.env.CONSOLE_URL ?? 'http://127.0.0.1:8771'
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', e => errors.push(e.message))
const result = { nominal: { functional: true, decision_time_ps: 100, power_uw: 20, final_diff_v: .7, noise_uv_rms: 100 }, offset: { offset_sigma_mv: 2, offset_mean_mv: 0, pelgrom_sigma_vth_mv: 1, n_mc: 16, samples_mv: [] }, verdicts: {} }
const wave = { n: 2, vdd: .7, t_ns: [0, 1], clk: [0, .7], outp: [0, .7], outn: [.7, 0] }
await page.route('**/api/simulate', route => route.fulfill({ json: result }))
await page.route('**/api/waveform', route => route.fulfill({ json: wave }))
await page.goto(baseURL)
await page.getByLabel('설계 이름', { exact: true }).fill('ADC 비교기')
await page.getByLabel('M1 / M2 W (µm)', { exact: true }).fill('12')
await page.getByLabel('Decision time ≤').fill('200')
const downloaded = page.waitForEvent('download')
await page.getByRole('button', { name: '파일 저장', exact: true }).click()
const download = await downloaded
const saved = JSON.parse(await fs.readFile(await download.path(), 'utf8'))
assert.equal(saved.name, 'ADC 비교기')
assert.equal(saved.params.devices.input.w_um, 12)
assert.equal(saved.targets.decision_time_ps, 200)
await page.getByRole('button', { name: '▶ Run SPICE', exact: true }).click()
await page.getByTestId('design-status').getByText('스펙 만족', { exact: true }).waitFor()
await page.getByLabel('Power ≤').fill('10')
await page.getByTestId('design-status').getByText('스펙 미달', { exact: true }).waitFor()
await page.getByLabel('M1 / M2 W (µm)', { exact: true }).fill('18')
await page.getByTestId('design-status').getByText('아직 측정 안 함', { exact: true }).waitFor()
assert.equal(await page.getByRole('button', { name: '⤓ 리포트', exact: true }).isDisabled(), true)
const upload = async project => page.getByLabel('설계 파일 선택', { exact: true }).setInputFiles({ name: 'test.strongarm.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(project)) })
await upload({ ...saved, version: 900 })
await page.getByRole('alert').waitFor()
assert.equal(await page.getByLabel('M1 / M2 W (µm)', { exact: true }).inputValue(), '18')
await upload(saved)
await page.getByRole('region', { name: '가져오기 미리보기' }).waitFor()
assert.equal(await page.getByLabel('M1 / M2 W (µm)', { exact: true }).inputValue(), '18')
await page.getByRole('button', { name: '설계 불러오기', exact: true }).click()
assert.equal(await page.getByLabel('M1 / M2 W (µm)', { exact: true }).inputValue(), '12')
assert.equal(await page.getByLabel('Power ≤').inputValue(), '100')
await page.getByRole('button', { name: '이전 설계 복원', exact: true }).click()
assert.equal(await page.getByLabel('M1 / M2 W (µm)', { exact: true }).inputValue(), '18')

// A stale optimizer response must not replace a design/spec edited during a run.
let releaseOptimize
const requested = new Promise(resolve => {
  page.route('**/api/optimize', route => {
    releaseOptimize = () => route.fulfill({ json: { trajectory: [], final_params: { ...saved.params, devices: { ...saved.params.devices, input: { ...saved.params.devices.input, w_um: 777 } } }, final_result: result, verdicts: {}, success: true, targets: saved.targets } })
    resolve()
  })
})
await page.getByRole('button', { name: '◴ Auto-find W & M', exact: true }).click()
await requested
await page.getByLabel('Decision time ≤').fill('75')
await releaseOptimize()
await page.getByRole('button', { name: '◴ Auto-find W & M', exact: true }).waitFor()
assert.equal(await page.getByLabel('M1 / M2 W (µm)', { exact: true }).inputValue(), '18')

// Successful optimization must remain visible under the resulting input identity.
await page.route('**/api/optimize', route => {
  const request = route.request().postDataJSON()
  const final = { ...request.params, devices: { ...request.params.devices, input: { ...request.params.devices.input, w_um: 13 } } }
  return route.fulfill({ json: { trajectory: [{ action: 'verified final sizing', params: final.devices }], final_params: final, final_result: result, verdicts: { power_uw: true }, success: true, targets: request.targets } })
})
await page.getByRole('button', { name: '◴ Auto-find W & M', exact: true }).click()
await page.getByText('verified final sizing', { exact: true }).waitFor()
await navigate(page, '소자 크기')
assert.equal(await page.getByLabel('M1 / M2 W (µm)', { exact: true }).inputValue(), '13')
// Incomplete measurements are not reported as passing.
await page.route('**/api/simulate', route => route.fulfill({ json: { nominal: result.nominal, verdicts: {} } }))
await page.getByLabel('Decision time ≤').fill('200')
await page.getByLabel('Power ≤').fill('100')
await page.getByRole('button', { name: '▶ Run SPICE', exact: true }).click()
await page.getByTestId('design-status').getByText('일부 측정 필요', { exact: true }).waitFor()

await page.getByRole('button', { name: '∿ VCO', exact: true }).click()
await navigate(page, '사이징 · 튜닝')
await page.getByLabel('단수 N', { exact: true }).fill('5')
await page.getByLabel('설계 이름', { exact: true }).fill('PLL ring')
const vdownloaded = page.waitForEvent('download')
await page.getByRole('button', { name: '파일 저장', exact: true }).click()
const vdownload = await vdownloaded
const vsaved = JSON.parse(await fs.readFile(await vdownload.path(), 'utf8'))
assert.equal(vsaved.params.n_stages, 5)
assert.equal(vsaved.domain, 'vco')
await page.getByLabel('단수 N', { exact: true }).fill('7')
await upload(saved)
await page.getByRole('alert').waitFor()
assert.equal(await page.getByLabel('단수 N', { exact: true }).inputValue(), '7')
await upload(vsaved)
await page.getByRole('button', { name: '설계 불러오기', exact: true }).click()
assert.equal(await page.getByLabel('단수 N', { exact: true }).inputValue(), '5')
await page.route('**/api/vco/simulate', route => route.fulfill({ status: 503, json: { error: 'Simulator unavailable for test' } }))
await page.getByRole('button', { name: '▶ VCO 실행 (튜닝 포함)', exact: true }).click()
await page.getByTestId('design-status').getByText('Simulator unavailable for test', { exact: true }).waitFor()
assert.equal(await page.getByRole('button', { name: '▶ VCO 실행 (튜닝 포함)', exact: true }).isEnabled(), true)
await page.route('**/api/vco/simulate', route => route.fulfill({ json: { nominal: { oscillates: true, f_osc_ghz: 1.5, power_uw: 20, vpp_v: 1, n_stages: 5, vctrl_v: .6 } } }))
await page.getByRole('button', { name: '▶ VCO 실행 (튜닝 포함)', exact: true }).click()
await page.getByTestId('design-status').getByText('스펙 만족', { exact: true }).waitFor()
await page.getByLabel('단수 N', { exact: true }).fill('7')
await page.getByTestId('design-status').getByText('아직 측정 안 함', { exact: true }).waitFor()
await navigate(page, '자동 사이징')
await page.getByLabel('목표 주파수 (GHz)').fill('2.5')
await page.route('**/api/vco/optimize', route => {
  const request = route.request().postDataJSON()
  return route.fulfill({ json: {
    final_params: { ...request.params, n_stages: 9 },
    nominal: { oscillates: true, f_osc_ghz: 2.5, power_uw: 20, vpp_v: 1, n_stages: 9, vctrl_v: .6 },
    tuning: { points: [], f_min_ghz: 1, f_max_ghz: 3, tuning_pct: 100, kvco_ghz_per_v: 2, center_ghz: 2 },
    trajectory: [], success: true, target_f_ghz: 2.5, n_sims: 1,
  } })
})
await page.getByRole('button', { name: '◴ 자동 사이징 실행', exact: true }).click()
await page.getByTestId('design-status').getByText('스펙 만족', { exact: true }).waitFor()
assert.equal(await page.getByLabel('단수 N', { exact: true }).inputValue(), '9')
let flowTarget
await page.route('**/api/vco/fullflow', route => {
  flowTarget = route.request().postDataJSON().targets.f_ghz
  return route.fulfill({ status: 503, json: { error: 'Full flow test completed' } })
})
await navigate(page, '전체 흐름')
await page.getByRole('button', { name: '⇉ 전체 실행', exact: true }).click()
await page.getByTestId('design-status').getByText('Full flow test completed', { exact: true }).waitFor()
assert.equal(flowTarget, 2.5)
assert.deepEqual(errors, [])
console.log(JSON.stringify({ comparatorFileRoundtrip: true, vcoFileRoundtrip: true, importPreviewAndUndo: true, rejectedInvalidFile: true, staleResultsHidden: true, staleOptimizerDiscarded: true, successfulOptimizerRetained: true, vcoOptimizerRetained: true, incompleteNotPassing: true, vcoErrorVisible: true, fullFlowUsesCurrentTarget: true, browserErrors: errors }))
await browser.close()

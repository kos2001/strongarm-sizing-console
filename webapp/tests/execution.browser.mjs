import { navigate } from './navigation.mjs'
import assert from 'node:assert/strict'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const baseURL = process.env.CONSOLE_URL ?? 'http://127.0.0.1:8771'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const visibleStatus = () => page.getByTestId('design-status').filter({ visible: true })
let releaseVco, vcoCalls = 0
const vcoStarted = new Promise(resolve => {
  page.route('**/api/vco/simulate', route => {
    vcoCalls++
    releaseVco = () => route.fulfill({ json: { nominal: { oscillates: true, f_osc_ghz: 1.5, power_uw: 20, vpp_v: 1, n_stages: 3, vctrl_v: .6 } } })
    resolve()
  })
})
await page.goto(baseURL)
await page.getByRole('button', { name: '∿ VCO', exact: true }).click()
await navigate(page, '사이징 · 튜닝')
await page.getByRole('button', { name: '▶ VCO 실행 (튜닝 포함)', exact: true }).click()
await vcoStarted
await page.getByRole('button', { name: '⚖ 비교기', exact: true }).click()
const activity = page.getByRole('region', { name: '실행 기록', exact: true })
assert.equal(await activity.locator('[data-state="running"]').count(), 1)
assert.match(await activity.innerText(), /VCO/)
await activity.getByRole('button', { name: '화면 열기', exact: true }).click()
assert.equal(await page.getByRole('button', { name: '시뮬레이션 중…', exact: true }).isDisabled(), true)
assert.equal(vcoCalls, 1)
await releaseVco()
await visibleStatus().getByText('스펙 만족', { exact: true }).waitFor()
await page.getByRole('button', { name: '⚖ 비교기', exact: true }).click()
await page.getByRole('button', { name: '∿ VCO', exact: true }).click()
await visibleStatus().getByText('스펙 만족', { exact: true }).waitFor()
assert.equal(vcoCalls, 1)

// A measured startup failure is a failure even when no numeric metrics exist.
await navigate(page, '사이징 · 튜닝')
await page.route('**/api/vco/simulate', route => route.fulfill({ json: { nominal: { oscillates: false, f_osc_ghz: null, power_uw: null, vpp_v: null, n_stages: 3, vctrl_v: .6 } } }))
await page.getByRole('button', { name: '▶ VCO 실행 (튜닝 포함)', exact: true }).click()
await visibleStatus().getByText('회로 동작 실패', { exact: true }).waitFor()

// Comparator robustness work survives page changes and remains single-flight.
await page.getByRole('button', { name: '⚖ 비교기', exact: true }).click()
await navigate(page, 'WiCkeD 강건성')
let releaseWcd, wcdCalls = 0
const wcdStarted = new Promise(resolve => {
  page.route('**/api/wicked/wcd', route => {
    wcdCalls++
    releaseWcd = () => route.fulfill({ json: { beta_sigma: 4.2, estimated_yield_pct: 99.99, candidates: [], limiting_mechanism: { metric: 'offset' }, predicted_offset_sigma_mv: 1.2, note: 'Retained result' } })
    resolve()
  })
})
await page.getByRole('button', { name: 'β run WCD (24)', exact: true }).click()
await wcdStarted
await navigate(page, '소자 크기')
assert.equal(await page.getByRole('button', { name: '▶ Run SPICE', exact: true }).isDisabled(), true)
await activity.getByRole('button', { name: '화면 열기', exact: true }).click()
assert.equal(await page.getByRole('button', { name: 'sampling… (~30s)', exact: true }).isDisabled(), true)
await releaseWcd()
await page.getByText('4.2σ', { exact: true }).waitFor()
await navigate(page, '소자 크기')
await navigate(page, 'WiCkeD 강건성')
await page.getByText('4.2σ', { exact: true }).waitFor()
assert.equal(wcdCalls, 1)
// Only measured processes belong in the grid; missing cells are not failures.
await page.getByRole('button', { name: '∿ VCO', exact: true }).click()
await navigate(page, 'PVT 코너')
const corners = ['SS', 'TT', 'FF'].flatMap(process => [-40, 125].flatMap(temp => [.9, 1.1].map(v_frac => ({ process, temp, v_frac, vdd: v_frac, f_osc_ghz: 1.5, oscillates: true, power_uw: 20 }))))
let partial = false
await page.route('**/api/vco/pvt', route => route.fulfill({ json: { corners: partial ? corners.slice(1) : corners, base_vdd: 1, f_min_ghz: 1.5, f_max_ghz: 1.5, any_nonosc: false } }))
await page.getByRole('button', { name: '◫ 45코너 실행', exact: true }).click()
const table = page.getByRole('table', { name: 'PVT 코너 측정값' })
await table.waitFor()
assert.equal(await table.locator('tbody tr').count(), 3)
assert(!((await table.innerText()).includes('✗')))
partial = true
await page.getByRole('button', { name: '◫ 45코너 실행', exact: true }).click()
await page.getByText('일부 미측정', { exact: true }).waitFor()
assert((await table.innerText()).includes('—'))
assert(!((await table.innerText()).includes('✗')))
assert.deepEqual(errors, [])
await page.close()

// A missing lazy panel must not remove navigation or the saved design toolbar.
const broken = await browser.newPage()
await broken.route('**/assets/VcoPage-*.js', route => route.abort())
await broken.goto(baseURL)
await broken.getByRole('button', { name: '∿ VCO', exact: true }).click()
await broken.getByRole('alert').getByText('분석 화면을 표시하지 못했습니다.', { exact: false }).waitFor()
await broken.getByRole('button', { name: '⚖ 비교기', exact: true }).click()
await broken.getByLabel('설계 이름', { exact: true }).waitFor()
// The failed, already-visited domain must not make other workspaces fail again.
await broken.getByLabel('M1 / M2 W (µm)', { exact: true }).waitFor()
await browser.close()
console.log(JSON.stringify({ vcoRunSurvivesNavigation: true, vcoResultRetained: true, robustnessRunSurvivesNavigation: true, robustnessResultRetained: true, duplicateRunsBlocked: true, chunkFailureContained: true, missingCornersNotFailures: true, failedStartupNotUnmeasured: true, browserErrors: errors }))

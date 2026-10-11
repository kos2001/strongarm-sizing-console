import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright')
const baseURL = process.env.CONSOLE_URL ?? 'http://127.0.0.1:8771'
const output = process.env.QA_OUTPUT ?? '/tmp/strongarm-interaction-qa'
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    window.qa = { vertices: 0, traceStrokes: 0, draftWrites: 0 }
    const lineTo = Path2D.prototype.lineTo
    Path2D.prototype.lineTo = function (...args) { window.qa.vertices++; return lineTo.apply(this, args) }
    const stroke = CanvasRenderingContext2D.prototype.stroke
    CanvasRenderingContext2D.prototype.stroke = function (...args) {
      if (args[0] instanceof Path2D) window.qa.traceStrokes++
      return stroke.apply(this, args)
    }
    const setItem = Storage.prototype.setItem
    Storage.prototype.setItem = function (key, value) {
      if (key === 'strongarm.design.v1.comparator') window.qa.draftWrites++
      return setItem.call(this, key, value)
    }
  })
  const times = Array.from({ length: 20_001 }, (_, i) => i / 1000)
  const wave = {
    n: times.length, vdd: .7, t_ns: times, clk: times.map(t => t < 4 ? 0 : .7),
    outp: times.map(t => t < 5 ? .7 : .1), outn: times.map(t => t < 5 ? .7 : 0),
    clk_edge_ns: 4, decision_ns: 5,
  }
  wave.outp[8231] = .75 // a narrow peak must survive rendering reduction
  await page.route('**/api/waveform', route => route.fulfill({ json: wave }))
  await page.route('**/api/vco/waveform', route => route.fulfill({ json: {
    vdd: 1, t_ns: times, o1: times.map(t => .5 + .5 * Math.sin(t * 10)),
    o2: times.map(t => .5 - .5 * Math.sin(t * 10)), period_ns: .628, f_osc_ghz: 1.592,
  } }))
  await page.goto(baseURL)
  await page.getByText('이 브라우저에 입력값 자동 저장됨', { exact: true }).waitFor()

  const writes = await page.evaluate(() => window.qa.draftWrites)
  const field = page.getByLabel('M1 / M2 W (µm)', { exact: true })
  await field.fill('')
  await field.pressSequentially('12.345', { delay: 10 })
  await page.getByText('이 브라우저에 입력값 자동 저장됨', { exact: true }).waitFor()
  const coalescedWrites = await page.evaluate(before => window.qa.draftWrites - before, writes)
  assert.equal(coalescedWrites, 1)
  // Reload immediately, before the debounce, to exercise the lifecycle flush.
  await field.fill('17')
  await page.reload()
  assert.equal(await field.inputValue(), '17')

  await page.getByRole('button', { name: '↻ waveform', exact: true }).click()
  const plot = page.getByRole('group', { name: 'Transient waveform: comparator outputs resolving after the clock edge', exact: true })
  await plot.waitFor()
  await page.waitForFunction(() => window.qa.traceStrokes >= 3)
  const cursor = plot.getByLabel('측정 커서', { exact: true })
  await cursor.focus()
  await cursor.press('End')
  await plot.getByText('t = 20.0000 ns', { exact: true }).waitFor()
  const canvas = plot.locator('.waveform-canvas canvas').last()
  const box = await canvas.boundingBox()
  const drawn = await page.evaluate(() => ({ ...window.qa }))
  await page.mouse.move(box.x + 38 + (box.width - 50) / 2, box.y + 100)
  await plot.getByText('t = 10.0000 ns', { exact: true }).waitFor()
  const moved = await page.evaluate(() => ({ ...window.qa }))
  assert.equal(moved.vertices, drawn.vertices, 'cursor movement must not rebuild paths')
  assert.equal(moved.traceStrokes, drawn.traceStrokes, 'cursor movement must not redraw traces')
  assert(drawn.vertices < wave.n * 3 / 2, `${drawn.vertices} vertices should be far below ${wave.n * 3}`)
  await plot.getByRole('button', { name: '파형 확대', exact: true }).click()
  assert(Number(await cursor.getAttribute('min')) > 0)
  assert(Number(await cursor.getAttribute('max')) < wave.n - 1)
  await plot.getByRole('button', { name: '전체 보기', exact: true }).click()
  assert.equal(await cursor.getAttribute('min'), '0')
  assert.equal(await cursor.getAttribute('max'), String(wave.n - 1))
  await plot.getByRole('button', { name: 'clk', exact: true }).click()
  assert.equal(await plot.getByRole('button', { name: 'clk', exact: true }).getAttribute('aria-pressed'), 'false')
  assert(!await plot.locator('.waveform-readout').innerText().then(text => text.includes('clk =')))
  await plot.screenshot({ path: `${output}/comparator.png` })

  await page.keyboard.press('Control+k')
  const dialog = page.getByRole('dialog', { name: '분석 화면으로 이동' })
  const search = dialog.getByRole('searchbox', { name: '분석 검색어' })
  await search.fill('vco 파형')
  await search.press('ArrowDown')
  await page.keyboard.press('Enter')
  await page.waitForURL('**/#vcocircuit')
  await page.getByRole('button', { name: '↻ 파형', exact: true }).click()
  const vcoPlot = page.getByRole('group', { name: 'Ring VCO oscillation waveform', exact: true })
  await vcoPlot.waitFor()
  await vcoPlot.getByLabel('측정 커서').press('End')
  await vcoPlot.getByText('t = 20.0000 ns', { exact: true }).waitFor()
  await page.goBack()
  await field.waitFor()
  assert.equal(await field.inputValue(), '17')
  await page.goForward()
  await vcoPlot.waitFor()
  await page.reload()
  await page.getByRole('button', { name: '↻ 파형', exact: true }).waitFor()
  assert.equal(new URL(page.url()).hash, '#vcocircuit')

  await page.setViewportSize({ width: 390, height: 1000 })
  await page.getByRole('button', { name: /분석 검색|Find analysis/ }).click()
  await search.fill('no-such-analysis')
  await dialog.getByText('일치하는 분석이 없습니다.', { exact: true }).waitFor()
  await search.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  assert.equal(await dialog.isVisible(), false)
  await page.getByRole('button', { name: '↻ 파형', exact: true }).click()
  await vcoPlot.waitFor()
  const mobileBox = await vcoPlot.boundingBox()
  assert(mobileBox.x >= 0 && mobileBox.x + mobileBox.width <= 390)
  await vcoPlot.getByRole('button', { name: '파형 확대', exact: true }).click()
  await vcoPlot.screenshot({ path: `${output}/vco-mobile.png` })
  // Unknown bookmarks fall back to a working editor rather than crashing.
  await page.goto(`${baseURL}/#unknown-analysis`)
  await field.waitFor()
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ keyboardSearch: true, backForwardAndBookmarks: true, waveformControls: true,
    cursorDoesNotRedrawTraces: true, rawTraceVertices: wave.n * 3, drawnVertices: drawn.vertices,
    coalescedWrites, immediateReloadPreservesInputs: true, mobileChartFits: true, browserErrors: errors }))
} finally { await browser.close() }

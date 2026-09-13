import { navigate } from './navigation.mjs'
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const baseURL = process.env.CONSOLE_URL ?? 'http://127.0.0.1:8771';
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage(); const errors=[]; page.on('pageerror',e=>errors.push(e.message));
await page.goto(baseURL);
await page.getByLabel('M1 / M2 W (µm)',{exact:true}).fill('10');
await page.getByLabel('Decision time ≤').fill('350');
await page.reload();
assert.equal(await page.getByLabel('M1 / M2 W (µm)',{exact:true}).inputValue(),'10');
assert.equal(await page.getByLabel('Decision time ≤').inputValue(),'350');
assert.match(await page.locator('.draft-status').innerText(),/이전 입력 복원됨/);
assert.equal(await page.getByRole('heading',{level:1}).innerText(),'설계 편집');
const initial=await page.evaluate(()=>performance.getEntriesByType('resource').map(r=>r.name));
assert(!initial.some(url=>url.includes('VcoPage')||url.includes('/api/waveform')));
const labels=await page.locator('nav button').allTextContents();
for (const label of labels) {
  await page.locator('nav button').filter({hasText:label.trim()}).click();
  await page.locator('.panel-loading').waitFor({state:'hidden'});
  assert.equal(await page.locator('nav [aria-current="page"]').count(),1);
  for (const tab of await page.getByRole('tab').all()) { await tab.click(); await page.locator('.panel-loading').waitFor({state:'hidden'}); }
}
await page.getByRole('button',{name:'∿ VCO',exact:true}).click();
await page.locator('.panel-loading').waitFor({state:'hidden'});

const vlabels=await page.locator('nav button').allTextContents();
for (const label of vlabels) {
  await page.locator('nav button').filter({hasText:label.trim()}).click();
  await page.locator('.panel-loading').waitFor({state:'hidden'});
  for (const tab of await page.getByRole('tab').all()) { await tab.click(); await page.locator('.panel-loading').waitFor({state:'hidden'}); }
}
await navigate(page, '사이징 · 튜닝');
await page.getByLabel('단수 N',{exact:true}).fill('5');
await page.getByRole('button',{name:'⚖ 비교기',exact:true}).click();
await page.getByRole('button',{name:'∿ VCO',exact:true}).click();
await navigate(page, '사이징 · 튜닝');
assert.equal(await page.getByLabel('단수 N',{exact:true}).inputValue(),'5');
await page.reload();
await page.getByRole('button',{name:'∿ VCO',exact:true}).click();
await navigate(page, '사이징 · 튜닝');
assert.equal(await page.getByLabel('단수 N',{exact:true}).inputValue(),'5');
assert.deepEqual(errors,[]);
console.log(JSON.stringify({comparatorWorkspaces:labels.length,vcoWorkspaces:vlabels.length,restoredWidth:10,restoredDecisionTarget:350,restoredVcoStages:5,pageErrors:errors}));
await browser.close();

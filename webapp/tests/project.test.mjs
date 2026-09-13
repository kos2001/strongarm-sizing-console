import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseProject, projectFilename, MAX_PROJECT_BYTES } from '../src/project.ts'
import { analysisKey, comparatorVerdicts } from '../src/analysis.ts'
const devices = keys => Object.fromEntries(keys.map(key=>[key,{w_um:2,l_nm:45,m:2}]))
const comparator = {
  format:'strongarm-design',version:1,domain:'comparator',name:'ADC 비교기',savedAt:'2026-09-13T00:00:00.000Z',
  params:{vdd:.7,cload_ff:15,avt_mv_um:2,n_mc:16,devices:devices(['input','tail','ncc','pcc','pre','prei'])},
  targets:{decision_time_ps:400,power_uw:100,offset_sigma_mv:5,noise_uv_rms:250},
}
const vco = {...comparator,domain:'vco',name:'Ring oscillator',params:{vdd:1,vctrl:.6,n_stages:3,cload_ff:3,topology:'xcplsv',devices:devices(['invp','invn','starvep','starven','xcplp'])},targets:{f_ghz:1.5}}
const parse = value => parseProject(JSON.stringify(value), value.domain)

test('comparator and VCO projects round-trip with advanced backend fields intact', () => {
  for (const project of [comparator,vco]) {
    const extended={...project,params:{...project.params,temp_c:85,parasitic:true,extra:{clock_ps:250}}}
    assert.deepEqual(parse(extended),extended)
  }
})
test('malformed, oversized, future-version and cross-domain files are rejected', () => {
  assert.throws(()=>parseProject('{broken','comparator'),/JSON/)
  assert.throws(()=>parseProject(' '.repeat(MAX_PROJECT_BYTES+1),'comparator'),/1 MiB/)
  assert.throws(()=>parse({...comparator,version:2}),/version/)
  assert.throws(()=>parseProject(JSON.stringify(vco),'comparator'),/VCO/)
  assert.throws(()=>parse({...comparator,name:''}),/name/)
  assert.throws(()=>parse({...comparator,savedAt:'invalid'}),/date/)
})
test('invalid dimensions, specs, models and stage counts cannot reach the editor', () => {
  for (const patch of [{vdd:0},{vdd:null},{cload_ff:-1},{n_mc:1.5},{devices:{}},{model:'unknown'}]) {
    assert.throws(()=>parse({...comparator,params:{...comparator.params,...patch}}))
  }
  for (const stages of [2,4,11,3.5]) assert.throws(()=>parse({...vco,params:{...vco.params,n_stages:stages}}))
  assert.throws(()=>parse({...vco,targets:{f_ghz:-1}}))
  assert.throws(()=>parse({...comparator,targets:{decision_time_ps:400}}))
  const polluted=JSON.stringify(comparator).replace('"vdd":0.7','"__proto__":{"polluted":true},"vdd":0.7')
  assert.throws(()=>parseProject(polluted,'comparator'))
  assert.equal({}.polluted,undefined)
})
test('file names support Korean and cannot inject path separators', () => {
  assert.equal(projectFilename('ADC 비교기'),'ADC-비교기.strongarm.json')
  assert(!projectFilename('../../evil/name').includes('/'))
})
test('result identity ignores object order but includes all simulation and spec inputs', () => {
  assert.equal(analysisKey({vdd:.7,devices:{input:{m:2,w:1}}}),analysisKey({devices:{input:{w:1,m:2}},vdd:.7}))
  assert.notEqual(analysisKey(comparator.params),analysisKey({...comparator.params,vdd:.8}))
  assert.notEqual(analysisKey(comparator.params,{power:100}),analysisKey(comparator.params,{power:50}))
})
test('verdicts use current specs, and missing measurements never pass', () => {
  const result={nominal:{functional:true,decision_time_ps:300,power_uw:80,noise_uv_rms:200},verdicts:{}}
  const current=comparatorVerdicts(result,comparator.targets)
  assert.deepEqual(current,{decision_time_ps:true,power_uw:true,offset_sigma_mv:null,noise_uv_rms:true})
  assert.equal(comparatorVerdicts(result,{power_uw:50}).power_uw,false)
  assert.equal(comparatorVerdicts({...result,nominal:{...result.nominal,functional:false}},{power_uw:100}).power_uw,false)
})

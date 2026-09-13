import { useEffect, useState } from 'react'
import { requestJson } from '../execution'
import type { Lang } from '../i18n'

type Cell = { inst: string; master: string; x: number; y: number; w: number; h: number; orient: string }
type Segment = { layer: string; x1: number; y1: number; x2: number; y2: number }
type Geometry = { die: [number, number, number, number] | null; cells: Cell[]; nets: { name: string; segments: Segment[] }[] }
type Verdict = { passed?: boolean; area_um2?: number | null; power?: { total_w?: number | null }; violations?: string[]; unverified?: string[]; signoff_checks?: { key: string; label: string; count: number | null }[] }
type Candidate = { iteration: number; tag: string; cells: number; nets: number; has_geometry: boolean; pdk?: string; verdict?: Verdict }
type Case = { file: string; design: string; date: string; outcome: string; candidates: Candidate[] }
type Detail = { file: string; design: string; date: string; tag: string; pdk?: string; source: string; layout: Geometry | null; verdict?: Verdict }
const colors: Record<string, string> = { li1: '#a1a7b0', met1: '#e0574a', met2: '#4bbf73', met3: '#e8b339', met4: '#4a90d9', met5: '#c76bd6' }

// Coordinates and signoff checks come directly from the sibling project's recorded
// DEF/LEF output. A reference design is never substituted for the edited analog cell.
export default function PhysicalReference({ lang }: { lang: Lang }) {
  const ko = lang === 'ko'
  const [files, setFiles] = useState<{ file: string; bytes: number }[]>([])
  const [file, setFile] = useState('')
  const [record, setRecord] = useState<Case | null>(null)
  const [selection, setSelection] = useState('')
  const [detail, setDetail] = useState<Detail | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [hidden, setHidden] = useState<string[]>([])
  const [zoom, setZoom] = useState(1)
  useEffect(() => {
    let current = true
    requestJson<{ available: boolean; cases: typeof files }>('/api/physical/cases').then(result => {
      if (!current) return
      setFiles(result.cases)
      if (!result.available) setError(ko ? 'ppa-eda-agent 참조 저장소를 찾을 수 없습니다.' : 'ppa-eda-agent reference store is unavailable.')
    }).catch(e => { if (current) setError(String(e)) })
    return () => { current = false }
  }, [ko])
  useEffect(() => {
    let current = true
    setRecord(null); setDetail(null); setSelection(''); setError('')
    if (!file) { setLoading(false); return }
    setLoading(true)
    requestJson<Case>(`/api/physical/case?file=${encodeURIComponent(file)}`).then(result => {
      if (current) setRecord(result)
    }).catch(e => { if (current) setError(String(e)) }).finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [file])
  useEffect(() => {
    let current = true
    setDetail(null); setHidden([]); setZoom(1)
    if (!selection || !record) { setLoading(false); return }
    const candidate = record.candidates[Number(selection) - 1]
    setLoading(true); setError('')
    requestJson<Detail>(`/api/physical/candidate?file=${encodeURIComponent(record.file)}&iteration=${candidate.iteration}&tag=${encodeURIComponent(candidate.tag)}`).then(result => {
      if (current) setDetail(result)
    }).catch(e => { if (current) setError(String(e)) }).finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [selection, record])
  const layout = detail?.layout
  const layers = [...new Set(layout?.nets.flatMap(net => net.segments.map(segment => segment.layer)) ?? [])].sort()
  const die = layout?.die
  const checks = detail?.verdict?.signoff_checks ?? []
  return <section className="physical-reference" aria-label={ko ? '실제 배치·배선 기록' : 'Recorded placement and routing'}>
    <p className="analysis-notice">{ko ? 'ppa-eda-agent의 실제 실행 기록입니다. 선택한 참조 설계의 결과이며 현재 편집 중인 비교기/VCO의 레이아웃은 아닙니다.' : 'Actual ppa-eda-agent run records for the selected reference design, separate from the comparator/VCO being edited.'}</p>
    <div className="physical-selectors">
      <label>{ko ? '실행 기록' : 'Run record'}<select value={file} onChange={e => setFile(e.target.value)}><option value="">{ko ? '실행 파일 선택' : 'Select a run file'}</option>{files.map(item => <option key={item.file} value={item.file}>{item.file}</option>)}</select></label>
      <label>{ko ? '후보 · 반복' : 'Candidate · iteration'}<select value={selection} disabled={!record} onChange={e => setSelection(e.target.value)}><option value="">{ko ? '후보 선택' : 'Select a candidate'}</option>{record?.candidates.map((candidate, index) => <option key={index} value={index + 1}>{candidate.iteration + 1} / {candidate.tag} · {candidate.cells} cells, {candidate.nets} nets</option>)}</select></label>
    </div>
    {error && <p role="alert">{error}</p>}
    {loading && <p role="status">{ko ? '실행 데이터 읽는 중…' : 'Reading recorded artifacts…'}</p>}
    {record && <div className="physical-provenance">{record.design} · {record.date} · {record.outcome}</div>}
    {detail && <>
      <div className="physical-provenance">{detail.source} · {detail.pdk ?? 'PDK unrecorded'} · {detail.tag}</div>
      {die && layout && (layout.cells.length > 0 || layout.nets.length > 0) ? <>
        <div className="eda-command-row"><button onClick={() => setZoom(z => Math.min(8, z * 1.5))}>＋</button><button onClick={() => setZoom(z => Math.max(1, z / 1.5))}>−</button><button onClick={() => setZoom(1)}>{ko ? '전체 보기' : 'Fit'}</button><span>{layout.cells.length} cells · {layout.nets.length} nets · {(zoom * 100).toFixed(0)}%</span></div>
        <div className="physical-canvas">
          <svg viewBox={`${die[0]} 0 ${die[2] - die[0]} ${die[3] - die[1]}`} style={{ width: `${zoom * 100}%`, minWidth: `${zoom * 100}%`, height: `${zoom * 100}%` }} role="img" aria-label="Recorded DEF placement and routing">
            <rect x={die[0]} y={0} width={die[2] - die[0]} height={die[3] - die[1]} fill="#080c13" stroke="#8296b0" strokeWidth={.1} />
            {layout.cells.map(cell => <rect key={cell.inst} x={cell.x} y={die[3] - cell.y - cell.h} width={cell.w} height={cell.h} fill="#24354d" stroke="#8499b0" strokeWidth={.04}><title>{`${cell.inst} / ${cell.master} / ${cell.orient}\n${cell.x}, ${cell.y} µm`}</title></rect>)}
            {layout.nets.map(net => net.segments.filter(segment => !hidden.includes(segment.layer)).map((segment, i) => <line key={`${net.name}-${i}`} x1={segment.x1} y1={die[3] - segment.y1} x2={segment.x2} y2={die[3] - segment.y2} stroke={colors[segment.layer] ?? '#c0a8dd'} strokeWidth={Math.max(die[2] - die[0], die[3] - die[1]) * .0015}><title>{net.name} / {segment.layer}</title></line>))}
          </svg>
        </div>
        <div className="physical-layers">{layers.map(layer => <label key={layer} style={{ color: colors[layer] ?? 'var(--text)' }}><input type="checkbox" checked={!hidden.includes(layer)} onChange={() => setHidden(old => old.includes(layer) ? old.filter(value => value !== layer) : [...old, layer])} />{layer}</label>)}</div>
      </> : <p className="analysis-notice">{ko ? '이 후보에는 저장된 셀·배선 좌표가 없습니다. 다른 후보를 선택하세요.' : 'No cell or routing geometry was recorded for this candidate. Select another candidate.'}</p>}
      <div className="physical-provenance">{ko ? '기록된 면적' : 'Recorded area'}: {detail.verdict?.area_um2 ?? '—'} µm² · {ko ? '총 전력' : 'Total power'}: {detail.verdict?.power?.total_w == null ? '—' : (detail.verdict.power.total_w * 1e6).toFixed(3)} µW</div>
      <table className="physical-checks"><caption>{ko ? '실행별 검증 결과' : 'Recorded verification checks'}</caption><thead><tr><th>{ko ? '검사' : 'Check'}</th><th>{ko ? '위반 수' : 'Violations'}</th><th>{ko ? '상태' : 'State'}</th></tr></thead><tbody>{checks.map(check => <tr key={check.key}><td>{check.label}</td><td>{check.count ?? '—'}</td><td style={{ color: check.count == null ? 'var(--muted)' : check.count === 0 ? 'var(--good)' : 'var(--bad)' }}>{check.count == null ? (ko ? '미검증' : 'Unverified') : check.count === 0 ? (ko ? '통과' : 'Pass') : (ko ? '위반' : 'Violation')}</td></tr>)}</tbody></table>
      {!checks.length && <p>{ko ? '이 기록에는 개별 검사 결과가 없습니다.' : 'This record has no per-check verification results.'}</p>}
      {detail.verdict?.violations?.map((value, i) => <p key={i} style={{ color: 'var(--bad)' }}>{value}</p>)}
      {detail.verdict?.unverified?.map((value, i) => <p key={i} style={{ color: 'var(--warn)' }}>{value}</p>)}
    </>}
  </section>
}

import { useRef, useState } from 'react'
import type { Lang } from '../i18n'
import type { Params, VcoParams } from '../types'
import { MAX_PROJECT_BYTES, parseProject, projectFilename, type DesignDomain, type DesignProject } from '../project'
import { useDraft } from '../useDraft'
import DraftStatus from './DraftStatus'

interface Props {
  domain: DesignDomain
  lang: Lang
  params: Params | VcoParams
  targets: Record<string, number>
  busy: boolean
  status: { savedAt: number | null; restored: boolean; saveError: boolean }
  onImport: (project: DesignProject) => void
}

export default function ProjectToolbar({ domain, lang, params, targets, busy, status, onImport }: Props) {
  const ko = lang === 'ko'
  const [name, setName] = useDraft(`${domain}-project-name`, domain === 'vco' ? 'VCO design' : 'Comparator design')
  const [pending, setPending] = useState<DesignProject | null>(null)
  const [previous, setPrevious] = useState<DesignProject | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const snapshot = (): DesignProject => ({ format: 'strongarm-design', version: 1, domain, name, params, targets, savedAt: new Date().toISOString() })
  const save = () => {
    try {
      const text = JSON.stringify(snapshot(), null, 2)
      parseProject(text, domain)
      const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = projectFilename(name)
      anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setError(null)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  const open = async (file?: File) => {
    setPending(null)
    setError(null)
    if (!file) return
    try {
      if (file.size > MAX_PROJECT_BYTES) throw new Error('Project file exceeds 1 MiB.')
      setPending(parseProject(await file.text(), domain))
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  return <section className="project-toolbar" aria-label={ko ? '설계 파일' : 'Design files'}>
    <div className="project-controls">
      <label className="project-name"><span>{ko ? '설계 이름' : 'Design name'}</span>
        <input value={name} maxLength={120} onChange={e => setName(e.target.value)} />
      </label>
      <div className="project-actions">
        <button onClick={save}>{ko ? '파일 저장' : 'Save file'}</button>
        <button disabled={busy} onClick={() => fileInput.current?.click()}>{ko ? '파일 열기' : 'Open file'}</button>
        <input ref={fileInput} type="file" accept=".json,application/json" aria-label={ko ? '설계 파일 선택' : 'Choose design file'} hidden
          onChange={e => { void open(e.target.files?.[0]); e.target.value = '' }} />
      </div>
    </div>
    <DraftStatus lang={lang} status={status} />
    {error && <div className="project-message" role="alert">{ko ? '파일을 처리하지 못했습니다: ' : 'Unable to process file: '}{error}</div>}
    {pending && <div className="project-preview" role="region" aria-label={ko ? '가져오기 미리보기' : 'Import preview'}>
      <strong>{pending.name}</strong>
      <span>{pending.domain === 'vco' ? 'VCO' : 'Comparator'} · {pending.params.model ?? 'ptm'} · {pending.params.vdd} V</span>
      <p>{ko ? '현재 입력을 이 파일의 소자 크기와 스펙으로 바꿉니다. 측정 결과는 다시 실행해야 합니다.' : 'Replace current device dimensions and specifications with this file. Run again to produce measurements.'}</p>
      <div className="project-actions">
        <button disabled={busy} onClick={() => { setPrevious(snapshot()); onImport(pending); setName(pending.name); setPending(null) }}>{ko ? '설계 불러오기' : 'Load design'}</button>
        <button onClick={() => setPending(null)}>{ko ? '취소' : 'Cancel'}</button>
      </div>
    </div>}
    {previous && !pending && <div className="project-message project-actions">
      <span>{ko ? '설계를 불러왔습니다.' : 'Design loaded.'}</span>
      <button disabled={busy} onClick={() => { onImport(previous); setName(previous.name); setPrevious(null) }}>{ko ? '이전 설계 복원' : 'Restore previous design'}</button>
    </div>}
  </section>
}

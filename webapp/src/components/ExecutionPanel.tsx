import { useEffect, useState, useSyncExternalStore } from 'react'
import { getExecutions, subscribeExecutions } from '../execution'
import type { Lang } from '../i18n'

export function ElapsedTime({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return <span className="tnum">{Math.max(0, (now - since) / 1000).toFixed(0)}</span>
}

export default function ExecutionPanel({ lang, onOpen }: { lang: Lang; onOpen: (page: string) => void }) {
  const records = useSyncExternalStore(subscribeExecutions, getExecutions)
  const [expanded, setExpanded] = useState(false)
  const active = records.filter(record => record.state === 'running')
  const ko = lang === 'ko'
  useEffect(() => {
    if (!active.length) return
    const protectRun = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', protectRun)
    return () => window.removeEventListener('beforeunload', protectRun)
  }, [active.length])
  const shown = expanded ? records : active.length ? active : records.slice(0, 1)
  return <section className="execution-panel" aria-label={ko ? '실행 기록' : 'Execution history'}>
    <button className="execution-summary" onClick={() => setExpanded(value => !value)} aria-expanded={expanded} aria-controls="execution-list">
      <span>{ko ? '실행 기록' : 'Execution history'} <span className="tnum">{active.length ? (ko ? `· ${active.length}개 실행 중` : `· ${active.length} running`) : `· ${records.length}`}</span></span>
      <span aria-hidden="true">{expanded ? '−' : '+'}</span>
    </button>
    <div id="execution-list">
      {!records.length && <div className="eda-output-empty">{ko ? '준비됨 · 분석을 실행하면 진행 상태와 메시지가 표시됩니다.' : 'Ready · Run an analysis to see progress and messages.'}</div>}
      {shown.map(record => <div key={record.id} className="execution-row" data-state={record.state}>
        <span className="execution-domain">{record.domain === 'vco' ? 'VCO' : (ko ? '비교기' : 'Comparator')}</span>
        <span className="execution-label">{record.label[lang]}
          {record.error && <span className="execution-error">{record.error}</span>}
        </span>
        <span className="execution-outcome">{record.state === 'running' ? (ko ? '실행 중' : 'Running') : record.state === 'failed' ? (ko ? '실행 오류' : 'Failed') : (ko ? '분석 완료' : 'Completed')}</span>
        <span className="mono execution-time">{record.state === 'running' ? <ElapsedTime since={record.startedAt} /> : ((record.finishedAt! - record.startedAt) / 1000).toFixed(1)}s</span>
        <button className="execution-open" onClick={() => onOpen(record.page)}>{ko ? '화면 열기' : 'Open workspace'}</button>
      </div>)}
    </div>
  </section>
}

import { lazy, Suspense, useState } from 'react'
import type { ReactNode } from 'react'
import type { Lang } from '../i18n'
const PhysicalReference = lazy(() => import('./PhysicalReference'))
export default function LayoutWorkspace({ lang, children }: { lang: Lang; children: ReactNode }) {
  const [source, setSource] = useState('current')
  return <div className="layout-workspace">
    <div className="eda-analysis-tabs" role="group" aria-label={lang === 'ko' ? '레이아웃 소스' : 'Layout source'}>
      <button aria-pressed={source === 'current'} onClick={() => setSource('current')}>{lang === 'ko' ? '현재 설계 · GDS 초안' : 'Current design · GDS draft'}</button>
      <button aria-pressed={source === 'reference'} onClick={() => setSource('reference')}>{lang === 'ko' ? 'ppa-eda-agent · 실제 P&R' : 'ppa-eda-agent · recorded P&R'}</button>
    </div>
    {source === 'current' ? <>{children}</> : <Suspense fallback={<p role="status">Loading physical artifacts…</p>}><PhysicalReference lang={lang} /></Suspense>}
  </div>
}

import { NAV_LABELS, t, type Lang } from '../i18n'
import type { Page, Workspace } from '../navigation'

export default function WorkspaceTabs({ workspace, page, lang, onNavigate }: {
  workspace: Workspace; page: Page; lang: Lang; onNavigate: (page: Page) => void
}) {
  if (workspace.id === 'design') return null
  return (
    <div className="eda-analysis-tabs" role="tablist" aria-label={lang === 'ko' ? '세부 분석' : 'Analysis views'}>
      {workspace.pages.map(id => <button key={id} role="tab" aria-selected={page === id} tabIndex={page === id ? 0 : -1}
        onKeyDown={event => {
          const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
          if (!keys.includes(event.key)) return
          event.preventDefault()
          const i = workspace.pages.indexOf(page)
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? workspace.pages.length - 1 : (i + (event.key === 'ArrowRight' ? 1 : -1) + workspace.pages.length) % workspace.pages.length
          onNavigate(workspace.pages[next])
          ;(event.currentTarget.parentElement?.children[next] as HTMLButtonElement)?.focus()
        }} onClick={() => onNavigate(id)}>{t(lang, NAV_LABELS[id])}</button>)}
    </div>
  )
}

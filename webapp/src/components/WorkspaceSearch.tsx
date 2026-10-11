import { useEffect, useId, useRef, useState } from 'react'
import type { Lang } from '../i18n'
import { t } from '../i18n'

import type { Page, SearchDestination } from '../navigation'

export default function WorkspaceSearch({ destinations, lang, onNavigate }: {
  destinations: SearchDestination[]; lang: Lang; onNavigate: (id: Page) => void
}) {
  const ko = lang === 'ko'
  const id = useId()
  const dialog = useRef<HTMLDialogElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [query, setQuery] = useState('')
  const open = () => {
    setQuery('')
    dialog.current?.showModal()
    input.current?.focus()
  }
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        if (dialog.current?.open) dialog.current.close()
        else { setQuery(''); dialog.current?.showModal(); input.current?.focus() }
      }
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  }, [])
  const terms = query.trim().toLowerCase().split(/\s+/)
  const matches = destinations.filter(item => {
    const text = [item.id, item.label.ko, item.label.en, item.group.ko, item.group.en, item.domain.ko, item.domain.en].join(' ').toLowerCase()
    return terms.every(term => text.includes(term))
  })
  return <>
    <button ref={trigger} className="workspace-search-trigger" onClick={open} aria-haspopup="dialog" aria-keyshortcuts="Meta+K Control+K">
      <span>⌕ {ko ? '분석 검색' : 'Find analysis'}</span><kbd>⌘ / Ctrl K</kbd>
    </button>
    <dialog ref={dialog} className="workspace-search-dialog" aria-labelledby={id} onClose={() => trigger.current?.focus()}
      onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); dialog.current?.close() } }}
      onClick={event => { if (event.target === event.currentTarget) dialog.current?.close() }}>
      <div className="workspace-search-header">
        <h2 id={id}>{ko ? '분석 화면으로 이동' : 'Go to an analysis'}</h2>
        <button onClick={() => dialog.current?.close()} aria-label={ko ? '검색 닫기' : 'Close search'}>×</button>
      </div>
      <input ref={input} type="search" value={query} aria-label={ko ? '분석 검색어' : 'Search analyses'}
        placeholder={ko ? '파형, 최적화, VCO…' : 'Waveform, optimization, VCO…'}
        onChange={event => setQuery(event.target.value)} onKeyDown={event => {
          if (event.key === 'ArrowDown') { event.preventDefault(); dialog.current?.querySelector<HTMLButtonElement>('.workspace-search-result')?.focus() }
          if (event.key === 'Enter' && matches[0]) { event.preventDefault(); onNavigate(matches[0].id); dialog.current?.close() }
        }} />
      <div className="workspace-search-results" aria-label={ko ? '검색 결과' : 'Search results'}>
        {matches.map((item, i) => <button key={item.id} className="workspace-search-result" onClick={() => { onNavigate(item.id); dialog.current?.close() }}
          onKeyDown={event => {
            if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
            event.preventDefault()
            if (event.key === 'ArrowUp' && i === 0) { input.current?.focus(); return }
            const next = event.key === 'Home' ? 0 : event.key === 'End' ? matches.length - 1 : (i + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length
            dialog.current?.querySelectorAll<HTMLButtonElement>('.workspace-search-result')[next]?.focus()
          }}>
          <span>{t(lang, item.label)}</span><small>{t(lang, item.domain)} · {t(lang, item.group)}</small>
        </button>)}
        {!matches.length && <p role="status">{ko ? '일치하는 분석이 없습니다.' : 'No matching analyses.'}</p>}
      </div>
      <p className="workspace-search-hint">{ko ? '↑ ↓ 선택 · Enter 이동 · Esc 닫기' : '↑ ↓ select · Enter open · Esc close'}</p>
    </dialog>
  </>
}

import { t, UI, type Lang } from '../i18n'
import { DOMAIN_HOME, NAV_COMPARATOR, NAV_VCO, domainOf, type Page } from '../navigation'

interface Props {
  page: Page
  lang: Lang
  theme: 'dark' | 'light'
  apiUp: boolean | null
  reportAvailable: boolean
  mobileNavOpen: boolean
  onNavigate: (page: Page) => void
  onMobileNavChange: (open: boolean) => void
  onLangChange: (lang: Lang) => void
  onThemeChange: (theme: 'dark' | 'light') => void
  onReport: () => void
}

export default function WorkspaceSidebar({ page, lang, theme, apiUp, reportAvailable, mobileNavOpen,
  onNavigate, onMobileNavChange, onLangChange, onThemeChange, onReport }: Props) {
  const domain = domainOf(page)
  const navList = domain === 'vco' ? NAV_VCO : NAV_COMPARATOR
  const workspace = navList.find(item => item.pages.includes(page))!
  return (
    <aside data-menu-open={mobileNavOpen} onKeyDown={e => { if (e.key === 'Escape') { onMobileNavChange(false); document.querySelector<HTMLButtonElement>('.mobile-nav-toggle')?.focus() } }} className="app-sidebar shrink-0 sticky top-0 self-start h-screen flex flex-col" style={{ borderRight: '1px solid var(--line-soft)', background: 'var(--surface-2)' }}>
      <div className="px-4 py-4 flex items-center gap-2.5" style={{ borderBottom: '1px solid var(--line-soft)' }}>
        <div className="relative w-8 h-8 rounded-lg overflow-hidden shrink-0" style={{ background: 'var(--surface)', border: '1px solid var(--line)' }} aria-hidden>
          <div className="absolute top-1/2 left-0 w-1/3 h-[2px]" style={{ background: 'var(--si)', boxShadow: '0 0 8px var(--si)', animation: 'sweep 2.2s linear infinite' }} />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold leading-tight" style={{ color: 'var(--text)' }}>StrongARM</div>
          <div className="mono text-[10px]" style={{ color: 'var(--faint)' }}>{t(lang, UI.appSub)}</div>
        </div>
      </div>
      <button className="mobile-nav-toggle" aria-expanded={mobileNavOpen} aria-controls="workspace-navigation"
        onClick={() => onMobileNavChange(!mobileNavOpen)}>{mobileNavOpen ? (lang === 'ko' ? '메뉴 닫기' : 'Close menu') : (lang === 'ko' ? '분석 메뉴' : 'Analysis menu')}</button>
      {/* domain switch — Comparator vs VCO are two separate worlds */}
      <div className="grid grid-cols-2 gap-1.5 p-2" style={{ borderBottom: '1px solid var(--line-soft)' }}>
        {([['comparator', '⚖', 'var(--si)', UI.domainComparator], ['vco', '∿', 'var(--ag)', UI.domainVco]] as const).map(([d, glyph, col, label]) => {
          const on = domain === d
          return (
            <button key={d} data-domain-choice={d} aria-pressed={on} onClick={() => { onNavigate(DOMAIN_HOME[d]); onMobileNavChange(false) }}
              className="flex flex-col items-center gap-0.5 py-2 rounded-lg transition-colors"
              style={{ background: on ? `color-mix(in srgb, ${col} 16%, transparent)` : 'var(--surface)', border: `1px solid ${on ? col : 'var(--line)'}` }}>
              <span className="text-base" style={{ color: on ? col : 'var(--faint)' }}>{glyph}</span>
              <span className="mono text-[10px] tracking-wide" style={{ color: on ? 'var(--text)' : 'var(--muted)' }}>{t(lang, label)}</span>
            </button>
          )
        })}
      </div>
      <nav id="workspace-navigation" aria-label={lang === 'ko' ? '분석 화면' : 'Analysis pages'} className="sidebar-nav flex flex-col p-2 overflow-y-auto">
        <div className="eda-tree-heading">{lang === 'ko' ? '설계 탐색기' : 'Design explorer'}</div>
        <div className="eda-cell-name">▾ {domain === 'vco' ? 'ring_vco' : 'strongarm'} <span>schematic</span></div>
        {navList.map(item => <button key={item.id} data-workspace={item.id} aria-current={workspace.id === item.id ? 'page' : undefined}
          className="eda-tree-item" onClick={() => { onNavigate(item.pages[0]); onMobileNavChange(false) }}>
          <span>{item.glyph}</span>{t(lang, item.label)}
        </button>)}
      </nav>
      <div className="app-sidebar-footer mt-auto p-3 flex flex-col gap-2" style={{ borderTop: '1px solid var(--line-soft)' }}>
        <div className="mono text-[11px] flex items-center gap-2" style={{ color: 'var(--muted)' }}>
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: apiUp === null ? 'var(--faint)' : apiUp ? 'var(--good)' : 'var(--bad)' }} />
          {apiUp === null ? t(lang, UI.connecting) : apiUp ? t(lang, UI.backendLive) : t(lang, UI.backendOff)}
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => onLangChange(lang === 'ko' ? 'en' : 'ko')} className="mono text-xs px-3 py-1.5 rounded-full" style={{ color: 'var(--ag)', border: '1px solid color-mix(in srgb, var(--ag) 40%, var(--line))' }} title="한국어 / English">🌐 {lang === 'ko' ? 'EN' : '한'}</button>
          <button onClick={() => onThemeChange(theme === 'dark' ? 'light' : 'dark')} className="mono text-xs px-3 py-1.5 rounded-full" style={{ color: 'var(--muted)', border: '1px solid var(--line)' }}>◐ {t(lang, UI.theme)}</button>
          <button onClick={onReport} disabled={!reportAvailable} className="mono text-xs px-3 py-1.5 rounded-full disabled:opacity-40" style={{ color: 'var(--si)', border: '1px solid color-mix(in srgb, var(--si) 40%, var(--line))' }} title="Download a Markdown report of the current design + results">⤓ {t(lang, UI.report)}</button>
        </div>
      </div>
    </aside>
  )
}

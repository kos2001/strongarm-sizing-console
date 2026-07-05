import { useState } from 'react'
import { HELP, t, UI, type Lang } from '../i18n'

// Beginner-friendly explanation card shown at the top of every page: a plain-
// language "what is this" + "how to read it", in the selected language.
// Collapsible so experienced users can hide it (state per page id).
export default function PageHelp({ page, lang }: { page: string; lang: Lang }) {
  const [open, setOpen] = useState(true)
  const h = HELP[page]
  if (!h) return null
  return (
    <div className="rounded-2xl mb-5" style={{ background: 'color-mix(in srgb, var(--ag) 8%, var(--surface))', border: '1px solid color-mix(in srgb, var(--ag) 30%, var(--line))' }}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left"
        aria-expanded={open}
      >
        <span aria-hidden style={{ fontSize: 15 }}>💡</span>
        <span className="mono text-[11px] uppercase tracking-[0.14em]" style={{ color: 'var(--ag)' }}>{t(lang, UI.whatIsThis)}</span>
        <span className="mono text-[11px] ml-auto" style={{ color: 'var(--faint)' }}>{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 flex flex-col gap-2">
          <p className="text-sm leading-relaxed" style={{ color: 'var(--text)' }}>{t(lang, h.what)}</p>
          <p className="text-sm leading-relaxed" style={{ color: 'var(--muted)' }}>
            <span className="mono text-[11px] uppercase tracking-[0.12em] mr-1.5" style={{ color: 'var(--faint)' }}>{t(lang, UI.howToRead)}:</span>
            {t(lang, h.read)}
          </p>
        </div>
      )}
    </div>
  )
}

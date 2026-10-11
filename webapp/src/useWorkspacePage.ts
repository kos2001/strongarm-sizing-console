import { useCallback, useEffect, useState } from 'react'

/** Keep leaf views bookmarkable without reloading or interrupting running work. */
export function useWorkspacePage<P extends string>(pages: readonly P[], home: P) {
  const read = useCallback(() => {
    const value = window.location.hash.slice(1)
    return pages.find(page => page === value) ?? home
  }, [pages, home])
  const [page, update] = useState<P>(read)
  useEffect(() => {
    const sync = () => update(read())
    window.addEventListener('popstate', sync)
    window.addEventListener('hashchange', sync)
    return () => { window.removeEventListener('popstate', sync); window.removeEventListener('hashchange', sync) }
  }, [read])
  const navigate = useCallback((next: P) => {
    if (!pages.includes(next)) return
    if (window.location.hash !== `#${next}`) window.history.pushState(null, '', `#${next}`)
    update(next)
  }, [pages])
  return [page, navigate] as const
}

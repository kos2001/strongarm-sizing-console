import { useEffect, useMemo, useState } from 'react'
import { decodeDraft, matchesInputs } from './draft'
import { createAutosave } from './autosave'

export function useDraft<T>(key: string, defaults: T) {
  const storageKey = `strongarm.design.v1.${key}`
  const [initial] = useState(() => {
    try { return decodeDraft(localStorage.getItem(storageKey), matchesInputs(defaults)) }
    catch { return null }
  })
  const [value, setValue] = useState<T>(initial?.value ?? defaults)
  const [saved, setSaved] = useState<{ value: T | undefined; savedAt: number | null }>({ value: initial?.value, savedAt: initial?.savedAt ?? null })
  const [saveError, setSaveError] = useState(false)
  const writer = useMemo(() => createAutosave<T>(next => {
    try {
      const timestamp = Date.now()
      localStorage.setItem(storageKey, JSON.stringify({ version: 1, value: next, savedAt: timestamp }))
      setSaved({ value: next, savedAt: timestamp })
      setSaveError(false)
    } catch { setSaveError(true) }
  }), [storageKey])
  useEffect(() => { writer.schedule(value) }, [writer, value])
  useEffect(() => {
    const flushWhenHidden = () => { if (document.visibilityState === 'hidden') writer.flush() }
    window.addEventListener('pagehide', writer.flush)
    document.addEventListener('visibilitychange', flushWhenHidden)
    return () => {
      window.removeEventListener('pagehide', writer.flush)
      document.removeEventListener('visibilitychange', flushWhenHidden)
      writer.flush()
    }
  }, [writer])
  return [value, setValue, { restored: initial !== null, savedAt: saved.savedAt, saving: saved.value !== value, saveError }] as const
}

import { useEffect, useState } from 'react'
import { decodeDraft, matchesInputs } from './draft'

export function useDraft<T>(key: string, defaults: T) {
  const storageKey = `strongarm.design.v1.${key}`
  const [initial] = useState(() => {
    try { return decodeDraft(localStorage.getItem(storageKey), matchesInputs(defaults)) }
    catch { return null }
  })
  const [value, setValue] = useState<T>(initial?.value ?? defaults)
  const [savedAt, setSavedAt] = useState<number | null>(initial?.savedAt ?? null)
  const [saveError, setSaveError] = useState(false)
  useEffect(() => {
    try {
      const timestamp = Date.now()
      localStorage.setItem(storageKey, JSON.stringify({ version: 1, value, savedAt: timestamp }))
      setSavedAt(timestamp)
      setSaveError(false)
    } catch { setSaveError(true) }
  }, [storageKey, value])
  return [value, setValue, { restored: initial !== null, savedAt, saveError }] as const
}

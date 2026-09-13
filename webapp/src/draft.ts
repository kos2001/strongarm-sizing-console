// Versioned local design inputs. Measurement results are deliberately not restored.
export interface Draft<T> { version: 1; value: T; savedAt: number }
export function decodeDraft<T>(raw: string | null, validate: (value: unknown) => value is T): Draft<T> | null {
  if (!raw) return null
  try {
    const draft = JSON.parse(raw)
    return draft?.version === 1 && Number.isFinite(draft.savedAt) && validate(draft.value) ? draft : null
  } catch { return null }
}

/** Check required input fields and reject non-finite numbers in optional fields. */
export function matchesInputs<T>(defaults: T): (value: unknown) => value is T {
  const finite = (v: unknown): boolean => typeof v === 'number' ? Number.isFinite(v)
    : v !== null && typeof v === 'object' ? Object.values(v).every(finite) : true
  const shape = (v: unknown, sample: unknown): boolean => {
    if (sample === null) return v === null
    if (typeof sample !== 'object') return typeof v === typeof sample
    if (v === null || typeof v !== 'object' || Array.isArray(v)) return false
    return Object.entries(sample).every(([key, field]) => key in v && shape((v as Record<string, unknown>)[key], field))
  }
  return (value): value is T => shape(value, defaults) && finite(value)
}

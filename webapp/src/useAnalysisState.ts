import { useCallback, useRef, useState, type SetStateAction } from 'react'

/** One result, bound to its submitted inputs. Old async closures cannot replace
 * a newer design's result. Optimizers may explicitly bind to their final sizing. */
export function useAnalysisState<T>(scope: string) {
  const active = useRef(scope)
  active.current = scope
  const [entry, setEntry] = useState<{ scope: string; value: T | null }>({ scope, value: null })
  const setValue = useCallback((action: SetStateAction<T | null>, finalScope?: string) => {
    if (finalScope === undefined && active.current !== scope) return
    const destination = finalScope ?? scope
    setEntry(previous => ({
      scope: destination,
      value: typeof action === 'function'
        ? (action as (value: T | null) => T | null)(previous.scope === destination ? previous.value : null)
        : action,
    }))
  }, [scope])
  const isCurrent = useCallback((expected = scope) => active.current === expected, [scope])
  return [entry.scope === scope ? entry.value : null, setValue,
    entry.scope !== scope && entry.value !== null, isCurrent] as const
}

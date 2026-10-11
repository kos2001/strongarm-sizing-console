/** One pending write per draft, with an explicit synchronous lifecycle flush. */
export function createAutosave<T>(write: (value: T) => void, delay = 250) {
  let pending: { value: T } | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  const flush = () => {
    clearTimeout(timer)
    timer = undefined
    if (!pending) return
    const { value } = pending
    pending = null
    write(value)
  }
  return {
    schedule(value: T) {
      pending = { value }
      clearTimeout(timer)
      timer = setTimeout(flush, delay)
    },
    flush,
  }
}

interface Lifecycle {
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
}

/** Share lifecycle handling while each analysis owns its inputs and result update. */
export async function runAnalysisRequest(work: () => Promise<void>, { setLoading, setError }: Lifecycle) {
  setLoading(true)
  setError(null)
  try {
    await work()
  } catch (error) {
    setError(error instanceof Error ? error.message : String(error))
  } finally {
    setLoading(false)
  }
}

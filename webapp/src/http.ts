/** Decode API failures before they can be mistaken for measurement results. */
export async function readJson<T>(response: Response): Promise<T> {
  let data: unknown
  try {
    data = await response.json()
  } catch {
    throw new Error(`Invalid server response (HTTP ${response.status}).`)
  }
  const error = data && typeof data === 'object' && 'error' in data ? data.error : null
  if (!response.ok || error) {
    throw new Error(typeof error === 'string' ? error : `Request failed (HTTP ${response.status}).`)
  }
  return data as T
}

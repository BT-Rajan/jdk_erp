import { useCallback, useRef } from 'react'

/** One reference per submission, for server-side duplicate protection:
 * `get()` creates it on the first attempt and returns the same value on
 * every retry (after an error or a timeout), so the server can recognise
 * a repeat and return the record it already made; `reset()` after a
 * success (or when the form switches to another record) starts a new
 * submission. */
export function useSubmissionReference() {
  const ref = useRef<string | null>(null)
  const get = useCallback(() => {
    if (ref.current === null) {
      ref.current =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    }
    return ref.current
  }, [])
  const reset = useCallback(() => {
    ref.current = null
  }, [])
  return { get, reset }
}

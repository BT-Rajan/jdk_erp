import { useState } from 'react'

function isEmptyValue(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return true
  if (Array.isArray(value)) return value.length === 0
  return false
}

/** The one shared way a module owns its filter state -- values, setting
 * one, clearing one back to its default, clearing all, and a count of
 * how many are actually active (non-empty and different from the
 * default). Without this, "apply/clear" and "preserve filter state"
 * would each get reinvented per module the same way an unowned form
 * system would. */
export function useFilters<F extends Record<string, unknown>>(initial: F) {
  const [values, setValues] = useState<F>(initial)

  function setValue<K extends keyof F>(key: K, value: F[K]) {
    setValues((previous) => ({ ...previous, [key]: value }))
  }

  function clearOne(key: keyof F) {
    setValues((previous) => ({ ...previous, [key]: initial[key] }))
  }

  function clear() {
    setValues(initial)
  }

  const activeCount = (Object.keys(values) as Array<keyof F>).filter((key) => {
    const current = values[key]
    return !isEmptyValue(current) && current !== initial[key]
  }).length

  return { values, setValue, clearOne, clear, activeCount }
}

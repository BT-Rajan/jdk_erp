import { useEffect, useState } from 'react'

/** The one reusable debounce primitive for a server-backed search box
 * (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md's list-contract
 * follow-up) -- pair with the existing TextField (a `leadingIcon` and a
 * `trailingSlot` clear button already cover the "standard search
 * input" shape) rather than a bespoke SearchField component; the only
 * genuinely new primitive a search box needed was this debounce, not a
 * new field type alongside the ten already documented in
 * docs/modules/common_ui_components.md.
 *
 * Returns `value` unchanged after `delayMs` of no further changes --
 * the caller keeps its own immediate input state for a responsive
 * field, and feeds the *debounced* value into whatever triggers the
 * actual server request (e.g. useServerTable's `filters`). */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}

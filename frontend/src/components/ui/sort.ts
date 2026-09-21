export interface SortState {
  field: string
  direction: 'asc' | 'desc'
}

/** Explicit {field, direction} instead of jdk_clean's bare `-field`
 * sigil-prefixed string -- still simple, but no string-parsing needed at
 * each consumer. Clicking the same field cycles asc -> desc -> unsorted;
 * clicking a different field starts it at asc. */
export function toggleSort(current: SortState | null, field: string): SortState | null {
  if (!current || current.field !== field) return { field, direction: 'asc' }
  if (current.direction === 'asc') return { field, direction: 'desc' }
  return null
}

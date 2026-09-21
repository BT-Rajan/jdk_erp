import { useId } from 'react'

/** Every form field shares this: auto-generate an id when none is given
 * (avoids collisions when a field renders more than once on a page),
 * and derive the hint/error ids used for aria-describedby. */
export function useFieldIds(id?: string) {
  const generatedId = useId()
  const fieldId = id ?? generatedId
  return {
    fieldId,
    hintId: `${fieldId}-hint`,
    errorId: `${fieldId}-error`,
  }
}

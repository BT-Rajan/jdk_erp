import { forwardRef, type FocusEvent, type InputHTMLAttributes } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'
import { inputClasses } from './inputClasses'

export interface NumberFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string
  error?: string
  hint?: string
}

/** Clamps into [min,max] on blur when both are set -- built into the
 * field instead of every call site re-implementing a clamp helper by
 * hand (jdk_clean had a `clampNonNegative` utility in lib/number.ts but
 * applied it manually per call site rather than baking it into a
 * NumberField, since no such field existed). */
export const NumberField = forwardRef<HTMLInputElement, NumberFieldProps>(function NumberField(
  { label, error, hint, min, max, onBlur, id, className, required, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)

  function handleBlur(event: FocusEvent<HTMLInputElement>) {
    if ((min !== undefined || max !== undefined) && event.target.value !== '') {
      const n = Number(event.target.value)
      if (!Number.isNaN(n)) {
        let clamped = n
        if (min !== undefined && clamped < Number(min)) clamped = Number(min)
        if (max !== undefined && clamped > Number(max)) clamped = Number(max)
        if (clamped !== n) event.target.value = String(clamped)
      }
    }
    onBlur?.(event)
  }

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error} required={required}>
      <input
        ref={ref}
        id={fieldId}
        type="number"
        min={min}
        max={max}
        onBlur={handleBlur}
        aria-invalid={!!error || undefined}
        aria-describedby={describedBy(hint, error, hintId, errorId)}
        className={inputClasses(!!error, className)}
        {...props}
      />
    </FieldShell>
  )
})

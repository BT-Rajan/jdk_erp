import { forwardRef, type InputHTMLAttributes } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'
import { inputClasses } from './inputClasses'

export interface DateFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string
  error?: string
  hint?: string
  /** Renders a datetime-local input instead of a date-only input. */
  withTime?: boolean
}

export const DateField = forwardRef<HTMLInputElement, DateFieldProps>(function DateField(
  { label, error, hint, withTime = false, id, className, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error}>
      <input
        ref={ref}
        id={fieldId}
        type={withTime ? 'datetime-local' : 'date'}
        aria-invalid={!!error || undefined}
        aria-describedby={describedBy(hint, error, hintId, errorId)}
        className={inputClasses(!!error, className)}
        {...props}
      />
    </FieldShell>
  )
})

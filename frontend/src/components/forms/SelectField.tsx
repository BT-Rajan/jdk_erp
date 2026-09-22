import { forwardRef, type ReactNode, type SelectHTMLAttributes } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'
import { inputClasses } from './inputClasses'

export interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string
  error?: string
  hint?: string
  children: ReactNode
}

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { label, error, hint, id, className, children, required, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error} required={required}>
      <select
        ref={ref}
        id={fieldId}
        aria-invalid={!!error || undefined}
        aria-describedby={describedBy(hint, error, hintId, errorId)}
        className={inputClasses(!!error, className)}
        {...props}
      >
        {children}
      </select>
    </FieldShell>
  )
})

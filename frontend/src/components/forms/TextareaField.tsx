import { forwardRef, type TextareaHTMLAttributes } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { cn } from '@/lib/cn'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'
import { inputClasses } from './inputClasses'

export interface TextareaFieldProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string
  error?: string
  hint?: string
}

export const TextareaField = forwardRef<HTMLTextAreaElement, TextareaFieldProps>(function TextareaField(
  { label, error, hint, id, className, rows = 3, required, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error} required={required}>
      <textarea
        ref={ref}
        id={fieldId}
        rows={rows}
        aria-invalid={!!error || undefined}
        aria-describedby={describedBy(hint, error, hintId, errorId)}
        className={cn(inputClasses(!!error), 'h-auto py-2', className)}
        {...props}
      />
    </FieldShell>
  )
})

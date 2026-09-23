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
  /** Spans both grid columns by default -- a textarea cramped into a
   * half-width column defeats the point of it being multi-line. Pass
   * `false` to allow it to share a row when a form genuinely wants that. */
  fullWidth?: boolean
}

export const TextareaField = forwardRef<HTMLTextAreaElement, TextareaFieldProps>(function TextareaField(
  { label, error, hint, id, className, rows = 3, required, fullWidth = true, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error} required={required} fullWidth={fullWidth}>
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

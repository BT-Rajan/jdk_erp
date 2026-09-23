import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { cn } from '@/lib/cn'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'
import { inputClasses } from './inputClasses'

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  error?: string
  hint?: string
  leadingIcon?: ReactNode
  trailingSlot?: ReactNode
  /** Span both columns of a two-column form grid instead of sharing a row. */
  fullWidth?: boolean
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, error, hint, leadingIcon, trailingSlot, id, className, required, fullWidth, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error} required={required} fullWidth={fullWidth}>
      <div className="relative flex items-center">
        {leadingIcon && <span className="pointer-events-none absolute left-3 text-gold-100/40">{leadingIcon}</span>}
        <input
          ref={ref}
          id={fieldId}
          aria-invalid={!!error || undefined}
          aria-describedby={describedBy(hint, error, hintId, errorId)}
          className={cn(inputClasses(!!error), leadingIcon && 'pl-9', trailingSlot && 'pr-9', className)}
          {...props}
        />
        {trailingSlot && <div className="absolute right-2">{trailingSlot}</div>}
      </div>
    </FieldShell>
  )
})

import { forwardRef, type InputHTMLAttributes } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { cn } from '@/lib/cn'
import { describedBy } from './describedBy'

export interface CheckboxFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string
  error?: string
  hint?: string
  fullWidth?: boolean
}

export const CheckboxField = forwardRef<HTMLInputElement, CheckboxFieldProps>(function CheckboxField(
  { label, error, hint, id, className, required, fullWidth, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)

  return (
    <div className={cn('flex flex-col gap-1.5', fullWidth && 'sm:col-span-2')}>
      <label
        htmlFor={fieldId}
        className={cn(
          'flex items-center gap-2 text-sm text-gold-100',
          required && "after:ml-0.5 after:text-danger-500 after:content-['*']",
        )}
      >
        <input
          ref={ref}
          id={fieldId}
          type="checkbox"
          aria-invalid={!!error || undefined}
          aria-describedby={describedBy(hint, error, hintId, errorId)}
          className={className ?? 'h-4 w-4 rounded border-ink-600 bg-ink-800 text-gold-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold-400'}
          {...props}
        />
        {label}
      </label>
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger-500">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-gold-100/50">
          {hint}
        </p>
      ) : null}
    </div>
  )
})

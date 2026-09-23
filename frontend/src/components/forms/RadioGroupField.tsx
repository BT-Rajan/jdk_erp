import { forwardRef, type InputHTMLAttributes } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { cn } from '@/lib/cn'
import { describedBy } from './describedBy'

export interface RadioGroupOption {
  value: string
  label: string
}

export interface RadioGroupFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'value'> {
  label: string
  options: RadioGroupOption[]
  error?: string
  hint?: string
  fullWidth?: boolean
}

/** react-hook-form's `register(name)` returns one `ref` -- every radio
 * in the group must receive the SAME forwarded ref for RHF to track the
 * group correctly (it only needs a ref to one input in the group to read
 * the checked value). Forwarding this component's ref to every `<input>`
 * below is intentional, not a bug. */
export const RadioGroupField = forwardRef<HTMLInputElement, RadioGroupFieldProps>(function RadioGroupField(
  { label, options, error, hint, name, id, className, required, fullWidth, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)

  return (
    <div className={cn('flex flex-col gap-1.5', fullWidth && 'sm:col-span-2')}>
      <span
        id={fieldId}
        className={cn('text-sm font-medium text-gold-100', required && "after:ml-0.5 after:text-danger-500 after:content-['*']")}
      >
        {label}
      </span>
      <div role="radiogroup" aria-labelledby={fieldId} aria-required={required || undefined} className="flex flex-col gap-2">
        {options.map((option) => (
          <label key={option.value} className={cn('flex items-center gap-2 text-sm text-gold-100', className)}>
            <input
              ref={ref}
              type="radio"
              name={name}
              value={option.value}
              aria-invalid={!!error || undefined}
              aria-describedby={describedBy(hint, error, hintId, errorId)}
              className="h-4 w-4 border-ink-600 bg-ink-800 text-gold-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gold-400"
              {...props}
            />
            {option.label}
          </label>
        ))}
      </div>
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

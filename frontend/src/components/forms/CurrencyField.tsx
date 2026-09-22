import { forwardRef, type InputHTMLAttributes } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { cn } from '@/lib/cn'
import { currencyDecimals, DEFAULT_CURRENCY } from '@/lib/currency'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'
import { inputClasses } from './inputClasses'

export interface CurrencyFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string
  error?: string
  hint?: string
  currency?: string
}

/** A numeric input with a currency-symbol prefix and a decimal step
 * matching that currency -- distinct from NumberField, which the spec
 * lists as a separate field type, so a currency amount doesn't lose its
 * symbol/decimal convention by reusing the generic field. Stores a
 * plain numeric value, like any other number input -- display-only
 * currency formatting is the separate `Currency` component
 * (`components/ui/Currency.tsx`). */
export const CurrencyField = forwardRef<HTMLInputElement, CurrencyFieldProps>(function CurrencyField(
  { label, error, hint, currency = DEFAULT_CURRENCY, id, className, required, step, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)
  // Step matches the currency's own decimal precision (KWD: 3 places,
  // most others: 2) rather than a hard-coded 2-decimal assumption
  // (docs/modules/common_validation.md #4) -- an explicit `step` prop
  // still wins.
  const resolvedStep = step ?? (1 / 10 ** currencyDecimals(currency)).toString()
  const symbol =
    new Intl.NumberFormat('en-US', { style: 'currency', currency, currencyDisplay: 'narrowSymbol' })
      .formatToParts(0)
      .find((part) => part.type === 'currency')?.value ?? currency

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error} required={required}>
      <div className="relative flex items-center">
        <span className="pointer-events-none absolute left-3 text-sm text-gold-100/40">{symbol}</span>
        <input
          ref={ref}
          id={fieldId}
          type="number"
          step={resolvedStep}
          aria-invalid={!!error || undefined}
          aria-describedby={describedBy(hint, error, hintId, errorId)}
          className={cn(inputClasses(!!error), 'pl-8', className)}
          {...props}
        />
      </div>
    </FieldShell>
  )
})

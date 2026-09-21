import { forwardRef, type ReactNode, type SelectHTMLAttributes } from 'react'
import { useFieldIds } from '@/lib/useFieldIds'
import { cn } from '@/lib/cn'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'
import { inputClasses } from './inputClasses'

export interface MultiSelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'multiple'> {
  label: string
  error?: string
  hint?: string
  children: ReactNode
  /** Visible option rows before scrolling; default 4. */
  size?: number
}

/** A native multi-select, sized to show several rows -- correct
 * keyboard/screen-reader behaviour for free, no gap left unfilled (jdk_clean
 * had no multi-select at all). A custom checkbox-list combobox is a
 * reasonable future upgrade if the native control's look becomes a
 * problem, but isn't needed to satisfy the requirement today. */
export const MultiSelectField = forwardRef<HTMLSelectElement, MultiSelectFieldProps>(function MultiSelectField(
  { label, error, hint, id, className, children, size = 4, ...props },
  ref,
) {
  const { fieldId, hintId, errorId } = useFieldIds(id)

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error}>
      <select
        ref={ref}
        id={fieldId}
        multiple
        size={size}
        aria-invalid={!!error || undefined}
        aria-describedby={describedBy(hint, error, hintId, errorId)}
        className={cn(inputClasses(!!error, className), 'h-auto py-1')}
        {...props}
      >
        {children}
      </select>
    </FieldShell>
  )
})

import { useFieldIds } from '@/lib/useFieldIds'
import { FieldShell } from './FieldShell'
import { describedBy } from './describedBy'
import { inputClasses } from './inputClasses'

export interface DateRangeValue {
  from: string | null
  to: string | null
}

export interface DateRangeFieldProps {
  label: string
  value: DateRangeValue
  onChange: (value: DateRangeValue) => void
  error?: string
  hint?: string
  id?: string
}

/** A from/to date pair -- the spec lists "date/date range" as one
 * filter type, and only a single-date field existed before this. */
export function DateRangeField({ label, value, onChange, error, hint, id }: DateRangeFieldProps) {
  const { fieldId, hintId, errorId } = useFieldIds(id)
  const describedById = describedBy(hint, error, hintId, errorId)

  return (
    <FieldShell label={label} fieldId={fieldId} hintId={hintId} errorId={errorId} hint={hint} error={error}>
      <div className="flex items-center gap-2">
        <input
          id={fieldId}
          type="date"
          aria-label={`${label} from`}
          aria-invalid={!!error || undefined}
          aria-describedby={describedById}
          value={value.from ?? ''}
          onChange={(event) => onChange({ ...value, from: event.target.value || null })}
          className={inputClasses(!!error)}
        />
        <span className="shrink-0 text-sm text-gold-100/40">to</span>
        <input
          type="date"
          aria-label={`${label} to`}
          aria-invalid={!!error || undefined}
          aria-describedby={describedById}
          value={value.to ?? ''}
          onChange={(event) => onChange({ ...value, to: event.target.value || null })}
          className={inputClasses(!!error)}
        />
      </div>
    </FieldShell>
  )
}

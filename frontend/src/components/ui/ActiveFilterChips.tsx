import { X } from 'lucide-react'
import { Button } from './Button'

export interface ActiveFilter {
  key: string
  label: string
  onRemove: () => void
}

export interface ActiveFilterChipsProps {
  filters: ActiveFilter[]
  onClearAll?: () => void
}

/** A clear, scannable summary of which filters are currently applied,
 * each individually removable -- pairs with useFilters, whose
 * `activeCount`/`clearOne` a module maps into this shape. Renders
 * nothing when there's nothing active. */
export function ActiveFilterChips({ filters, onClearAll }: ActiveFilterChipsProps) {
  if (filters.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-2">
      {filters.map((filter) => (
        <span key={filter.key} className="inline-flex items-center gap-1 rounded-full bg-ink-700 py-1 pl-2.5 pr-1.5 text-xs text-gold-100">
          {filter.label}
          <button
            type="button"
            aria-label={`Remove ${filter.label} filter`}
            onClick={filter.onRemove}
            className="rounded-full p-0.5 text-gold-100/50 transition-colors hover:bg-ink-600 hover:text-gold-100"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      {onClearAll && (
        <Button variant="ghost" size="sm" onClick={onClearAll}>
          Clear all
        </Button>
      )}
    </div>
  )
}

import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { SortState } from './sort'

export interface SortableHeaderProps {
  label: string
  field: string
  sort: SortState | null
  onSort: (field: string) => void
  align?: 'left' | 'right' | 'center'
  className?: string
}

export function SortableHeader({ label, field, sort, onSort, align = 'left', className }: SortableHeaderProps) {
  const isActive = sort?.field === field
  const direction = isActive ? sort.direction : undefined

  return (
    <th
      scope="col"
      className={cn(
        'px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gold-100/60',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        className,
      )}
    >
      <button
        type="button"
        onClick={() => onSort(field)}
        aria-label={`Sort by ${label}${isActive ? `, currently sorted ${direction === 'asc' ? 'ascending' : 'descending'}` : ''}`}
        className="inline-flex items-center gap-1 transition-colors hover:text-gold-100"
      >
        {label}
        {isActive ? (
          direction === 'asc' ? (
            <ArrowUp size={12} aria-hidden="true" />
          ) : (
            <ArrowDown size={12} aria-hidden="true" />
          )
        ) : (
          <ArrowUpDown size={12} aria-hidden="true" className="opacity-40" />
        )}
      </button>
    </th>
  )
}

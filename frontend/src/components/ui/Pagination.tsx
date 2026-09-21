import { cn } from '@/lib/cn'
import { Button } from './Button'

export interface PaginationProps {
  page: number
  totalPages: number
  total: number
  onPageChange: (page: number) => void
  className?: string
}

/** Returns null when there's nothing to paginate, so callers never need
 * `{totalPages > 1 && <Pagination ... />}` at the call site. */
export function Pagination({ page, totalPages, total, onPageChange, className }: PaginationProps) {
  if (totalPages <= 1) return null

  return (
    <div className={cn('flex items-center justify-between gap-4 text-sm text-gold-100/60', className)}>
      <span>{total} total</span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          Previous
        </Button>
        <span>
          Page {page} of {totalPages}
        </span>
        <Button variant="secondary" size="sm" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  )
}

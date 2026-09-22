import { cn } from '@/lib/cn'
import { Button } from './Button'

export interface PaginationProps {
  page: number
  totalPages: number
  total: number
  onPageChange: (page: number) => void
  className?: string
  /** Standard page-size options (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md's
   * list-contract follow-up) -- omit both `pageSize` and
   * `onPageSizeChange` to keep this exactly as it was before (no
   * selector, Previous/Next only). */
  pageSize?: number
  pageSizeOptions?: number[]
  onPageSizeChange?: (pageSize: number) => void
}

const DEFAULT_PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

/** Returns null when there's nothing to paginate and no page-size
 * control is wired in, so callers never need
 * `{totalPages > 1 && <Pagination ... />}` at the call site. A
 * page-size control is still shown at a single page, though -- picking
 * a smaller size is exactly how a one-page result becomes several. */
export function Pagination({
  page,
  totalPages,
  total,
  onPageChange,
  className,
  pageSize,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  onPageSizeChange,
}: PaginationProps) {
  const showPageSizeControl = pageSize !== undefined && !!onPageSizeChange
  if (totalPages <= 1 && !showPageSizeControl) return null

  return (
    <div className={cn('flex flex-wrap items-center justify-between gap-3 text-sm text-gold-100/60', className)}>
      <div className="flex items-center gap-3">
        <span>{total} total</span>
        {showPageSizeControl && (
          <label className="flex items-center gap-1.5">
            Per page
            <select
              value={pageSize}
              onChange={(event) => onPageSizeChange?.(Number(event.target.value))}
              className="rounded-md border border-ink-600 bg-ink-800 px-2 py-1 text-sm text-gold-100"
            >
              {pageSizeOptions.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {totalPages > 1 && (
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
      )}
    </div>
  )
}

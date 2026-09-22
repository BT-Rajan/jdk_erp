import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Columns3 } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useDismissableOverlay } from '@/lib/useDismissableOverlay'
import { Alert } from './Alert'
import { EmptyState } from './EmptyState'
import { IconButton } from './IconButton'
import { Pagination } from './Pagination'
import { SortableHeader } from './SortableHeader'
import { Spinner } from './Spinner'
import { toggleSort, type SortState } from './sort'

export interface DataTableColumn<T> {
  key: string
  label: string
  sortable?: boolean
  align?: 'left' | 'right' | 'center'
  /** Excluded from the column-visibility toggle -- always shown. */
  alwaysVisible?: boolean
  /** Hide this column on screens narrower than the given breakpoint,
   * instead of shrinking every column to fit -- for secondary
   * information a narrow table can drop, while the row's important
   * columns and its actions column (mark that one `alwaysVisible`, not
   * `hideBelow`) stay put. */
  hideBelow?: 'sm' | 'md' | 'lg'
  render: (row: T) => ReactNode
}

const HIDE_BELOW_CLASSES: Record<NonNullable<DataTableColumn<unknown>['hideBelow']>, string> = {
  sm: 'hidden sm:table-cell',
  md: 'hidden md:table-cell',
  lg: 'hidden lg:table-cell',
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  sort?: SortState | null
  onSortChange?: (sort: SortState | null) => void
  loading?: boolean
  error?: string
  emptyTitle?: string
  emptyMessage?: string
  page?: number
  totalPages?: number
  total?: number
  onPageChange?: (page: number) => void
  enableColumnVisibility?: boolean
  /** Renders a checkbox column when combined with `selectedKeys` +
   * `onSelectionChange` -- the row-selection half of bulk actions
   * (pair with BulkActionsBar for the action toolbar). */
  selectable?: boolean
  selectedKeys?: Set<string | number>
  onSelectionChange?: (keys: Set<string | number>) => void
  /** Keeps the header visible while the table body scrolls vertically
   * -- only meaningful for a long table, so it also caps the body at a
   * fixed height with its own scroll instead of the whole page. */
  stickyHeader?: boolean
}

/** The one table shell every list page composes -- masters and business
 * lists alike. Generalizes jdk_clean's MasterListPage column-as-data
 * shape (which only masters actually used; every real business list
 * page hand-copied the same shell instead). Search/status filtering is
 * deliberately not owned here -- compose FilterBar + TextField/SelectField
 * above this component instead of this component reinventing them. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  sort = null,
  onSortChange,
  loading = false,
  error,
  emptyTitle = 'No records found',
  emptyMessage,
  page,
  totalPages,
  total,
  onPageChange,
  enableColumnVisibility = false,
  selectable = false,
  selectedKeys,
  onSelectionChange,
  stickyHeader = false,
}: DataTableProps<T>) {
  const [hiddenKeys, setHiddenKeys] = useState<Set<string>>(new Set())
  const visibleColumns = columns.filter((column) => !hiddenKeys.has(column.key))

  function handleSort(field: string) {
    onSortChange?.(toggleSort(sort ?? null, field))
  }

  const rowKeys = rows.map(rowKey)
  const selectedCount = selectedKeys ? rowKeys.filter((key) => selectedKeys.has(key)).length : 0
  const allSelected = rowKeys.length > 0 && selectedCount === rowKeys.length
  const someSelected = selectedCount > 0 && !allSelected

  function toggleAll() {
    if (!onSelectionChange) return
    const next = new Set(selectedKeys)
    if (allSelected) rowKeys.forEach((key) => next.delete(key))
    else rowKeys.forEach((key) => next.add(key))
    onSelectionChange(next)
  }

  function toggleRow(key: string | number) {
    if (!onSelectionChange) return
    const next = new Set(selectedKeys)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    onSelectionChange(next)
  }

  function toggleColumn(key: string) {
    setHiddenKeys((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const showPagination = page !== undefined && totalPages !== undefined && total !== undefined && !!onPageChange

  return (
    <div className="flex flex-col gap-3">
      <Alert variant="danger">{error}</Alert>
      {enableColumnVisibility && (
        <div className="flex justify-end">
          <ColumnVisibilityMenu columns={columns} hiddenKeys={hiddenKeys} onToggle={toggleColumn} />
        </div>
      )}
      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState title={emptyTitle} message={emptyMessage} />
      ) : (
        <div className={cn('overflow-x-auto rounded-lg border border-ink-700', stickyHeader && 'max-h-[32rem] overflow-y-auto')}>
          <table className="w-full border-collapse text-left text-sm">
            <thead className={cn('border-b border-ink-700 bg-ink-800/50', stickyHeader && 'sticky top-0 z-10')}>
              <tr>
                {selectable && (
                  <th scope="col" className="w-10 px-3 py-2">
                    <SelectionCheckbox
                      checked={allSelected}
                      indeterminate={someSelected}
                      onChange={toggleAll}
                      label="Select all rows"
                    />
                  </th>
                )}
                {visibleColumns.map((column) =>
                  column.sortable ? (
                    <SortableHeader
                      key={column.key}
                      label={column.label}
                      field={column.key}
                      sort={sort ?? null}
                      onSort={handleSort}
                      align={column.align}
                      className={column.hideBelow && HIDE_BELOW_CLASSES[column.hideBelow]}
                    />
                  ) : (
                    <th
                      key={column.key}
                      scope="col"
                      className={cn(
                        'px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gold-100/60',
                        column.align === 'right' && 'text-right',
                        column.align === 'center' && 'text-center',
                        column.hideBelow && HIDE_BELOW_CLASSES[column.hideBelow],
                      )}
                    >
                      {column.label}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-700">
              {rows.map((row) => {
                const key = rowKey(row)
                return (
                <tr key={key} className="transition-colors hover:bg-ink-800/40">
                  {selectable && (
                    <td className="px-3 py-2">
                      <SelectionCheckbox
                        checked={!!selectedKeys?.has(key)}
                        onChange={() => toggleRow(key)}
                        label={`Select row ${key}`}
                      />
                    </td>
                  )}
                  {visibleColumns.map((column) => (
                    <td
                      key={column.key}
                      className={cn(
                        'px-3 py-2 text-gold-100',
                        column.align === 'right' && 'text-right',
                        column.align === 'center' && 'text-center',
                        column.hideBelow && HIDE_BELOW_CLASSES[column.hideBelow],
                      )}
                    >
                      {column.render(row)}
                    </td>
                  ))}
                </tr>
              )})}
            </tbody>
          </table>
        </div>
      )}
      {showPagination && (
        <Pagination page={page} totalPages={totalPages} total={total} onPageChange={onPageChange} />
      )}
    </div>
  )
}

function SelectionCheckbox({
  checked,
  indeterminate = false,
  onChange,
  label,
}: {
  checked: boolean
  indeterminate?: boolean
  onChange: () => void
  label: string
}) {
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate
  }, [indeterminate])

  return (
    <input
      ref={ref}
      type="checkbox"
      aria-label={label}
      checked={checked}
      onChange={onChange}
      className="h-4 w-4 rounded border-ink-600 bg-ink-800 text-gold-400"
    />
  )
}

function ColumnVisibilityMenu<T>({
  columns,
  hiddenKeys,
  onToggle,
}: {
  columns: DataTableColumn<T>[]
  hiddenKeys: Set<string>
  onToggle: (key: string) => void
}) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  useDismissableOverlay(containerRef, { open, onDismiss: () => setOpen(false) })

  const toggleable = columns.filter((column) => !column.alwaysVisible)

  return (
    <div ref={containerRef} className="relative">
      <IconButton
        icon={<Columns3 size={16} />}
        aria-label="Choose visible columns"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      />
      {open && (
        <div role="menu" aria-label="Choose visible columns" className="absolute right-0 z-10 mt-2 min-w-48 rounded-md border border-ink-600 bg-ink-800 p-2 shadow-lg">
          {toggleable.map((column) => (
            <label key={column.key} className="flex items-center gap-2 rounded px-2 py-1.5 text-sm text-gold-100 hover:bg-ink-700">
              <input
                type="checkbox"
                checked={!hiddenKeys.has(column.key)}
                onChange={() => onToggle(column.key)}
                className="h-4 w-4 rounded border-ink-600 bg-ink-800 text-gold-400"
              />
              {column.label}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

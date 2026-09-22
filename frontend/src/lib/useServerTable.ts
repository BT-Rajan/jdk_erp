import { useEffect, useState } from 'react'
import type { SortState } from '@/components/ui/sort'

export interface ServerTableResult<T> {
  rows: T[]
  total: number
}

export interface UseServerTableOptions<T, F> {
  /** Must be stable across renders (e.g. wrapped in useCallback by the
   * caller) -- it re-runs whenever page/sort/filters change. */
  fetcher: (params: { page: number; pageSize: number; sort: SortState | null; filters: F }) => Promise<ServerTableResult<T>>
  pageSize?: number
  initialFilters: F
}

/** The one shared way a module wires DataTable to a real endpoint --
 * page/sort/filter state plus the request/loading/error plumbing around
 * it, so "don't fetch all records just to filter/sort in the browser"
 * has an actual reusable answer instead of every module re-inventing
 * this glue. DataTable itself stays a dumb, controlled renderer; this
 * hook is what a module composes it with. */
export function useServerTable<T, F>({ fetcher, pageSize = 20, initialFilters }: UseServerTableOptions<T, F>) {
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<SortState | null>(null)
  const [filters, setFiltersState] = useState<F>(initialFilters)
  const [rows, setRows] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(undefined)

    fetcher({ page, pageSize, sort, filters })
      .then((result) => {
        if (cancelled) return
        setRows(result.rows)
        setTotal(result.total)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [fetcher, page, pageSize, sort, filters])

  function setFilters(next: F) {
    setFiltersState(next)
    setPage(1)
  }

  return {
    rows,
    total,
    totalPages: Math.max(1, Math.ceil(total / pageSize)),
    page,
    setPage,
    sort,
    setSort,
    filters,
    setFilters,
    loading,
    error,
  }
}

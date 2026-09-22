import { useEffect, useRef, useState } from 'react'
import type { SortState } from '@/components/ui/sort'

export interface ServerTableResult<T> {
  rows: T[]
  total: number
}

export interface UseServerTableOptions<T, F> {
  /** Must be stable across renders (e.g. wrapped in useCallback by the
   * caller) -- it re-runs whenever page/pageSize/sort/filters change. */
  fetcher: (params: { page: number; pageSize: number; sort: SortState | null; filters: F }) => Promise<ServerTableResult<T>>
  pageSize?: number
  initialFilters: F
}

/** The one shared way a module wires DataTable to a real endpoint --
 * page/pageSize/sort/filter state plus the request/loading/error
 * plumbing around it, so "don't fetch all records just to filter/sort
 * in the browser" has an actual reusable answer instead of every module
 * re-inventing this glue. DataTable itself stays a dumb, controlled
 * renderer; this hook is what a module composes it with.
 *
 * Changing search/filters/sort/pageSize resets to page 1 -- the
 * previous page number rarely still makes sense against a different
 * result set. Changing the page alone never touches filters/sort. */
export function useServerTable<T, F>({ fetcher, pageSize: initialPageSize = 20, initialFilters }: UseServerTableOptions<T, F>) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSizeState] = useState(initialPageSize)
  const [sort, setSortState] = useState<SortState | null>(null)
  const [filters, setFiltersState] = useState<F>(initialFilters)
  const [rows, setRows] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)
  // Bumped by refetch() to re-run the effect below without touching
  // page/pageSize/sort/filters -- the one case those four don't already
  // cover: the server-side data itself changed (a create, an edit)
  // while the caller's own view of it should not reset to page 1.
  const [reloadToken, setReloadToken] = useState(0)

  // Guards against a slower, now-stale request resolving after a newer
  // one and overwriting fresher results -- e.g. typing quickly into a
  // search box can fire several requests whose responses arrive out of
  // order. Only the response matching the latest request id is applied.
  const latestRequestId = useRef(0)

  useEffect(() => {
    const requestId = ++latestRequestId.current
    setLoading(true)
    setError(undefined)

    fetcher({ page, pageSize, sort, filters })
      .then((result) => {
        if (requestId !== latestRequestId.current) return
        setRows(result.rows)
        setTotal(result.total)
      })
      .catch((err: unknown) => {
        if (requestId !== latestRequestId.current) return
        setError(err instanceof Error ? err.message : 'Failed to load')
      })
      .finally(() => {
        if (requestId === latestRequestId.current) setLoading(false)
      })
    // reloadToken is intentionally in the dependency list purely to
    // trigger a re-run; its value is never read.
  }, [fetcher, page, pageSize, sort, filters, reloadToken])

  function refetch() {
    setReloadToken((token) => token + 1)
  }

  function setFilters(next: F) {
    setFiltersState(next)
    setPage(1)
  }

  function setSort(next: SortState | null) {
    setSortState(next)
    setPage(1)
  }

  function setPageSize(next: number) {
    setPageSizeState(next)
    setPage(1)
  }

  return {
    rows,
    total,
    totalPages: total === 0 ? 0 : Math.ceil(total / pageSize),
    page,
    setPage,
    pageSize,
    setPageSize,
    sort,
    setSort,
    filters,
    setFilters,
    loading,
    error,
    refetch,
  }
}

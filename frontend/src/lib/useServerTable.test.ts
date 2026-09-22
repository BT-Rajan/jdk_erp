import { renderHook, waitFor } from '@testing-library/react'
import { act } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useServerTable } from './useServerTable'

interface Row {
  id: number
  name: string
}

describe('useServerTable', () => {
  it('calls the fetcher with page/pageSize/sort/filters and exposes the result', async () => {
    const fetcher = vi.fn().mockResolvedValue({ rows: [{ id: 1, name: 'Acme' }], total: 1 })
    const { result } = renderHook(() =>
      useServerTable<Row, { search: string }>({ fetcher, pageSize: 10, initialFilters: { search: '' } }),
    )

    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(fetcher).toHaveBeenCalledWith({ page: 1, pageSize: 10, sort: null, filters: { search: '' } })
    expect(result.current.rows).toEqual([{ id: 1, name: 'Acme' }])
    expect(result.current.total).toBe(1)
    expect(result.current.totalPages).toBe(1)
  })

  it('never fetches more than one page of rows client-side -- re-fetches instead of accumulating', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ rows: [{ id: 1, name: 'Page 1' }], total: 25 })
      .mockResolvedValueOnce({ rows: [{ id: 2, name: 'Page 2' }], total: 25 })
    const { result } = renderHook(() => useServerTable<Row, object>({ fetcher, pageSize: 10, initialFilters: {} }))
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => result.current.setPage(2))
    await waitFor(() => expect(result.current.rows).toEqual([{ id: 2, name: 'Page 2' }]))

    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(fetcher).toHaveBeenLastCalledWith({ page: 2, pageSize: 10, sort: null, filters: {} })
  })

  it('resets to page 1 when filters change', async () => {
    const fetcher = vi.fn().mockResolvedValue({ rows: [], total: 0 })
    const { result } = renderHook(() =>
      useServerTable<Row, { status: string }>({ fetcher, initialFilters: { status: 'active' } }),
    )
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => result.current.setPage(3))
    await waitFor(() => expect(result.current.page).toBe(3))

    act(() => result.current.setFilters({ status: 'inactive' }))
    expect(result.current.page).toBe(1)
    await waitFor(() => expect(fetcher).toHaveBeenLastCalledWith({ page: 1, pageSize: 20, sort: null, filters: { status: 'inactive' } }))
  })

  it('surfaces a fetch failure as an error message, not an unhandled rejection', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('Network down'))
    const { result } = renderHook(() => useServerTable<Row, object>({ fetcher, initialFilters: {} }))

    await waitFor(() => expect(result.current.error).toBe('Network down'))
    expect(result.current.loading).toBe(false)
  })
})

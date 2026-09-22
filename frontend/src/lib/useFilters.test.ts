import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useFilters } from './useFilters'

interface SupplierFilters {
  search: string
  status: string
  [key: string]: unknown
}

describe('useFilters', () => {
  const initial: SupplierFilters = { search: '', status: 'all' }

  it('starts with the initial values and zero active filters', () => {
    const { result } = renderHook(() => useFilters(initial))
    expect(result.current.values).toEqual(initial)
    expect(result.current.activeCount).toBe(0)
  })

  it('setValue updates one field and counts it as active when non-empty and different from default', () => {
    const { result } = renderHook(() => useFilters(initial))
    act(() => result.current.setValue('search', 'acme'))

    expect(result.current.values).toEqual({ search: 'acme', status: 'all' })
    expect(result.current.activeCount).toBe(1)
  })

  it('does not count a value equal to its default as active', () => {
    const { result } = renderHook(() => useFilters(initial))
    act(() => result.current.setValue('status', 'all'))
    expect(result.current.activeCount).toBe(0)
  })

  it('clearOne resets a single field back to its initial value', () => {
    const { result } = renderHook(() => useFilters(initial))
    act(() => result.current.setValue('search', 'acme'))
    act(() => result.current.setValue('status', 'active'))
    expect(result.current.activeCount).toBe(2)

    act(() => result.current.clearOne('search'))
    expect(result.current.values.search).toBe('')
    expect(result.current.values.status).toBe('active')
    expect(result.current.activeCount).toBe(1)
  })

  it('clear resets everything back to the initial values', () => {
    const { result } = renderHook(() => useFilters(initial))
    act(() => result.current.setValue('search', 'acme'))
    act(() => result.current.setValue('status', 'active'))

    act(() => result.current.clear())
    expect(result.current.values).toEqual(initial)
    expect(result.current.activeCount).toBe(0)
  })
})

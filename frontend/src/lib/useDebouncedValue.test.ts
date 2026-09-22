import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useDebouncedValue } from './useDebouncedValue'

describe('useDebouncedValue', () => {
  it('returns the initial value immediately', () => {
    const { result } = renderHook(() => useDebouncedValue('a', 50))
    expect(result.current).toBe('a')
  })

  it('only updates after the delay has passed with no further change', async () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 30), {
      initialProps: { value: 'a' },
    })

    rerender({ value: 'ab' })
    expect(result.current).toBe('a') // not yet -- debounce hasn't elapsed

    await waitFor(() => expect(result.current).toBe('ab'))
  })

  it('resets the timer on each change -- only the final value is applied', async () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 30), {
      initialProps: { value: 'a' },
    })

    rerender({ value: 'ab' })
    rerender({ value: 'abc' })
    rerender({ value: 'abcd' })

    await waitFor(() => expect(result.current).toBe('abcd'))
  })
})

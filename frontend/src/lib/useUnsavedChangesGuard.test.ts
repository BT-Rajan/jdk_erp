import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useUnsavedChangesGuard } from './useUnsavedChangesGuard'

function fireBeforeUnload(): BeforeUnloadEvent {
  const event = new Event('beforeunload', { cancelable: true }) as BeforeUnloadEvent
  window.dispatchEvent(event)
  return event
}

describe('useUnsavedChangesGuard', () => {
  it('does not intercept beforeunload when not dirty', () => {
    renderHook(() => useUnsavedChangesGuard(false))
    const event = fireBeforeUnload()
    expect(event.defaultPrevented).toBe(false)
  })

  it('prevents the default beforeunload behaviour when dirty', () => {
    renderHook(() => useUnsavedChangesGuard(true))
    const event = fireBeforeUnload()
    expect(event.defaultPrevented).toBe(true)
  })

  it('stops intercepting once isDirty flips back to false', () => {
    const { rerender } = renderHook(({ dirty }) => useUnsavedChangesGuard(dirty), { initialProps: { dirty: true } })
    rerender({ dirty: false })
    const event = fireBeforeUnload()
    expect(event.defaultPrevented).toBe(false)
  })

  it('removes its listener on unmount', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const { unmount } = renderHook(() => useUnsavedChangesGuard(true))
    unmount()
    expect(removeSpy).toHaveBeenCalledWith('beforeunload', expect.any(Function))
  })
})

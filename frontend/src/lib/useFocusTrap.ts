import { useEffect, type RefObject } from 'react'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface UseFocusTrapOptions {
  active: boolean
  onEscape?: () => void
  /** Focus this element on open instead of the first focusable child --
   * e.g. a destructive confirm dialog should default focus to Cancel,
   * not whichever button happens to come first in DOM order. */
  initialFocusRef?: RefObject<HTMLElement | null>
}

/** Shared by Modal and Drawer: traps Tab/Shift+Tab inside `containerRef`,
 * restores focus to whatever was focused before opening, and calls
 * `onEscape` on the Escape key. Both components render via a portal, so
 * this can't rely on the DOM tree above `containerRef` at all. */
export function useFocusTrap(containerRef: RefObject<HTMLElement | null>, options: UseFocusTrapOptions) {
  const { active, onEscape, initialFocusRef } = options

  useEffect(() => {
    if (!active) return

    const previouslyFocused = document.activeElement as HTMLElement | null

    const target = initialFocusRef?.current ?? containerRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
    target?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onEscape?.()
        return
      }
      if (event.key !== 'Tab' || !containerRef.current) return

      const focusable = Array.from(containerRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      if (focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      previouslyFocused?.focus()
    }
  }, [active])
}

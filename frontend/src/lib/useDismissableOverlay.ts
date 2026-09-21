import { useEffect, type RefObject } from 'react'

interface UseDismissableOverlayOptions {
  open: boolean
  onDismiss: () => void
}

/** Shared by ActionMenu and any other trigger+panel overlay: closes on a
 * pointerdown outside the container or on Escape. jdk_clean implemented
 * this same logic three separate times (DownloadMenu, ApprovalMenu,
 * NavDropdown) -- one copy here instead. */
export function useDismissableOverlay(containerRef: RefObject<HTMLElement | null>, options: UseDismissableOverlayOptions) {
  const { open, onDismiss } = options

  useEffect(() => {
    if (!open) return

    function handlePointerDown(event: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        onDismiss()
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onDismiss()
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])
}

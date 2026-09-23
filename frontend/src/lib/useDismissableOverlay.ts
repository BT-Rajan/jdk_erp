import { useEffect, type RefObject } from 'react'

interface UseDismissableOverlayOptions {
  open: boolean
  onDismiss: () => void
}

/** Shared by ActionMenu and any other trigger+panel overlay: closes on a
 * pointerdown outside the container(s) or on Escape. jdk_clean implemented
 * this same logic three separate times (DownloadMenu, ApprovalMenu,
 * NavDropdown) -- one copy here instead.
 *
 * Accepts one ref for a trigger+panel that share a single DOM subtree, or
 * several for a trigger and a panel that don't -- e.g. a panel rendered
 * via `createPortal` into `document.body` so an ancestor's `overflow`
 * can't clip it (docs/modules/common_ui_components.md). A pointerdown is
 * only treated as "outside" when it falls outside every given ref. */
export function useDismissableOverlay(
  containerRef: RefObject<HTMLElement | null> | RefObject<HTMLElement | null>[],
  options: UseDismissableOverlayOptions,
) {
  const { open, onDismiss } = options
  const containerRefs = Array.isArray(containerRef) ? containerRef : [containerRef]

  useEffect(() => {
    if (!open) return

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node
      const isInside = containerRefs.some((ref) => ref.current?.contains(target))
      if (!isInside) onDismiss()
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

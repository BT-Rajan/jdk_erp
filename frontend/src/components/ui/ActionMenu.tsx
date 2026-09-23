import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { MoreVertical } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useDismissableOverlay } from '@/lib/useDismissableOverlay'
import { IconButton } from './IconButton'
import { MenuPanel } from './MenuPanel'

export interface ActionMenuOption {
  key: string
  label: string
  onSelect: () => void
  disabled?: boolean
  danger?: boolean
}

export interface ActionMenuProps {
  options: ActionMenuOption[]
  /** aria-label for the trigger button and the menu itself. */
  label?: string
  className?: string
}

/** The one "⋮" action menu every list row / detail page composes.
 * Replaces jdk_clean's three independent, near-identical dropdown
 * implementations (DownloadMenu, ApprovalMenu, NavDropdown) with a
 * single generic trigger+options primitive, and adds the arrow-key
 * navigation none of those three had.
 *
 * This must always be present alongside a ContextMenu on the same row
 * (never the reverse) -- right-click is a desktop-only convenience, not
 * an access path a touch/mobile user has.
 *
 * The panel renders through a portal into `document.body`, fixed-positioned
 * from the trigger's own bounding rect -- like ContextMenu already does,
 * and for the same reason: a row-level trigger sits inside DataTable's
 * `overflow-x-auto` wrapper, and CSS maps a lone `overflow-x` onto
 * `overflow-y: auto` too, so a panel positioned relative to that ancestor
 * gets clipped by it and grows a real (if pointless, one-row-of-content)
 * scrollbar around itself. A portal escapes that ancestor entirely; both
 * the trigger and the portaled panel are passed to useDismissableOverlay
 * since they no longer share a DOM subtree. */
export function ActionMenu({ options, label = 'Actions', className }: ActionMenuProps) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [style, setStyle] = useState<CSSProperties | null>(null)

  useDismissableOverlay([triggerRef, panelRef], { open, onDismiss: () => setOpen(false) })

  useLayoutEffect(() => {
    if (!open) {
      setStyle(null)
      return
    }

    function reposition() {
      const rect = triggerRef.current?.getBoundingClientRect()
      if (!rect) return
      setStyle({ position: 'fixed', top: rect.bottom + 8, right: window.innerWidth - rect.right })
    }

    reposition()
    // Keep the panel anchored to the trigger if the page (or a scroll
    // container the trigger sits in, e.g. DataTable's own body scroll)
    // moves under it -- capture:true catches scroll on any ancestor,
    // not just window.
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    return () => {
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
    }
  }, [open])

  return (
    <div ref={triggerRef} className={cn('relative inline-block', className)}>
      <IconButton
        icon={<MoreVertical size={18} />}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      />
      {open &&
        style &&
        createPortal(
          <MenuPanel ref={panelRef} options={options} label={label} onClose={() => setOpen(false)} style={style} />,
          document.body,
        )}
    </div>
  )
}

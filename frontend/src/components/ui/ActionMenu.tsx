import { useRef, useState } from 'react'
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
 * an access path a touch/mobile user has. */
export function ActionMenu({ options, label = 'Actions', className }: ActionMenuProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useDismissableOverlay(containerRef, { open, onDismiss: () => setOpen(false) })

  return (
    <div ref={containerRef} className={cn('relative inline-block', className)}>
      <IconButton
        icon={<MoreVertical size={18} />}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      />
      {open && <MenuPanel options={options} label={label} onClose={() => setOpen(false)} className="absolute right-0 mt-2" />}
    </div>
  )
}

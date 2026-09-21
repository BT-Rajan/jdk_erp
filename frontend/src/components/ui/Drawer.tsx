import { useRef, type MouseEvent, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useFocusTrap } from '@/lib/useFocusTrap'
import { IconButton } from './IconButton'

export interface DrawerProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  side?: 'left' | 'right'
  initialFocusRef?: RefObject<HTMLElement | null>
}

/** A side panel for a record's detail view, built on the same
 * portal + focus-trap groundwork as Modal (via the shared useFocusTrap
 * hook) rather than duplicating that logic a second time. Use this
 * instead of Modal when the content is a detail/edit view the user may
 * want to keep glancing at the underlying list behind, not a blocking
 * decision. */
export function Drawer({ open, title, onClose, children, footer, side = 'right', initialFocusRef }: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null)

  useFocusTrap(panelRef, { active: open, onEscape: onClose, initialFocusRef })

  if (!open) return null

  function handleBackdropMouseDown(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) onClose()
  }

  return createPortal(
    <div className="fixed inset-0 z-50 bg-ink-950/70" onMouseDown={handleBackdropMouseDown}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          'fixed top-0 flex h-full w-full max-w-md flex-col border-ink-600 bg-ink-900 shadow-glow-gold sm:max-w-lg',
          side === 'right' ? 'right-0 border-l' : 'left-0 border-r',
        )}
      >
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-4">
          <h2 className="font-display text-lg font-medium text-gold-100">{title}</h2>
          <IconButton icon={<X size={18} />} aria-label="Close" onClick={onClose} />
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-ink-700 px-5 py-4">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

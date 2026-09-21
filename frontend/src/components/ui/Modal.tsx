import { useRef, type MouseEvent, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useFocusTrap } from '@/lib/useFocusTrap'
import { IconButton } from './IconButton'

export type ModalSize = 'default' | 'wide' | 'fullPage'

export interface ModalProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  /** 'default' (max-w-md) for a short confirmation/simple form, 'wide'
   * (max-w-2xl) for a form with several fields, 'fullPage' for content
   * that needs most of the viewport (a detail view, a big table). */
  size?: ModalSize
  /** Focus this instead of the first focusable element on open -- e.g. a
   * destructive dialog should default focus to Cancel, not whichever
   * button happens to come first in DOM order. */
  initialFocusRef?: RefObject<HTMLElement | null>
}

const SIZE_CLASSES: Record<ModalSize, string> = {
  default: 'max-w-md',
  wide: 'max-w-2xl',
  fullPage: 'h-[90vh] w-[95vw] max-w-6xl',
}

/** Rendered via a portal to `document.body` -- kept out of any ancestor
 * stacking context (a sticky app header, a scrollable panel) that would
 * otherwise fight the modal for z-index. */
export function Modal({ open, title, onClose, children, footer, size = 'default', initialFocusRef }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)

  useFocusTrap(dialogRef, { active: open, onEscape: onClose, initialFocusRef })

  if (!open) return null

  function handleBackdropMouseDown(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) onClose()
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/70 p-4"
      onMouseDown={handleBackdropMouseDown}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          'flex max-h-[90vh] w-full flex-col rounded-lg border border-ink-600 bg-ink-900 shadow-glow-gold',
          SIZE_CLASSES[size],
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

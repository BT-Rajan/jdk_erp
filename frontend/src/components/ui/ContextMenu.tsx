import { cloneElement, isValidElement, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { useDismissableOverlay } from '@/lib/useDismissableOverlay'
import type { ActionMenuOption } from './ActionMenu'
import { MenuPanel } from './MenuPanel'

export interface ContextMenuProps {
  options: ActionMenuOption[]
  label?: string
  /** A single element to attach the right-click handler to. */
  children: ReactElement
}

/** An optional desktop convenience, never a required one: this must
 * only ever be composed alongside an ActionMenu offering the SAME
 * options on the same row/card, never used by itself -- a touch/mobile
 * user (and most long-press browser behaviour is inconsistent enough
 * not to rely on) has no other way to reach a right-click-only action.
 * Reuses ActionMenu's MenuPanel rather than re-implementing the option
 * list and keyboard navigation a second time. */
export function ContextMenu({ options, label = 'Actions', children }: ContextMenuProps) {
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useDismissableOverlay(panelRef, { open: position !== null, onDismiss: () => setPosition(null) })

  if (!isValidElement(children)) return children

  const child = children as ReactElement<Record<string, unknown>>
  const trigger = cloneElement(child, {
    onContextMenu: (event: ReactMouseEvent) => {
      ;(child.props.onContextMenu as ((e: ReactMouseEvent) => void) | undefined)?.(event)
      event.preventDefault()
      setPosition({ x: event.clientX, y: event.clientY })
    },
  })

  return (
    <>
      {trigger}
      {position &&
        createPortal(
          <MenuPanel
            ref={panelRef}
            options={options}
            label={label}
            onClose={() => setPosition(null)}
            style={{ position: 'fixed', top: position.y, left: position.x }}
          />,
          document.body,
        )}
    </>
  )
}

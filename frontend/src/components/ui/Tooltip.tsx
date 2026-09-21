import { cloneElement, isValidElement, useId, useRef, useState, type ReactElement } from 'react'
import { cn } from '@/lib/cn'

export interface TooltipProps {
  label: string
  side?: 'top' | 'bottom' | 'left' | 'right'
  /** A single focusable/hoverable element -- an icon button, a truncated
   * label, a disabled control explaining why. */
  children: ReactElement
}

const SIDE_CLASSES: Record<NonNullable<TooltipProps['side']>, string> = {
  top: 'bottom-full left-1/2 mb-2 -translate-x-1/2',
  bottom: 'top-full left-1/2 mt-2 -translate-x-1/2',
  left: 'right-full top-1/2 mr-2 -translate-y-1/2',
  right: 'left-full top-1/2 ml-2 -translate-y-1/2',
}

const SHOW_DELAY_MS = 300

export function Tooltip({ label, side = 'top', children }: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const timeoutRef = useRef<number | undefined>(undefined)
  const id = useId()

  function show() {
    window.clearTimeout(timeoutRef.current)
    timeoutRef.current = window.setTimeout(() => setVisible(true), SHOW_DELAY_MS)
  }

  function hide() {
    window.clearTimeout(timeoutRef.current)
    setVisible(false)
  }

  if (!isValidElement(children)) return children

  const child = children as ReactElement<Record<string, unknown>>
  const trigger = cloneElement(child, {
    'aria-describedby': visible ? id : undefined,
    onMouseEnter: (event: unknown) => {
      ;(child.props.onMouseEnter as ((e: unknown) => void) | undefined)?.(event)
      show()
    },
    onMouseLeave: (event: unknown) => {
      ;(child.props.onMouseLeave as ((e: unknown) => void) | undefined)?.(event)
      hide()
    },
    onFocus: (event: unknown) => {
      ;(child.props.onFocus as ((e: unknown) => void) | undefined)?.(event)
      show()
    },
    onBlur: (event: unknown) => {
      ;(child.props.onBlur as ((e: unknown) => void) | undefined)?.(event)
      hide()
    },
  })

  return (
    <span className="relative inline-block">
      {trigger}
      {visible && (
        <span
          id={id}
          role="tooltip"
          className={cn(
            'pointer-events-none absolute z-20 whitespace-nowrap rounded bg-ink-800 px-2 py-1 text-xs text-gold-100 shadow-lg',
            SIDE_CLASSES[side],
          )}
        >
          {label}
        </span>
      )}
    </span>
  )
}

import { forwardRef, useEffect, useRef, type CSSProperties, type KeyboardEvent } from 'react'
import { cn } from '@/lib/cn'
import type { ActionMenuOption } from './ActionMenu'

export interface MenuPanelProps {
  options: ActionMenuOption[]
  label: string
  onClose: () => void
  className?: string
  style?: CSSProperties
}

/** The option-list rendering + focus-on-open + arrow-key navigation
 * shared by ActionMenu (anchored, opened by a visible trigger) and
 * ContextMenu (positioned at the cursor, opened by right-click) --
 * pulled out so the second one doesn't duplicate this logic instead of
 * reusing it. */
export const MenuPanel = forwardRef<HTMLDivElement, MenuPanelProps>(function MenuPanel(
  { options, label, onClose, className, style },
  forwardedRef,
) {
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => {
    const firstEnabled = options.findIndex((option) => !option.disabled)
    if (firstEnabled >= 0) itemRefs.current[firstEnabled]?.focus()
  }, [options])

  function enabledIndexes() {
    return options.map((_, index) => index).filter((index) => !options[index].disabled)
  }

  function focusIndex(index: number) {
    itemRefs.current[index]?.focus()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const indexes = enabledIndexes()
    if (indexes.length === 0) return
    const current = itemRefs.current.findIndex((el) => el === document.activeElement)

    if (event.key === 'ArrowDown') {
      event.preventDefault()
      const next = indexes.find((index) => index > current) ?? indexes[0]
      focusIndex(next)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      const candidates = indexes.filter((index) => index < current)
      focusIndex(candidates.length > 0 ? candidates[candidates.length - 1] : indexes[indexes.length - 1])
    } else if (event.key === 'Home') {
      event.preventDefault()
      focusIndex(indexes[0])
    } else if (event.key === 'End') {
      event.preventDefault()
      focusIndex(indexes[indexes.length - 1])
    }
  }

  return (
    <div
      ref={forwardedRef}
      role="menu"
      aria-label={label}
      onKeyDown={handleKeyDown}
      style={style}
      className={cn('z-10 min-w-40 rounded-md border border-ink-600 bg-ink-800 py-1 shadow-lg', className)}
    >
      {options.map((option, index) => (
        <button
          key={option.key}
          ref={(el) => {
            itemRefs.current[index] = el
          }}
          role="menuitem"
          type="button"
          disabled={option.disabled}
          onClick={() => {
            option.onSelect()
            onClose()
          }}
          className={cn(
            'block w-full px-3 py-2 text-left text-sm transition-colors hover:bg-ink-700',
            'disabled:cursor-not-allowed disabled:opacity-40',
            option.danger ? 'text-danger-500' : 'text-gold-100',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
})

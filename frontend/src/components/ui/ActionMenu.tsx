import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { MoreVertical } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useDismissableOverlay } from '@/lib/useDismissableOverlay'
import { IconButton } from './IconButton'

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
 * navigation none of those three had. */
export function ActionMenu({ options, label = 'Actions', className }: ActionMenuProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([])

  useDismissableOverlay(containerRef, { open, onDismiss: () => setOpen(false) })

  useEffect(() => {
    if (!open) return
    const firstEnabled = options.findIndex((option) => !option.disabled)
    if (firstEnabled >= 0) itemRefs.current[firstEnabled]?.focus()
  }, [open, options])

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
    <div ref={containerRef} className={cn('relative inline-block', className)}>
      <IconButton
        icon={<MoreVertical size={18} />}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      />
      {open && (
        <div
          role="menu"
          aria-label={label}
          onKeyDown={handleKeyDown}
          className="absolute right-0 z-10 mt-2 min-w-40 rounded-md border border-ink-600 bg-ink-800 py-1 shadow-lg"
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
                setOpen(false)
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
      )}
    </div>
  )
}

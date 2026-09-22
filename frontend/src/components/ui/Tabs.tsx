import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface TabItem {
  id: string
  label: string
  badge?: ReactNode
}

export interface TabsProps {
  items: TabItem[]
  activeId: string
  onChange: (id: string) => void
  size?: 'md' | 'sm'
  className?: string
}

const SIZE_CLASSES = {
  md: 'px-4 py-2 text-sm',
  sm: 'px-3 py-1.5 text-xs',
}

/** Full WAI-ARIA tabs pattern: role="tablist"/"tab", aria-selected,
 * aria-controls, a roving tabindex, and Arrow/Home/End keyboard nav. */
export function Tabs({ items, activeId, onChange, size = 'md', className }: TabsProps) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([])

  function focusAndActivate(index: number) {
    const item = items[index]
    tabRefs.current[index]?.focus()
    onChange(item.id)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const currentIndex = items.findIndex((item) => item.id === activeId)
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      focusAndActivate((currentIndex + 1) % items.length)
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault()
      focusAndActivate((currentIndex - 1 + items.length) % items.length)
    } else if (event.key === 'Home') {
      event.preventDefault()
      focusAndActivate(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      focusAndActivate(items.length - 1)
    }
  }

  return (
    <div
      role="tablist"
      onKeyDown={handleKeyDown}
      className={cn('flex gap-1 overflow-x-auto border-b border-ink-700', className)}
    >
      {items.map((item, index) => {
        const isActive = item.id === activeId
        return (
          <button
            key={item.id}
            ref={(el) => {
              tabRefs.current[index] = el
            }}
            role="tab"
            type="button"
            id={`tab-${item.id}`}
            aria-selected={isActive}
            aria-controls={`tabpanel-${item.id}`}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(item.id)}
            className={cn(
              'flex items-center gap-2 border-b-2 font-medium transition-colors',
              SIZE_CLASSES[size],
              isActive ? 'border-gold-400 text-gold-100' : 'border-transparent text-gold-100/50 hover:text-gold-100/80',
            )}
          >
            {item.label}
            {item.badge}
          </button>
        )
      })}
    </div>
  )
}

export interface TabPanelProps {
  id: string
  activeId: string
  className?: string
  /** Keep this panel mounted even while hidden -- needed for a panel
   * that holds a react-hook-form-registered field, since unmounting
   * would drop that field's registration. */
  keepMounted?: boolean
  children: ReactNode
}

export function TabPanel({ id, activeId, className, keepMounted = false, children }: TabPanelProps) {
  const isActive = id === activeId
  if (!isActive && !keepMounted) return null

  return (
    <div
      role="tabpanel"
      id={`tabpanel-${id}`}
      aria-labelledby={`tab-${id}`}
      hidden={!isActive}
      className={className}
    >
      {children}
    </div>
  )
}

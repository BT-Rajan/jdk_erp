import { useRef, useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useDismissableOverlay } from '@/lib/useDismissableOverlay'
import type { NavEntry, NavGroup } from './nav-types'

export interface TopNavProps {
  logo: ReactNode
  /** Optional inline menu; omit it when a Sidebar is the app's menu. */
  entries?: NavEntry[]
  /** Slotted actions -- search trigger, notifications, avatar, etc. This
   * component owns no auth/business state of its own. */
  actions?: ReactNode
}

const LEAF_CLASSES =
  'rounded-md px-3 py-2 text-sm font-medium transition-colors text-gold-100/70 hover:text-gold-100 aria-[current=page]:text-gold-300'

export function TopNav({ logo, entries = [], actions }: TopNavProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-ink-700 bg-ink-950/90 backdrop-blur">
      <div className="mx-auto flex h-16 items-center justify-between gap-4 px-4">
        <div className="flex min-w-0 items-center gap-6">
          {logo}
          {/* Below md, a Sidebar (opened via a hamburger the app places
             in `logo`) is the mobile nav path -- this inline list would
             otherwise force the header wider than the viewport. */}
          {entries.length > 0 && (
            <nav aria-label="Main" className="hidden md:block">
              <ul className="flex items-center gap-1">
                {entries.map((entry) => (
                  <li key={entry.label}>
                    {entry.type === 'leaf' ? (
                      <NavLink to={entry.to} className={LEAF_CLASSES}>
                        {entry.icon}
                        {entry.label}
                      </NavLink>
                    ) : (
                      <NavGroupDropdown entry={entry} />
                    )}
                  </li>
                ))}
              </ul>
            </nav>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}

function NavGroupDropdown({ entry }: { entry: NavGroup }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  useDismissableOverlay(containerRef, { open, onDismiss: () => setOpen(false) })

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={cn(LEAF_CLASSES, 'flex items-center gap-1')}
      >
        {entry.icon}
        {entry.label}
        <ChevronDown size={14} aria-hidden="true" className={cn('transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div
          role="menu"
          aria-label={entry.label}
          className="absolute left-0 z-10 mt-2 min-w-40 rounded-md border border-ink-600 bg-ink-800 py-1 shadow-lg"
        >
          {entry.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              role="menuitem"
              onClick={() => setOpen(false)}
              className="block px-3 py-2 text-sm text-gold-100 transition-colors hover:bg-ink-700 aria-[current=page]:text-gold-300"
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  )
}

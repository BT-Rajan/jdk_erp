import { useEffect, useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { ChevronDown, ChevronsLeft, ChevronsRight } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Tooltip } from './Tooltip'
import type { NavEntry } from './nav-types'

export interface SidebarProps {
  entries: NavEntry[]
  collapsed: boolean
  onToggleCollapsed: () => void
  header?: ReactNode
  /** Mobile-only off-canvas state. Below the `md` breakpoint the sidebar
   * is hidden by default and slides in as an overlay with a backdrop
   * when true; at `md` and above both props are ignored and the sidebar
   * behaves exactly as before (always visible, sized by `collapsed`).
   * Omitting them keeps existing usage unchanged. */
  mobileOpen?: boolean
  onMobileClose?: () => void
}

const LEAF_CLASSES =
  'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-gold-100/70 transition-colors hover:text-gold-100 aria-[current=page]:bg-ink-800 aria-[current=page]:text-gold-300'

/** A persistent, collapsible side nav -- jdk_clean had no equivalent at
 * all (it's top-nav-only), so this has no reused precedent. Takes the
 * same NavEntry[] shape as TopNav and owns no auth/business state. */
export function Sidebar({ entries, collapsed, onToggleCollapsed, header, mobileOpen = false, onMobileClose }: SidebarProps) {
  useEffect(() => {
    if (!mobileOpen) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onMobileClose?.()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [mobileOpen, onMobileClose])

  return (
    <>
      {mobileOpen && (
        <div
          aria-hidden="true"
          onClick={onMobileClose}
          className="fixed inset-0 z-30 bg-ink-950/70 md:hidden"
        />
      )}
      <aside
        className={cn(
          'flex h-full flex-col border-r border-ink-700 bg-ink-900/60 transition-transform md:static md:z-auto md:translate-x-0 md:transition-[width]',
          'fixed inset-y-0 left-0 z-40',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
          collapsed ? 'md:w-16' : 'md:w-64',
          'w-64',
        )}
      >
      {header && <div className="px-3 py-4">{header}</div>}
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-2">
        <ul className="flex flex-col gap-1">
          {entries.map((entry) =>
            entry.type === 'leaf' ? (
              <li key={entry.label}>
                {collapsed ? (
                  <Tooltip label={entry.label} side="right">
                    <NavLink to={entry.to} className={cn(LEAF_CLASSES, 'justify-center')} aria-label={entry.label}>
                      {entry.icon}
                    </NavLink>
                  </Tooltip>
                ) : (
                  <NavLink to={entry.to} className={LEAF_CLASSES}>
                    {entry.icon}
                    {entry.label}
                  </NavLink>
                )}
              </li>
            ) : (
              <SidebarGroup key={entry.label} label={entry.label} icon={entry.icon} items={entry.items} collapsed={collapsed} />
            ),
          )}
        </ul>
      </nav>
      <button
        type="button"
        onClick={onToggleCollapsed}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        className="hidden items-center justify-center gap-2 border-t border-ink-700 px-3 py-3 text-sm text-gold-100/60 hover:text-gold-100 md:flex"
      >
        {collapsed ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
        {!collapsed && 'Collapse'}
      </button>
      </aside>
    </>
  )
}

function SidebarGroup({
  label,
  icon,
  items,
  collapsed,
}: {
  label: string
  icon?: ReactNode
  items: { label: string; to: string }[]
  collapsed: boolean
}) {
  const [expanded, setExpanded] = useState(false)

  if (collapsed) {
    return (
      <li>
        <Tooltip label={label} side="right">
          <button type="button" aria-label={label} className={cn(LEAF_CLASSES, 'w-full justify-center')}>
            {icon}
          </button>
        </Tooltip>
      </li>
    )
  }

  return (
    <li>
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        className={cn(LEAF_CLASSES, 'w-full justify-between')}
      >
        <span className="flex items-center gap-3">
          {icon}
          {label}
        </span>
        <ChevronDown size={14} aria-hidden="true" className={cn('transition-transform', expanded && 'rotate-180')} />
      </button>
      {expanded && (
        <ul className="ml-6 mt-1 flex flex-col gap-1 border-l border-ink-700 pl-3">
          {items.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} className={LEAF_CLASSES}>
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

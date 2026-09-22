import { useState } from 'react'
import { Home, Menu } from 'lucide-react'
import { Outlet } from 'react-router-dom'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { IconButton } from '@/components/ui/IconButton'
import { Sidebar } from '@/components/ui/Sidebar'
import { TopNav } from '@/components/ui/TopNav'
import { UserChip } from '@/components/ui/UserChip'
import type { NavEntry } from '@/components/ui/nav-types'
import { useAuth } from '@/lib/auth/AuthContext'

// The starting nav tree -- each future module (docs/ROADMAP.md Phase 2+)
// adds its own entries here as it's built, the same NavEntry[] shape
// Sidebar and TopNav both already accept and own no state of their own.
const NAV_ENTRIES: NavEntry[] = [{ type: 'leaf', label: 'Dashboard', to: '/', icon: <Home size={16} /> }]

/** The one authenticated app shell every protected route renders
 * inside -- composes Sidebar + TopNav exactly as
 * frontend/src/pages/StyleGuidePage.tsx demonstrates each
 * individually. A module adds a route (and a NAV_ENTRIES entry), not a
 * new layout. */
export function AppLayout() {
  const { user, logout } = useAuth()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <div className="min-h-screen bg-ink-950 text-gold-100">
      <TopNav
        logo={
          <span className="flex items-center gap-2">
            <IconButton
              icon={<Menu size={18} />}
              aria-label="Open navigation"
              className="md:hidden"
              onClick={() => setMobileOpen(true)}
            />
            <span className="font-display text-lg text-gold-400">JDK ERP</span>
          </span>
        }
        entries={NAV_ENTRIES}
        actions={
          <div className="flex items-center gap-3">
            <UserChip name={user?.full_name ?? ''} subtitle={user?.role} />
            <ActionMenu
              label="Account"
              options={[{ key: 'logout', label: 'Sign out', onSelect: () => void logout() }]}
            />
          </div>
        }
      />

      <div className="flex">
        <Sidebar
          entries={NAV_ENTRIES}
          collapsed={collapsed}
          onToggleCollapsed={() => setCollapsed((value) => !value)}
          mobileOpen={mobileOpen}
          onMobileClose={() => setMobileOpen(false)}
        />

        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

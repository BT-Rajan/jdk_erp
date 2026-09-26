import { useMemo, useState } from 'react'
import { Boxes, Home, Menu, Package, Settings, ShoppingCart, Wallet } from 'lucide-react'
import { Outlet } from 'react-router-dom'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { IconButton } from '@/components/ui/IconButton'
import { NotificationBell } from '@/components/ui/NotificationBell'
import { Sidebar } from '@/components/ui/Sidebar'
import { TopNav } from '@/components/ui/TopNav'
import { UserChip } from '@/components/ui/UserChip'
import type { NavEntry } from '@/components/ui/nav-types'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'

// The starting nav tree -- each future module (docs/ROADMAP.md Phase 2+)
// adds its own entries here as it's built, the same NavEntry[] shape
// Sidebar and TopNav both already accept and own no state of their own.
// UI visibility only (Principle 3) -- every page under Settings still
// enforces the same admin check server-side, via each endpoint it calls.
// Master Data sits in the general nav, not ADMIN_NAV_ENTRIES below --
// its read endpoints are open to any authenticated organisation member
// (docs/modules/categories.md #5), same as Teams/Users; only the
// mutating actions on each page are admin-gated, enforced server-side.
const NAV_ENTRIES: NavEntry[] = [
  { type: 'leaf', label: 'Dashboard', to: '/', icon: <Home size={16} /> },
  {
    type: 'group',
    label: 'Master Data',
    icon: <Boxes size={16} />,
    items: [
      { label: 'Categories', to: '/categories' },
      { label: 'Units of Measure', to: '/units-of-measure' },
      { label: 'Customers', to: '/customers' },
      { label: 'Suppliers', to: '/suppliers' },
      { label: 'Products', to: '/products' },
      { label: 'Raw Materials', to: '/raw-materials' },
      { label: 'Production Lines', to: '/production-lines' },
      { label: 'Machines', to: '/machines' },
      { label: 'Warehouses', to: '/warehouses' },
      { label: 'Bills of Materials', to: '/boms' },
    ],
  },
  {
    type: 'group',
    label: 'Procurement',
    icon: <ShoppingCart size={16} />,
    items: [
      { label: 'RFQs', to: '/rfqs' },
      { label: 'Purchase Orders', to: '/purchase-orders' },
      { label: 'Goods Receiving', to: '/receiving' },
    ],
  },
  {
    type: 'group',
    label: 'Inventory',
    icon: <Package size={16} />,
    items: [
      { label: 'Stock Adjustments', to: '/inventory/adjustments' },
      { label: 'Opening Stock', to: '/inventory/opening-stock' },
      { label: 'Reconciliation', to: '/inventory/reconciliation' },
      { label: 'Finished Goods Stock', to: '/inventory/finished-goods' },
      { label: 'Finished Goods Adjustments', to: '/inventory/finished-goods-adjustments' },
    ],
  },
  {
    type: 'group',
    label: 'Finance',
    icon: <Wallet size={16} />,
    items: [{ label: 'Payments', to: '/finance/payments' }],
  },
]
const ADMIN_NAV_ENTRIES: NavEntry[] = [
  {
    type: 'group',
    label: 'Settings',
    icon: <Settings size={16} />,
    items: [
      { label: 'Organisation', to: '/settings/organisation' },
      { label: 'Users', to: '/users' },
      { label: 'Email', to: '/settings/email' },
      { label: 'Documents', to: '/settings/documents' },
      { label: 'Working calendar', to: '/settings/working-calendar' },
    ],
  },
]

/** The one authenticated app shell every protected route renders
 * inside -- composes Sidebar + TopNav exactly as
 * frontend/src/pages/StyleGuidePage.tsx demonstrates each
 * individually. A module adds a route (and a NAV_ENTRIES entry), not a
 * new layout. */
export function AppLayout() {
  const { user, logout } = useAuth()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  const entries = useMemo(
    () => (isAdminRole(user?.role) ? [...NAV_ENTRIES, ...ADMIN_NAV_ENTRIES] : NAV_ENTRIES),
    [user?.role],
  )

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
        entries={entries}
        actions={
          <div className="flex items-center gap-3">
            <NotificationBell />
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
          entries={entries}
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

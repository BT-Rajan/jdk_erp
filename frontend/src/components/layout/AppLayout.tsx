import { useMemo, useState } from 'react'
import { Factory, FileText, Home, Menu, MessageCircle, Package, Settings, ShoppingCart, Wallet } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { AssistantDrawer } from '@/components/assistant/AssistantDrawer'
import { ActionMenu } from '@/components/ui/ActionMenu'
import { IconButton } from '@/components/ui/IconButton'
import { NotificationBell } from '@/components/ui/NotificationBell'
import { Sidebar } from '@/components/ui/Sidebar'
import { TopNav } from '@/components/ui/TopNav'
import { UserChip } from '@/components/ui/UserChip'
import type { NavEntry } from '@/components/ui/nav-types'
import { useAuth } from '@/lib/auth/AuthContext'
import { isAdminRole } from '@/lib/auth/roles'

// The nav tree -- each module adds its own entries here as it's built,
// in the NavEntry[] shape Sidebar accepts. The Sidebar is the one menu;
// the header carries no menu of its own (only a home icon).
// UI visibility only (Principle 3) -- every page still enforces its own
// access server-side, via each endpoint it calls.
const NAV_ENTRIES: NavEntry[] = [
  { type: 'leaf', label: 'Dashboard', to: '/', icon: <Home size={16} /> },
  {
    type: 'group',
    label: 'Sales',
    icon: <FileText size={16} />,
    items: [
      { label: 'Quotations', to: '/sales/quotations' },
      { label: 'Sales Orders', to: '/sales/orders' },
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
      { label: 'Deliveries', to: '/deliveries' },
    ],
  },
  {
    type: 'group',
    label: 'Production',
    icon: <Factory size={16} />,
    items: [
      { label: 'Requirements', to: '/production/requirements' },
      { label: 'Planning', to: '/production/planning' },
      { label: 'Schedule', to: '/production/schedule' },
      { label: 'Orders', to: '/production/orders' },
    ],
  },
  {
    type: 'group',
    label: 'Finance',
    icon: <Wallet size={16} />,
    items: [{ label: 'Payments', to: '/finance/payments' }],
  },
]

// Master Data lives under Settings for everyone -- its read endpoints are
// open to any organisation member (docs/modules/categories.md #5); only
// the mutating actions on each page are admin-gated, server-side.
const MASTER_DATA_ITEMS = [
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
]
// Admin-only settings pages, shown after Master Data.
const ADMIN_SETTINGS_ITEMS = [
  { label: 'Organisation', to: '/settings/organisation' },
  { label: 'Users', to: '/users' },
  { label: 'Email', to: '/settings/email' },
  { label: 'Documents', to: '/settings/documents' },
  { label: 'Working calendar', to: '/settings/working-calendar' },
  { label: 'AI Assistant', to: '/settings/assistant' },
]

/** The one authenticated app shell every protected route renders
 * inside: a header (logo, home icon, notifications, account) and the
 * Sidebar menu. A module adds a route (and a NAV_ENTRIES entry), not a
 * new layout. */
export function AppLayout() {
  const { user, logout } = useAuth()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [assistantOpen, setAssistantOpen] = useState(false)

  const entries = useMemo<NavEntry[]>(() => {
    const settings = isAdminRole(user?.role) ? [...MASTER_DATA_ITEMS, ...ADMIN_SETTINGS_ITEMS] : MASTER_DATA_ITEMS
    return [...NAV_ENTRIES, { type: 'group', label: 'Settings', icon: <Settings size={16} />, items: settings }]
  }, [user?.role])

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
            <NavLink
              to="/"
              end
              aria-label="Dashboard"
              className="rounded-md p-2 text-gold-100/70 transition-colors hover:text-gold-100 aria-[current=page]:text-gold-300"
            >
              <Home size={18} />
            </NavLink>
          </span>
        }
        actions={
          <div className="flex items-center gap-3">
            <IconButton
              icon={<MessageCircle size={18} />}
              aria-label="Open JDK Assistant"
              onClick={() => setAssistantOpen(true)}
            />
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

      <AssistantDrawer open={assistantOpen} onClose={() => setAssistantOpen(false)} />
    </div>
  )
}

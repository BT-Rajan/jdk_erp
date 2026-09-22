import { useState } from 'react'
import { Home, Menu, Package, Settings } from 'lucide-react'
import { ActionMenu } from './components/ui/ActionMenu'
import { ActiveFilterChips } from './components/ui/ActiveFilterChips'
import { Alert } from './components/ui/Alert'
import { AlertDialog } from './components/ui/AlertDialog'
import { Avatar } from './components/ui/Avatar'
import { Badge, StatusBadge } from './components/ui/Badge'
import { Breadcrumbs } from './components/ui/Breadcrumbs'
import { BulkActionsBar } from './components/ui/BulkActionsBar'
import { Button } from './components/ui/Button'
import { Card } from './components/ui/Card'
import { ConfirmDialog } from './components/ui/ConfirmDialog'
import { ContextMenu } from './components/ui/ContextMenu'
import { CopyToClipboard } from './components/ui/CopyToClipboard'
import { Currency } from './components/ui/Currency'
import { DataTable, type DataTableColumn } from './components/ui/DataTable'
import { DateTime } from './components/ui/DateTime'
import { Drawer } from './components/ui/Drawer'
import { EmptyState } from './components/ui/EmptyState'
import { FilterBar } from './components/ui/FilterBar'
import { FormDialog } from './components/ui/FormDialog'
import { FormSectionHeading } from './components/ui/FormSectionHeading'
import { IconButton } from './components/ui/IconButton'
import { KeyValue } from './components/ui/KeyValue'
import { Modal } from './components/ui/Modal'
import { MoreFiltersDisclosure } from './components/ui/MoreFiltersDisclosure'
import { AccessDeniedState } from './components/ui/AccessDeniedState'
import { PageErrorState } from './components/ui/PageErrorState'
import { ProgressBar } from './components/ui/ProgressBar'
import { Skeleton } from './components/ui/Skeleton'
import type { NavEntry } from './components/ui/nav-types'
import { NumberDisplay } from './components/ui/Number'
import { PageHeader } from './components/ui/PageHeader'
import { Percentage } from './components/ui/Percentage'
import { Sidebar } from './components/ui/Sidebar'
import type { SortState } from './components/ui/sort'
import { Spinner } from './components/ui/Spinner'
import { StatCard } from './components/ui/StatCard'
import { StatGrid } from './components/ui/StatGrid'
import { Tabs, TabPanel } from './components/ui/Tabs'
import { Tooltip } from './components/ui/Tooltip'
import { TopNav } from './components/ui/TopNav'
import { UserChip } from './components/ui/UserChip'
import { CheckboxField } from './components/forms/CheckboxField'
import { CurrencyField } from './components/forms/CurrencyField'
import { DateField } from './components/forms/DateField'
import { DateRangeField, type DateRangeValue } from './components/forms/DateRangeField'
import { FileUploadField } from './components/forms/FileUploadField'
import { MultiSelectField } from './components/forms/MultiSelectField'
import { NumberField } from './components/forms/NumberField'
import { RadioGroupField } from './components/forms/RadioGroupField'
import { SearchSelectField } from './components/forms/SearchSelectField'
import { SelectField } from './components/forms/SelectField'
import { TextField } from './components/forms/TextField'
import { TextareaField } from './components/forms/TextareaField'
import { LineChart } from './components/charts/LineChart'
import { BarChart } from './components/charts/BarChart'
import { PieChart } from './components/charts/PieChart'
import { formatCurrency } from './lib/format'
import { useFilters } from './lib/useFilters'

interface Supplier {
  id: number
  name: string
  balance: number
  status: string
}

const suppliers: Supplier[] = [
  { id: 1, name: 'Acme Corp', balance: 12500, status: 'active' },
  { id: 2, name: 'Globex Inc', balance: 3200, status: 'overdue' },
  { id: 3, name: 'Initech', balance: 0, status: 'inactive' },
]

const supplierColumns: DataTableColumn<Supplier>[] = [
  { key: 'name', label: 'Name', sortable: true, alwaysVisible: true, render: (row) => row.name },
  {
    key: 'balance',
    label: 'Balance',
    sortable: true,
    align: 'right',
    hideBelow: 'md',
    render: (row) => <Currency value={row.balance} />,
  },
  {
    key: 'status',
    label: 'Status',
    alwaysVisible: true,
    render: (row) => (
      <StatusBadge status={row.status} toneMap={{ active: 'success', overdue: 'danger', inactive: 'neutral' }} />
    ),
  },
]

const revenueByMonth = [
  { month: 'Apr', revenue: 42000, cost: 28000 },
  { month: 'May', revenue: 51000, cost: 31000 },
  { month: 'Jun', revenue: 47000, cost: 29500 },
  { month: 'Jul', revenue: 58000, cost: 33000 },
]

const spendByCategory = [
  { category: 'Raw materials', budget: 20000, actual: 18500 },
  { category: 'Labour', budget: 15000, actual: 16200 },
  { category: 'Logistics', budget: 8000, actual: 7100 },
]

const suppliersByStatus = [
  { status: 'Active', count: 92 },
  { status: 'Overdue', count: 12 },
  { status: 'Inactive', count: 24 },
]

const initialSupplierFilters = { search: '', status: 'all', owner: null as string | null }

const navEntries: NavEntry[] = [
  { type: 'leaf', label: 'Dashboard', to: '/', icon: <Home size={16} /> },
  { type: 'leaf', label: 'Suppliers', to: '/suppliers', icon: <Package size={16} /> },
  {
    type: 'group',
    label: 'Admin',
    icon: <Settings size={16} />,
    items: [
      { label: 'Users', to: '/admin/users' },
      { label: 'Roles', to: '/admin/roles' },
    ],
  },
]

export function App() {
  const [activeTab, setActiveTab] = useState('details')
  const [sort, setSort] = useState<SortState | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [sidebarMobileOpen, setSidebarMobileOpen] = useState(false)
  const [customer, setCustomer] = useState<string | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [selectedSuppliers, setSelectedSuppliers] = useState<Set<string | number>>(new Set())
  const [formDialogOpen, setFormDialogOpen] = useState(false)
  const [alertDialogOpen, setAlertDialogOpen] = useState(false)
  const [orderDateRange, setOrderDateRange] = useState<DateRangeValue>({ from: null, to: null })
  const filters = useFilters(initialSupplierFilters)

  return (
    <div className="min-h-screen bg-ink-950 text-gold-100">
      <TopNav
        logo={
          <span className="flex items-center gap-2">
            <IconButton
              icon={<Menu size={18} />}
              aria-label="Open navigation"
              className="md:hidden"
              onClick={() => setSidebarMobileOpen(true)}
            />
            <span className="font-display text-lg text-gold-400">JDK ERP</span>
          </span>
        }
        entries={navEntries}
        actions={<UserChip src={null} name="Ada Lovelace" subtitle="Admin" />}
      />

      <div className="flex">
        <Sidebar
          entries={navEntries}
          collapsed={sidebarCollapsed}
          onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
          mobileOpen={sidebarMobileOpen}
          onMobileClose={() => setSidebarMobileOpen(false)}
        />

        <main className="flex-1 space-y-10 p-6">
          <Breadcrumbs items={[{ label: 'Home', to: '/' }, { label: 'Suppliers', to: '/suppliers' }, { label: 'Acme Corp' }]} />

          <PageHeader
            title="Common UI Components"
            subtitle="Every component from docs/modules/common_ui_components.md, composed on one page for live verification."
            actions={
              <>
                <Button variant="secondary" onClick={() => setDrawerOpen(true)}>
                  Open drawer
                </Button>
                <Button onClick={() => setModalOpen(true)}>Open modal</Button>
                <ActionMenu
                  label="Row actions"
                  options={[
                    { key: 'edit', label: 'Edit', onSelect: () => {} },
                    { key: 'delete', label: 'Delete', onSelect: () => setConfirmOpen(true), danger: true },
                  ]}
                />
              </>
            }
          />

          <section className="space-y-3">
            <FormSectionHeading>1. Layout</FormSectionHeading>
            <Tabs
              items={[
                { id: 'details', label: 'Details' },
                { id: 'history', label: 'History' },
              ]}
              activeId={activeTab}
              onChange={setActiveTab}
            />
            <TabPanel id="details" activeId={activeTab}>
              <Card className="p-4">This is a Card inside a Tabs panel.</Card>
            </TabPanel>
            <TabPanel id="history" activeId={activeTab}>
              <Card className="p-4">History content.</Card>
            </TabPanel>
          </section>

          <section className="space-y-3">
            <FormSectionHeading>2. Actions</FormSectionHeading>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary">Primary</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="danger">Danger</Button>
              <Button variant="ghost">Ghost</Button>
              <Button isLoading>Loading</Button>
              <Button disabled>Disabled</Button>
              <Tooltip label="Edit this record">
                <IconButton icon={<Settings size={16} />} aria-label="Edit" />
              </Tooltip>
            </div>
          </section>

          <section className="space-y-3">
            <FormSectionHeading>3. Forms</FormSectionHeading>
            <FilterBar>
              <TextField label="Supplier name" placeholder="Search..." required />
              <NumberField label="Discount %" min={0} max={100} />
              <CurrencyField label="Credit limit" currency="USD" />
              <DateField label="Due date" />
              <SelectField label="Status">
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </SelectField>
            </FilterBar>
            <TextField label="Supplier code" value="ACME-001" readOnly hint="Assigned automatically, cannot be edited" />
            <MultiSelectField label="Teams">
              <option value="sales">Sales</option>
              <option value="ops">Operations</option>
              <option value="finance">Finance</option>
            </MultiSelectField>
            <SearchSelectField
              label="Customer"
              options={suppliers.map((s) => ({ value: String(s.id), label: s.name }))}
              value={customer}
              onChange={setCustomer}
              placeholder="Search suppliers..."
            />
            <CheckboxField label="Send confirmation email" />
            <RadioGroupField label="Payment terms" name="terms" options={[{ value: 'net30', label: 'Net 30' }, { value: 'net60', label: 'Net 60' }]} />
            <TextareaField label="Notes" />
            <FileUploadField label="Attachments" multiple value={files} onChange={setFiles} />
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setFormDialogOpen(true)}>
                Open form dialog
              </Button>
              <Button variant="secondary" onClick={() => setAlertDialogOpen(true)}>
                Open alert dialog
              </Button>
            </div>
          </section>

          <section className="space-y-3">
            <FormSectionHeading>4. Data &amp; Tables</FormSectionHeading>
            <StatGrid>
              <StatCard label="Open orders" value={42} hint="+5 this week" />
              <StatCard label="Overdue invoices" value={3} />
              <StatCard label="Active suppliers" value={128} />
              <StatCard label="Total spend" value={<Currency value={45800} />} />
            </StatGrid>
            <p className="text-xs text-gold-100/50">
              The Balance column below hides under the md breakpoint (resize the window to see it) -- Name and Status
              stay visible.
            </p>
            <BulkActionsBar
              count={selectedSuppliers.size}
              onClear={() => setSelectedSuppliers(new Set())}
              actions={[
                { key: 'export', label: 'Export', onSelect: () => {} },
                { key: 'delete', label: 'Delete', onSelect: () => setConfirmOpen(true), danger: true },
              ]}
            />
            <DataTable
              columns={supplierColumns}
              rows={suppliers}
              rowKey={(row) => row.id}
              sort={sort}
              onSortChange={setSort}
              enableColumnVisibility
              selectable
              selectedKeys={selectedSuppliers}
              onSelectionChange={setSelectedSuppliers}
              page={1}
              totalPages={1}
              total={suppliers.length}
              onPageChange={() => {}}
            />
            <Card className="grid grid-cols-2 gap-4 p-4">
              <KeyValue label="Registered name" value="Acme Corp" />
              <KeyValue label="Phone" />
            </Card>
          </section>

          <section className="space-y-3">
            <FormSectionHeading>Filters</FormSectionHeading>
            <FilterBar>
              <TextField
                label="Search"
                placeholder="Search by name..."
                value={filters.values.search}
                onChange={(e) => filters.setValue('search', e.target.value)}
              />
              <SelectField label="Status" value={filters.values.status} onChange={(e) => filters.setValue('status', e.target.value)}>
                <option value="all">All</option>
                <option value="active">Active</option>
                <option value="overdue">Overdue</option>
              </SelectField>
            </FilterBar>
            <ActiveFilterChips
              filters={(Object.keys(filters.values) as Array<keyof typeof filters.values>)
                .filter((key) => filters.values[key] && filters.values[key] !== initialSupplierFilters[key])
                .map((key) => ({
                  key: String(key),
                  label: `${String(key)}: ${filters.values[key]}`,
                  onRemove: () => filters.clearOne(key),
                }))}
              onClearAll={filters.activeCount > 0 ? filters.clear : undefined}
            />
            <MoreFiltersDisclosure>
              <FilterBar>
                <SearchSelectField
                  label="Owner"
                  options={suppliers.map((s) => ({ value: String(s.id), label: s.name }))}
                  value={filters.values.owner}
                  onChange={(value) => filters.setValue('owner', value)}
                />
                <DateRangeField label="Order date" value={orderDateRange} onChange={setOrderDateRange} />
              </FilterBar>
            </MoreFiltersDisclosure>
          </section>

          <section className="space-y-3">
            <FormSectionHeading>5. Feedback &amp; States</FormSectionHeading>
            <Spinner />
            <EmptyState title="No results" message="Try a different search." />
            <Alert variant="success">Saved successfully.</Alert>
            <Alert variant="warning">Low stock on 3 items.</Alert>
            <Alert variant="danger">Failed to save changes.</Alert>
            <Alert variant="info">Draft saved automatically.</Alert>
          </section>

          <section className="space-y-3">
            <FormSectionHeading>8. Standard Data Display</FormSectionHeading>
            <div className="flex flex-wrap items-center gap-4">
              <Currency value={1234.5} />
              <NumberDisplay value={1234567} />
              <DateTime value={new Date()} withTime />
              <Percentage value={12.5} />
              <Badge tone="gold">Featured</Badge>
              <Avatar src={null} name="Ada Lovelace" />
              <UserChip src={null} name="Ada Lovelace" subtitle="Admin" />
              <div className="flex items-center gap-1 text-sm">
                <span>INV-2026-001</span>
                <CopyToClipboard value="INV-2026-001" label="Copy invoice number" />
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <FormSectionHeading>9. Charts</FormSectionHeading>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card className="p-4">
                <p className="mb-2 text-sm text-gold-100/60">Revenue vs. cost (line)</p>
                <LineChart
                  data={revenueByMonth}
                  xKey="month"
                  series={[
                    { key: 'revenue', label: 'Revenue' },
                    { key: 'cost', label: 'Cost' },
                  ]}
                  valueFormatter={(v) => formatCurrency(v, 'USD')}
                  height={240}
                />
              </Card>
              <Card className="p-4">
                <p className="mb-2 text-sm text-gold-100/60">Budget vs. actual (stacked bar)</p>
                <BarChart
                  data={spendByCategory}
                  xKey="category"
                  stacked
                  series={[
                    { key: 'budget', label: 'Budget' },
                    { key: 'actual', label: 'Actual' },
                  ]}
                  valueFormatter={(v) => formatCurrency(v, 'USD')}
                  height={240}
                />
              </Card>
              <Card className="p-4">
                <p className="mb-2 text-sm text-gold-100/60">Suppliers by status (donut)</p>
                <PieChart data={suppliersByStatus} nameKey="status" valueKey="count" donut height={240} />
              </Card>
              <Card className="p-4">
                <p className="mb-2 text-sm text-gold-100/60">Loading / empty / error states</p>
                <div className="space-y-4">
                  <LineChart data={[]} xKey="month" series={[{ key: 'revenue', label: 'Revenue' }]} loading height={80} />
                  <LineChart data={[]} xKey="month" series={[{ key: 'revenue', label: 'Revenue' }]} height={80} />
                  <LineChart
                    data={[]}
                    xKey="month"
                    series={[{ key: 'revenue', label: 'Revenue' }]}
                    error="Failed to load revenue data"
                    height={80}
                  />
                </div>
              </Card>
            </div>
          </section>

          <section className="space-y-3">
            <FormSectionHeading>Context / Right-click Actions</FormSectionHeading>
            <p className="text-xs text-gold-100/50">
              The same options are reachable both ways -- the visible ⋮ menu (works everywhere, including touch) and,
              optionally, right-click on the card below (desktop convenience only, never the only path).
            </p>
            <ContextMenu
              label="Supplier actions"
              options={[
                { key: 'edit', label: 'Edit', onSelect: () => {} },
                { key: 'delete', label: 'Delete', onSelect: () => setConfirmOpen(true), danger: true },
              ]}
            >
              <Card className="flex items-center justify-between p-4">
                <span>Acme Corp -- right-click me, or use the menu</span>
                <ActionMenu
                  label="Supplier actions"
                  options={[
                    { key: 'edit', label: 'Edit', onSelect: () => {} },
                    { key: 'delete', label: 'Delete', onSelect: () => setConfirmOpen(true), danger: true },
                  ]}
                />
              </Card>
            </ContextMenu>
          </section>

          <section className="space-y-3">
            <FormSectionHeading>Additional Utility &amp; Display Components</FormSectionHeading>
            <div className="space-y-4">
              <ProgressBar value={64} label="Import progress" />
              <div className="flex items-center gap-3">
                <Skeleton className="h-9 w-9 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3 w-1/3" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              </div>
              <AccessDeniedState message="Only admins can view audit events." />
              <PageErrorState onRetry={() => {}} />
            </div>
          </section>
        </main>
      </div>

      <Modal open={modalOpen} title="Example modal" onClose={() => setModalOpen(false)} footer={<Button onClick={() => setModalOpen(false)}>Close</Button>}>
        <p>Modal content goes here.</p>
      </Modal>

      <Drawer open={drawerOpen} title="Example drawer" onClose={() => setDrawerOpen(false)}>
        <p>Drawer content goes here.</p>
      </Drawer>

      <ConfirmDialog
        open={confirmOpen}
        danger
        title="Delete supplier"
        message="This cannot be undone."
        onConfirm={() => setConfirmOpen(false)}
        onCancel={() => setConfirmOpen(false)}
      />

      <FormDialog
        open={formDialogOpen}
        title="New supplier"
        onClose={() => setFormDialogOpen(false)}
        onSubmit={(event) => {
          event.preventDefault()
          setFormDialogOpen(false)
        }}
      >
        <TextField label="Supplier name" required />
        <CurrencyField label="Opening balance" currency="USD" />
      </FormDialog>

      <AlertDialog
        open={alertDialogOpen}
        title="Import complete"
        message="42 suppliers were imported successfully."
        onClose={() => setAlertDialogOpen(false)}
        variant="success"
      />
    </div>
  )
}

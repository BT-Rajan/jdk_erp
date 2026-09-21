import { useState } from 'react'
import { Home, Package, Settings } from 'lucide-react'
import { ActionMenu } from './components/ui/ActionMenu'
import { Alert } from './components/ui/Alert'
import { Avatar } from './components/ui/Avatar'
import { Badge, StatusBadge } from './components/ui/Badge'
import { Breadcrumbs } from './components/ui/Breadcrumbs'
import { Button } from './components/ui/Button'
import { Card } from './components/ui/Card'
import { ConfirmDialog } from './components/ui/ConfirmDialog'
import { Currency } from './components/ui/Currency'
import { DataTable, type DataTableColumn } from './components/ui/DataTable'
import { DateTime } from './components/ui/DateTime'
import { Drawer } from './components/ui/Drawer'
import { EmptyState } from './components/ui/EmptyState'
import { FilterBar } from './components/ui/FilterBar'
import { FormSectionHeading } from './components/ui/FormSectionHeading'
import { IconButton } from './components/ui/IconButton'
import { KeyValue } from './components/ui/KeyValue'
import { Modal } from './components/ui/Modal'
import type { NavEntry } from './components/ui/nav-types'
import { NumberDisplay } from './components/ui/Number'
import { PageHeader } from './components/ui/PageHeader'
import { Percentage } from './components/ui/Percentage'
import { Sidebar } from './components/ui/Sidebar'
import type { SortState } from './components/ui/sort'
import { Spinner } from './components/ui/Spinner'
import { StatCard } from './components/ui/StatCard'
import { Tabs, TabPanel } from './components/ui/Tabs'
import { Tooltip } from './components/ui/Tooltip'
import { TopNav } from './components/ui/TopNav'
import { UserChip } from './components/ui/UserChip'
import { CheckboxField } from './components/forms/CheckboxField'
import { DateField } from './components/forms/DateField'
import { FileUploadField } from './components/forms/FileUploadField'
import { MultiSelectField } from './components/forms/MultiSelectField'
import { NumberField } from './components/forms/NumberField'
import { RadioGroupField } from './components/forms/RadioGroupField'
import { SearchSelectField } from './components/forms/SearchSelectField'
import { SelectField } from './components/forms/SelectField'
import { TextField } from './components/forms/TextField'
import { TextareaField } from './components/forms/TextareaField'

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
  { key: 'name', label: 'Name', sortable: true, render: (row) => row.name },
  { key: 'balance', label: 'Balance', sortable: true, align: 'right', render: (row) => <Currency value={row.balance} /> },
  {
    key: 'status',
    label: 'Status',
    render: (row) => (
      <StatusBadge status={row.status} toneMap={{ active: 'success', overdue: 'danger', inactive: 'neutral' }} />
    ),
  },
]

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
  const [customer, setCustomer] = useState<string | null>(null)
  const [files, setFiles] = useState<File[]>([])

  return (
    <div className="min-h-screen bg-ink-950 text-gold-100">
      <TopNav logo={<span className="font-display text-lg text-gold-400">JDK ERP</span>} entries={navEntries} actions={<UserChip src={null} name="Ada Lovelace" subtitle="Admin" />} />

      <div className="flex">
        <Sidebar entries={navEntries} collapsed={sidebarCollapsed} onToggleCollapsed={() => setSidebarCollapsed((v) => !v)} />

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
              <TextField label="Supplier name" placeholder="Search..." />
              <NumberField label="Discount %" min={0} max={100} />
              <DateField label="Due date" />
              <SelectField label="Status">
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </SelectField>
            </FilterBar>
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
          </section>

          <section className="space-y-3">
            <FormSectionHeading>4. Data &amp; Tables</FormSectionHeading>
            <div className="grid grid-cols-3 gap-4">
              <StatCard label="Open orders" value={42} hint="+5 this week" />
              <StatCard label="Overdue invoices" value={3} />
              <StatCard label="Active suppliers" value={128} />
            </div>
            <DataTable
              columns={supplierColumns}
              rows={suppliers}
              rowKey={(row) => row.id}
              sort={sort}
              onSortChange={setSort}
              enableColumnVisibility
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
    </div>
  )
}

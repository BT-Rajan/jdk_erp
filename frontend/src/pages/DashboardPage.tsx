import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { EmptyState } from '@/components/ui/EmptyState'
import { PageHeader } from '@/components/ui/PageHeader'
import { Tabs } from '@/components/ui/Tabs'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDate } from '@/lib/format'
import { useAuth } from '@/lib/auth/AuthContext'

/** Mirrors backend/app/schemas/action_item.py's ActionItemOut. */
interface ActionItem {
  type: string
  label: string
  entity: 'rfq' | 'purchase_order'
  id: number
  reference: string
  supplier_name: string | null
  detail: string | null
  date: string | null
}

function entityHref(item: ActionItem): string {
  return item.entity === 'rfq' ? `/rfqs/${item.id}` : `/purchase-orders/${item.id}`
}

/** Display order for the action-item `type` values backend/app/schemas/action_item.py
 * defines -- purely a display grouping, not a new status: a type not in this list
 * (future addition on the backend) still shows, just after these. */
const TYPE_ORDER = [
  'rfq_awaiting_response',
  'rfq_needs_decision',
  'po_pending_approval',
  'po_overdue',
  'po_partially_received',
  'po_requires_reconciliation',
  'po_requires_payment',
]

const ALL_TAB = 'all'

/** "What procurement items require my attention now?" -- GET
 * /api/action-items (backend/app/api/action_items.py) reuses the exact
 * RFQ/PO data and status logic the RFQ and Purchase Order screens
 * already compute; this page only lists it and links each row to that
 * existing screen. Not a dashboard of charts/KPIs -- one plain list. */
export function DashboardPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<ActionItem[] | null>(null)
  const [error, setError] = useState<string | undefined>(undefined)
  const [activeTab, setActiveTab] = useState<string>(ALL_TAB)

  useEffect(() => {
    apiClient
      .get<ActionItem[]>('/api/action-items')
      .then(({ data }) => setItems(data))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load action items.'))
  }, [])

  // Groups are derived purely from the `type`/`label` the backend already puts on
  // each item -- no new categorisation invented here, just a count per existing type
  // so the list can be filtered instead of scanned as one long table.
  const tabs = useMemo(() => {
    if (!items) return []
    const byType = new Map<string, { label: string; count: number }>()
    for (const item of items) {
      const existing = byType.get(item.type)
      byType.set(item.type, { label: item.label, count: (existing?.count ?? 0) + 1 })
    }
    const orderedTypes = [...byType.keys()].sort((a, b) => {
      const indexA = TYPE_ORDER.indexOf(a)
      const indexB = TYPE_ORDER.indexOf(b)
      if (indexA === -1 && indexB === -1) return a.localeCompare(b)
      if (indexA === -1) return 1
      if (indexB === -1) return -1
      return indexA - indexB
    })
    return [
      { id: ALL_TAB, label: 'All', badge: <Badge tone="neutral">{String(items.length)}</Badge> },
      ...orderedTypes.map((type) => {
        const group = byType.get(type)!
        return { id: type, label: group.label, badge: <Badge tone="neutral">{String(group.count)}</Badge> }
      }),
    ]
  }, [items])

  const visibleItems = useMemo(() => {
    if (!items) return []
    if (activeTab === ALL_TAB) return items
    return items.filter((item) => item.type === activeTab)
  }, [items, activeTab])

  const columns: DataTableColumn<ActionItem>[] = [
    {
      key: 'reference',
      label: 'Reference',
      render: (item) => (
        <Link to={entityHref(item)} className="text-gold-300 underline-offset-2 hover:underline">
          {item.reference}
        </Link>
      ),
    },
    { key: 'label', label: 'Needs', render: (item) => <Badge tone="warning">{item.label}</Badge> },
    { key: 'supplier', label: 'Supplier', hideBelow: 'sm', render: (item) => item.supplier_name ?? '—' },
    { key: 'detail', label: 'Detail', hideBelow: 'md', render: (item) => item.detail ?? '—' },
    { key: 'date', label: 'Date', hideBelow: 'md', render: (item) => (item.date ? formatDate(item.date) : '—') },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Welcome, ${user?.full_name ?? ''}`}
        subtitle="Action Required -- what needs your attention now, across RFQs and Purchase Orders."
      />
      <Alert variant="danger">{error}</Alert>
      {items && items.length === 0 ? (
        <EmptyState title="Nothing needs your attention" message="Every RFQ and Purchase Order you can see is up to date." />
      ) : (
        <>
          {tabs.length > 0 && <Tabs items={tabs} activeId={activeTab} onChange={setActiveTab} size="sm" />}
          <DataTable
            columns={columns}
            rows={visibleItems}
            rowKey={(item) => `${item.entity}-${item.id}-${item.type}`}
            loading={items === null}
          />
        </>
      )}
    </div>
  )
}

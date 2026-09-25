import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Badge } from '@/components/ui/Badge'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { EmptyState } from '@/components/ui/EmptyState'
import { PageHeader } from '@/components/ui/PageHeader'
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

/** "What procurement items require my attention now?" -- GET
 * /api/action-items (backend/app/api/action_items.py) reuses the exact
 * RFQ/PO data and status logic the RFQ and Purchase Order screens
 * already compute; this page only lists it and links each row to that
 * existing screen. Not a dashboard of charts/KPIs -- one plain list. */
export function DashboardPage() {
  const { user } = useAuth()
  const [items, setItems] = useState<ActionItem[] | null>(null)
  const [error, setError] = useState<string | undefined>(undefined)

  useEffect(() => {
    apiClient
      .get<ActionItem[]>('/api/action-items')
      .then(({ data }) => setItems(data))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load action items.'))
  }, [])

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
        <DataTable columns={columns} rows={items ?? []} rowKey={(item) => `${item.entity}-${item.id}-${item.type}`} loading={items === null} />
      )}
    </div>
  )
}

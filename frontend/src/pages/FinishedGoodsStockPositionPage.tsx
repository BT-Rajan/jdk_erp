import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/Alert'
import { Badge, type BadgeTone } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { DataTable, type DataTableColumn } from '@/components/ui/DataTable'
import { Drawer } from '@/components/ui/Drawer'
import { PageHeader } from '@/components/ui/PageHeader'
import { Spinner } from '@/components/ui/Spinner'
import { ApiError, apiClient } from '@/lib/apiClient'
import { formatDateTime, formatNumber } from '@/lib/format'

/** Mirrors backend/app/schemas/finished_goods_inventory.py's
 * FinishedGoodsStockPositionOut. warehouse_id/warehouse_name/
 * quantity_on_hand are only null for a `no_record` row -- a Product
 * that has never had a Finished Goods movement recorded anywhere. */
interface StockPosition {
  product_id: number
  product_code: string
  product_name: string
  product_is_active: boolean
  category_id: number
  category_name: string
  warehouse_id: number | null
  warehouse_name: string | null
  unit_of_measure_id: number
  unit_code: string
  quantity_on_hand: string | null
  status: 'in_stock' | 'out_of_stock' | 'no_record'
}

const STATUS_LABELS: Record<StockPosition['status'], string> = {
  in_stock: 'In Stock',
  out_of_stock: 'Out of Stock',
  no_record: 'No Stock Record',
}

const STATUS_TONES: Record<StockPosition['status'], BadgeTone> = {
  in_stock: 'success',
  out_of_stock: 'neutral',
  no_record: 'neutral',
}

/** Mirrors FinishedGoodsMovementOut. */
interface MovementEntry {
  id: number
  movement_type: string
  quantity: string
  unit_of_measure_id: number
  unit_code: string
  resulting_balance: string
  reference_type: string
  reference_id: number
  created_by_user_id: number | null
  created_by_name: string | null
  created_at: string
}

const MOVEMENT_TYPE_LABELS: Record<string, string> = {
  production_completion: 'Production Completion',
  delivery: 'Delivery',
  adjustment: 'Adjustment',
}

const MOVEMENT_TYPE_TONES: Record<string, BadgeTone> = {
  production_completion: 'success',
  delivery: 'warning',
  adjustment: 'info',
}

/** The current stock position of every manufactured Product, by
 * warehouse (backend/app/api/finished_goods_inventory.py's
 * list_stock_positions) -- a read-only report, the same "plain list,
 * fetch and render, no pagination" shape InventoryReconciliationPage
 * already established for a per-organisation Inventory listing of this
 * size. Every Product in the organisation is listed, not just ones
 * with recorded stock -- a Product that has never moved shows with a
 * `No Stock Record` status and no warehouse/quantity, distinguishable
 * from a real ledger that nets to zero (`Out of Stock`). "View History"
 * opens each row's own movement history in a Drawer (rule 6) rather
 * than navigating away -- this screen is primarily for viewing and
 * control, not direct quantity editing: there is no inline-edit path on
 * any cell here at all. Correcting a balance is a separate, deliberate
 * action on FinishedGoodsAdjustmentsPage. */
export function FinishedGoodsStockPositionPage() {
  const navigate = useNavigate()
  const [positions, setPositions] = useState<StockPosition[] | null>(null)
  const [error, setError] = useState<string | undefined>(undefined)

  const openAdjustment = (p: StockPosition) =>
    navigate('/inventory/finished-goods-adjustments', {
      state: { productId: p.product_id, warehouseId: p.warehouse_id ?? undefined },
    })

  const [historyTarget, setHistoryTarget] = useState<StockPosition | null>(null)
  const [movements, setMovements] = useState<MovementEntry[] | null>(null)
  const [historyError, setHistoryError] = useState<string | undefined>(undefined)

  useEffect(() => {
    apiClient
      .get<StockPosition[]>('/api/finished-goods-inventory')
      .then(({ data }) => setPositions(data))
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load Finished Goods stock positions.'))
  }, [])

  function openHistory(position: StockPosition) {
    setHistoryTarget(position)
    setMovements(null)
    setHistoryError(undefined)
    apiClient
      .get<MovementEntry[]>('/api/finished-goods-inventory/movements', {
        params: { product_id: position.product_id, warehouse_id: position.warehouse_id },
      })
      .then(({ data }) => setMovements(data))
      .catch((err) => setHistoryError(err instanceof ApiError ? err.message : 'Failed to load movement history.'))
  }

  const columns: DataTableColumn<StockPosition>[] = [
    { key: 'product_code', label: 'Product Code', render: (p) => p.product_code },
    { key: 'product_name', label: 'Product', render: (p) => p.product_name },
    { key: 'category_name', label: 'Category', hideBelow: 'sm', render: (p) => p.category_name },
    { key: 'warehouse_name', label: 'Warehouse', render: (p) => p.warehouse_name ?? '—' },
    { key: 'unit_code', label: 'Stock UOM', hideBelow: 'sm', render: (p) => p.unit_code },
    {
      key: 'quantity_on_hand',
      label: 'Quantity on Hand',
      align: 'right',
      render: (p) => (p.quantity_on_hand !== null ? `${formatNumber(p.quantity_on_hand)} ${p.unit_code}` : '—'),
    },
    {
      key: 'status',
      label: 'Status',
      render: (p) => <Badge tone={STATUS_TONES[p.status]}>{STATUS_LABELS[p.status]}</Badge>,
    },
    {
      key: 'product_is_active',
      label: 'Active',
      hideBelow: 'md',
      render: (p) => (
        <Badge tone={p.product_is_active ? 'success' : 'neutral'}>{p.product_is_active ? 'Active' : 'Inactive'}</Badge>
      ),
    },
    {
      key: 'actions',
      label: '',
      alwaysVisible: true,
      align: 'right',
      render: (p) => (
        <div className="flex justify-end gap-2">
          {p.warehouse_id !== null ? (
            <Button variant="secondary" size="sm" onClick={() => openHistory(p)}>
              View History
            </Button>
          ) : (
            <span className="text-xs text-gold-100/40">No movements yet</span>
          )}
          <Button variant="secondary" size="sm" onClick={() => openAdjustment(p)}>
            Adjust
          </Button>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Finished Goods Stock Position"
        subtitle="Current stock on hand for every manufactured Product, by warehouse."
      />
      <Alert variant="danger">{error}</Alert>

      <DataTable
        columns={columns}
        rows={positions ?? []}
        rowKey={(p) => `${p.product_id}-${p.warehouse_id ?? 'none'}`}
        loading={positions === null}
        emptyTitle="No Finished Goods Products yet"
        emptyMessage="Products will appear here as soon as they exist -- quantities populate once a production completion, delivery or adjustment is recorded."
      />

      <Drawer
        open={historyTarget !== null}
        title={historyTarget ? `${historyTarget.product_name} @ ${historyTarget.warehouse_name ?? '—'}` : 'Movement History'}
        onClose={() => setHistoryTarget(null)}
      >
        <Alert variant="danger">{historyError}</Alert>
        {!historyError && movements === null && (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        )}
        {movements && movements.length === 0 && (
          <p className="text-sm text-gold-100/60">No movements recorded yet.</p>
        )}
        {movements && movements.length > 0 && (
          <ul className="space-y-3">
            {movements.map((m) => (
              <li key={m.id} className="rounded-md border border-ink-700 p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <Badge tone={MOVEMENT_TYPE_TONES[m.movement_type] ?? 'neutral'}>
                    {MOVEMENT_TYPE_LABELS[m.movement_type] ?? m.movement_type}
                  </Badge>
                  <span className="text-xs text-gold-100/60">{formatDateTime(m.created_at)}</span>
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <span className={Number(m.quantity) < 0 ? 'text-danger-500' : 'text-success-500'}>
                    {Number(m.quantity) >= 0 ? '+' : ''}
                    {formatNumber(m.quantity)} {m.unit_code}
                  </span>
                  <span className="text-gold-100/70">
                    Balance: {formatNumber(m.resulting_balance)} {m.unit_code}
                  </span>
                </div>
                <div className="mt-1 text-xs text-gold-100/50">
                  Ref: {m.reference_type} #{m.reference_id}
                  {m.created_by_name && ` · ${m.created_by_name}`}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Drawer>
    </div>
  )
}
